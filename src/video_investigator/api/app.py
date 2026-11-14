"""FastAPI application. Loopback by default, explicit CORS allowlist, no filesystem paths in responses."""
from __future__ import annotations
import hashlib, hmac, json, os, re, shutil, uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from fastapi import BackgroundTasks, FastAPI, File, Form, Header, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from ..config import Settings, load_settings
from ..db import models as m
from ..db.session import make_engine, migrate, session_factory, session_scope
from ..events.geometry import validate_polygon
from ..media.probe import MediaError, probe, sha256_file, validate_limits
from ..paths import data_dir, evaluations_dir, runs_dir, uploads_tmp, videos_dir
from ..reports import export
from ..search import engine as search_engine
from ..search import semantic
from ..explain import vlm
from ..worker import store
from . import schemas
from .errors import ApiError, install

CORS_ORIGINS = [o for o in os.environ.get("VI_CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173").split(",") if o]
ALLOWED_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
EVIDENCE_NAME = re.compile(r"^(?:(?:start|mid|end)(?:_original)?\.jpg|clip\.mp4)$")
OVERRIDE_SECTIONS = {"processing", "detector", "tracker", "events", "quality", "search"}
OVERRIDE_DETECTOR_KEYS = {"score_threshold"}   # changing the detector architecture or weights is not a runtime option


class BodyLimit:
    """Pure ASGI middleware: count request-body bytes as they stream in and refuse with 413 once the cap is passed, before buffering it all."""
    def __init__(self, app, max_bytes: int):
        self.app, self.max = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] != "/api/videos":
            return await self.app(scope, receive, send)
        total = 0; started = False

        class TooLarge(Exception):
            pass

        async def counted():
            nonlocal total
            msg = await receive()
            if msg["type"] == "http.request":
                total += len(msg.get("body", b""))
                if total > self.max:
                    raise TooLarge()
            return msg

        async def tracked_send(msg):
            nonlocal started
            if msg["type"] == "http.response.start":
                started = True
            await send(msg)
        cl = dict(scope["headers"]).get(b"content-length")
        try:
            if cl and int(cl) > self.max:
                raise TooLarge()
            await self.app(scope, counted, tracked_send)
        except TooLarge:
            if not started:
                resp = JSONResponse({"error": {"code": "too_large", "message": f"The upload exceeds the {self.max // 2**20} MiB limit."}}, status_code=413)
                await resp(scope, receive, send)


def create_app() -> FastAPI:
    settings = load_settings()
    if os.environ.get("VI_UPLOAD_MAX_BYTES"):            # test/ops override of the upload cap
        settings.limits.upload_max_bytes = int(os.environ["VI_UPLOAD_MAX_BYTES"])

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = make_engine(); migrate(engine)
        app.state.engine, app.state.factory, app.state.settings = engine, session_factory(engine), settings
        yield
        engine.dispose()

    app = FastAPI(title="Video Investigation Platform", version="0.1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["GET", "POST", "PUT"], allow_headers=["Content-Type", "Range"],
                       expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"])
    app.add_middleware(BodyLimit, max_bytes=settings.limits.upload_max_bytes + 1_048_576)   # + multipart overhead
    install(app)
    F = lambda: app.state.factory

    # ---------- optional access token (for hosting beyond loopback) ----------
    api_token = os.environ.get("VI_API_TOKEN") or None
    session_cookie = hmac.new(api_token.encode(), b"scenetrace-session-v1", "sha256").hexdigest() if api_token else None

    def authed(request: Request) -> bool:
        if not api_token:
            return True
        bearer = request.headers.get("authorization", "")
        if bearer.lower().startswith("bearer ") and hmac.compare_digest(bearer[7:].strip(), api_token):
            return True
        return hmac.compare_digest(request.cookies.get("vi_session", ""), session_cookie or "x")

    @app.middleware("http")
    async def require_token(request: Request, call_next):
        p = request.url.path
        if api_token and p.startswith("/api/") and p not in ("/api/health", "/api/session") and request.method != "OPTIONS" and not authed(request):
            return JSONResponse({"error": {"code": "auth_required", "message": "An access token is required."}}, status_code=401)
        return await call_next(request)

    @app.get("/api/session")
    def session_state(request: Request):
        return {"required": bool(api_token), "authenticated": authed(request)}

    @app.post("/api/session")
    def session_login(body: dict, request: Request):
        if not api_token or not hmac.compare_digest(str(body.get("token", "")), api_token):
            raise ApiError(401, "auth_failed", "That access token was not accepted.")
        resp = JSONResponse({"required": True, "authenticated": True})
        resp.set_cookie("vi_session", session_cookie, httponly=True, samesite="lax", secure=request.url.scheme == "https", max_age=8 * 3600)
        return resp

    # ---------- serializers (never expose paths) ----------
    def video_out(v: m.Video) -> dict:
        return {"id": v.id, "display_name": v.display_name, "source_sha256": v.source_sha256, "size_bytes": v.size_bytes, "duration_ms": v.duration_ms, "width": v.width,
                "height": v.height, "codec": v.meta.get("codec"), "fps": v.meta.get("avg_fps"), "rotation": v.meta.get("rotation"), "timestamps_ok": v.meta.get("timestamps_ok"),
                "ready": v.derivative_status == "ready", "derivative_status": v.derivative_status, "derivative_error": v.derivative_error,
                "media_url": f"/api/videos/{v.id}/media" if v.derivative_status == "ready" else None, "created_at": v.created_at.isoformat() + "Z"}

    def run_out(r: m.Run) -> dict:
        return {"id": r.id, "video_id": r.video_id, "zone_version": r.zone_version, "state": r.state, "attempt": r.attempt, "progress": r.progress, "processed_ms": r.processed_ms,
                "errors": r.errors or [], "quality_flags": r.quality_flags or [], "cancel_requested": r.cancel_requested, "complete": r.state == "completed",
                "config_hash": r.config_hash, "pipeline_version": r.pipeline_version, "detector": r.detector, "timings": r.timings, "manifest_sha256": r.manifest_sha256,
                "zones": r.zones, "created_at": r.created_at.isoformat() + "Z", "finished_at": r.finished_at.isoformat() + "Z" if r.finished_at else None,
                "data_source": "detector", "retry_count": r.retry_count}

    def event_out(e: m.Event) -> dict:
        return {"id": e.id, "event_key": e.event_key, "evidence_base": f"/api/runs/{e.run_id}/evidence/{e.event_key}/", "run_id": e.run_id, "type": e.type, "zone_id": e.zone_id, "start_ms": e.start_ms, "end_ms": e.end_ms, "track_ids": e.track_ids, "class_name": e.class_name,
                "rule_version": e.rule_version, "details": e.details, "uncertainty_flags": e.uncertainty_flags, "evidence": e.evidence, "description": e.description, "group_id": e.group_id,
                "source": e.source, "review_status": e.review_status, "review_note": e.review_note, "review_version": e.review_version,
                "reviewed_at": e.reviewed_at.isoformat() + "Z" if e.reviewed_at else None}

    def get_or_404(s, model, ident, what):
        row = s.get(model, ident)
        if row is None:
            raise ApiError(404, f"{what}_not_found", f"No such {what}.")
        return row

    # ---------- health / config ----------
    @app.get("/api/health")
    def health():
        with session_scope(F()) as s:
            s.execute(select(func.count()).select_from(m.Video))
        return {"ok": True, "schema": "ready", "config_hash": settings.config_hash(), "mode": "live"}

    @app.get("/api/config")
    def config():
        return {"settings": settings.model_dump(), "config_hash": settings.config_hash()}

    # ---------- videos ----------
    def make_derivative(video_id: str):
        from ..reports.evidence import make_playable_derivative
        with session_scope(F()) as s:
            v = s.get(m.Video, video_id); src = data_dir() / v.original_rel
        dst = videos_dir() / video_id / "derivative.mp4"
        try:
            make_playable_derivative(src, dst)
            status, err, rel = "ready", None, str(dst.relative_to(data_dir()))
        except Exception as e:  # ffmpeg missing, codec problem
            status, err, rel = "failed", str(e)[:400], None
        with session_scope(F()) as s:
            v = s.get(m.Video, video_id); v.derivative_status, v.derivative_error, v.derivative_rel = status, err, rel

    @app.post("/api/videos", status_code=201)
    async def upload_video(background: BackgroundTasks, file: UploadFile = File(...), display_name: str = Form("")):
        lim = settings.limits
        tmp = uploads_tmp() / f"{uuid.uuid4().hex}.part"
        size = 0
        try:
            with open(tmp, "wb") as out:
                while chunk := await file.read(1 << 20):
                    size += len(chunk)
                    if size > lim.upload_max_bytes:
                        raise ApiError(413, "too_large", f"The upload exceeds the {lim.upload_max_bytes // 2**20} MiB limit.")
                    out.write(chunk)
            if size == 0:
                raise ApiError(422, "empty_file", "The uploaded file is empty.")
            try:
                info = probe(tmp)
                validate_limits(info, max_bytes=lim.upload_max_bytes, max_seconds=lim.upload_max_seconds)
            except MediaError as e:
                raise ApiError(413 if e.code == "too_large" else 422, e.code, e.message)
            ext = Path(file.filename or "").suffix.lower()
            ext = ext if ext in ALLOWED_EXT else ".video"
            vid = str(uuid.uuid4())
            dest = videos_dir() / vid / f"original{ext}"
            dest.parent.mkdir(parents=True)
            shutil.move(str(tmp), dest)
            name = re.sub(r"[\x00-\x1f\x7f]", "", (display_name or Path(file.filename or "video").stem))[:200].strip() or "video"
            with session_scope(F()) as s:
                v = m.Video(id=vid, display_name=name, source_sha256=sha256_file(dest), size_bytes=info.size_bytes, duration_ms=info.duration_ms, width=info.width, height=info.height,
                            meta=info.to_dict(), original_rel=str(dest.relative_to(data_dir())))
                s.add(v); s.flush(); out_json = video_out(v)
            background.add_task(make_derivative, vid)
            return out_json
        finally:
            tmp.unlink(missing_ok=True)

    @app.get("/api/videos")
    def list_videos():
        with session_scope(F()) as s:
            return {"videos": [video_out(v) for v in s.scalars(select(m.Video).order_by(m.Video.created_at.desc()))]}

    @app.get("/api/videos/{video_id}")
    def get_video(video_id: str):
        with session_scope(F()) as s:
            v = get_or_404(s, m.Video, video_id, "video")
            zs = s.scalar(select(func.max(m.ZoneSet.version)).where(m.ZoneSet.video_id == video_id))
            return {**video_out(v), "zone_version": zs}

    def _range(header: str | None, size: int):
        if not header:
            return None
        mt = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
        if not mt or (mt.group(1) == "" and mt.group(2) == ""):
            raise ApiError(416, "invalid_range", "Unsupported Range header.")
        a, b = mt.group(1), mt.group(2)
        if a == "":
            n = int(b); start, end = max(0, size - n), size - 1
        else:
            start = int(a); end = int(b) if b else size - 1
        end = min(end, size - 1)
        if start >= size or start > end:
            raise ApiError(416, "range_not_satisfiable", "Requested range is outside the file.")
        return start, end

    def _serve(path: Path, ctype: str, range_header: str | None):
        size = path.stat().st_size
        rng = _range(range_header, size)
        if rng is None:
            return FileResponse(path, media_type=ctype, headers={"Accept-Ranges": "bytes"})
        start, end = rng
        with open(path, "rb") as f:
            f.seek(start); data = f.read(end - start + 1)
        return Response(data, status_code=206, media_type=ctype, headers={"Content-Range": f"bytes {start}-{end}/{size}", "Accept-Ranges": "bytes", "Content-Length": str(len(data))})

    @app.get("/api/videos/{video_id}/media")
    def video_media(video_id: str, variant: str = Query("playable", pattern="^(playable|original)$"), range: str | None = Header(default=None)):
        with session_scope(F()) as s:
            v = get_or_404(s, m.Video, video_id, "video")
            if variant == "original":
                p, ctype = data_dir() / v.original_rel, "application/octet-stream"
            else:
                if v.derivative_status != "ready":
                    raise ApiError(409, "not_ready", f"The browser-playable version is {v.derivative_status}.", derivative_status=v.derivative_status, detail=v.derivative_error)
                p, ctype = data_dir() / v.derivative_rel, "video/mp4"
        return _serve(p, ctype, range)

    # ---------- zones ----------
    @app.put("/api/videos/{video_id}/zones")
    def put_zones(video_id: str, body: schemas.ZonesPut):
        ids = [z.id for z in body.zones]
        if len(ids) != len(set(ids)):
            raise ApiError(422, "duplicate_zone_id", "Zone ids must be unique.")
        for z in body.zones:
            err = validate_polygon([tuple(p) for p in z.polygon])
            if err:
                raise ApiError(422, "invalid_polygon", f"Zone '{z.name}': {err}", zone_id=z.id)
        with session_scope(F()) as s:
            get_or_404(s, m.Video, video_id, "video")
            ver = (s.scalar(select(func.max(m.ZoneSet.version)).where(m.ZoneSet.video_id == video_id)) or 0) + 1
            zs = m.ZoneSet(video_id=video_id, version=ver, zones=[z.model_dump() for z in body.zones]); s.add(zs)
            return {"video_id": video_id, "version": ver, "zones": zs.zones}

    @app.get("/api/videos/{video_id}/zones")
    def get_zones(video_id: str, version: int | None = None):
        with session_scope(F()) as s:
            get_or_404(s, m.Video, video_id, "video")
            q = select(m.ZoneSet).where(m.ZoneSet.video_id == video_id)
            q = q.where(m.ZoneSet.version == version) if version else q.order_by(m.ZoneSet.version.desc())
            zs = s.scalars(q).first()
            return {"video_id": video_id, "version": zs.version if zs else None, "zones": zs.zones if zs else []}

    # ---------- runs ----------
    def merged_settings(overrides: dict) -> Settings:
        for k, v in overrides.items():
            if k not in OVERRIDE_SECTIONS:
                raise ApiError(422, "override_not_allowed", f"'{k}' cannot be overridden per run.")
            if k == "detector" and (not isinstance(v, dict) or set(v) - OVERRIDE_DETECTOR_KEYS):
                raise ApiError(422, "override_not_allowed", "Only detector.score_threshold can be overridden.")
        try:
            return load_settings(overrides=overrides or None)
        except Exception as e:
            raise ApiError(422, "invalid_config", str(e).splitlines()[0][:300])

    @app.post("/api/runs", status_code=202)
    def create_run(body: schemas.RunCreate):
        with session_scope(F()) as s:
            if body.client_request_id:
                existing = s.scalars(select(m.Run).where(m.Run.client_request_id == body.client_request_id)).first()
                if existing:
                    return {**run_out(existing), "deduplicated": True}
            v = get_or_404(s, m.Video, body.video_id, "video")
            if not v.meta.get("timestamps_ok"):
                raise ApiError(422, "unsupported_timing", "This video has no usable timing metadata, so event times cannot be trusted.")
            q = select(m.ZoneSet).where(m.ZoneSet.video_id == v.id)
            q = q.where(m.ZoneSet.version == body.zone_version) if body.zone_version else q.order_by(m.ZoneSet.version.desc())
            zs = s.scalars(q).first()
            if zs is None:
                raise ApiError(422, "zones_required", "Define at least one zone for this video before processing (PUT /api/videos/{id}/zones).")
            cfg = merged_settings(body.config_overrides)
            run = m.Run(video_id=v.id, zone_version=zs.version, zones=zs.zones, config=cfg.model_dump(), config_hash=cfg.config_hash(), client_request_id=body.client_request_id)
            s.add(run); s.flush()
            return {**run_out(run), "deduplicated": False}

    @app.get("/api/runs")
    def list_runs(video_id: str | None = None):
        with session_scope(F()) as s:
            q = select(m.Run).order_by(m.Run.created_at.desc())
            if video_id:
                q = q.where(m.Run.video_id == video_id)
            return {"runs": [run_out(r) for r in s.scalars(q)]}

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str):
        with session_scope(F()) as s:
            return run_out(get_or_404(s, m.Run, run_id, "run"))

    @app.post("/api/runs/{run_id}/cancel")
    def cancel_run(run_id: str):
        try:
            state, accepted = store.request_cancel(F(), run_id)
        except KeyError:
            raise ApiError(404, "run_not_found", "No such run.")
        if not accepted:
            raise ApiError(409, "invalid_state", f"A {state} run cannot be cancelled.", state=state)
        return {"id": run_id, "state": state, "cancel_requested": True}

    @app.post("/api/runs/{run_id}/restart", status_code=202)
    def restart(run_id: str):
        try:
            state, ok = store.restart_run(F(), run_id)
        except KeyError:
            raise ApiError(404, "run_not_found", "No such run.")
        if not ok:
            raise ApiError(409, "invalid_state", f"A {state} run cannot be restarted.", state=state)
        return {"id": run_id, "state": state}

    def current_run(s, run_id: str) -> m.Run:
        return get_or_404(s, m.Run, run_id, "run")

    @app.get("/api/runs/{run_id}/observations")
    def observations(run_id: str, start_ms: int = Query(0, ge=0), end_ms: int | None = Query(None, ge=0), limit: int = Query(1000, ge=1, le=5000), cursor: int | None = Query(None, ge=0)):
        with session_scope(F()) as s:
            r = current_run(s, run_id)
            if r.state != "completed":
                return {"run_id": run_id, "complete": False, "run_state": r.state, "observations": [], "next_cursor": None,
                        "note": "Observations are published only when a run completes; this run has no finalized evidence."}
            q = select(m.Observation).where(m.Observation.run_id == run_id, m.Observation.attempt == r.attempt, m.Observation.t_ms >= start_ms)
            if end_ms is not None:
                q = q.where(m.Observation.t_ms <= end_ms)
            if cursor:
                q = q.where(m.Observation.id > cursor)
            rows = list(s.scalars(q.order_by(m.Observation.id).limit(limit + 1)))
            more = len(rows) > limit; rows = rows[:limit]
            return {"run_id": run_id, "complete": True, "run_state": r.state, "coordinate_space": "normalized_xyxy_upright",
                    "observations": [{"t_ms": o.t_ms, "track_id": o.track_id, "class_name": o.class_name, "confidence": o.confidence, "box": [o.x1, o.y1, o.x2, o.y2],
                                      "track_state": o.track_state, "source": o.source} for o in rows], "next_cursor": rows[-1].id if more and rows else None}

    def _events(s, r: m.Run, **f) -> list[dict]:
        q = select(m.Event).where(m.Event.run_id == r.id, m.Event.attempt == r.attempt).order_by(m.Event.start_ms, m.Event.id)
        if f.get("type"): q = q.where(m.Event.type == f["type"])
        if f.get("zone_id"): q = q.where(m.Event.zone_id == f["zone_id"])
        if f.get("review_status"): q = q.where(m.Event.review_status == f["review_status"])
        if f.get("start_ms") is not None: q = q.where(m.Event.end_ms >= f["start_ms"])
        if f.get("end_ms") is not None: q = q.where(m.Event.start_ms <= f["end_ms"])
        return [event_out(e) for e in s.scalars(q)]

    @app.get("/api/runs/{run_id}/events")
    def events(run_id: str, type: str | None = None, zone_id: str | None = None, review_status: str | None = None, start_ms: int | None = None, end_ms: int | None = None,
               limit: int = Query(100, ge=1, le=500), cursor: int = Query(0, ge=0)):
        with session_scope(F()) as s:
            r = current_run(s, run_id)
            rows = _events(s, r, type=type, zone_id=zone_id, review_status=review_status, start_ms=start_ms, end_ms=end_ms) if r.state == "completed" else []
            page = rows[cursor:cursor + limit]
            return {"run_id": run_id, "complete": r.state == "completed", "run_state": r.state, "quality_flags": r.quality_flags or [], "total": len(rows), "events": page,
                    "next_cursor": cursor + limit if cursor + limit < len(rows) else None,
                    "note": None if r.state == "completed" else "No finalized events: the run is not completed."}

    @app.post("/api/runs/{run_id}/search")
    def search(run_id: str, body: schemas.SearchBody):
        with session_scope(F()) as s:
            r = current_run(s, run_id)
            lim = min(body.limit or settings.search.default_limit, settings.search.max_limit)
            c = search_engine.parse_query(body.query or "", r.zones)
            f = body.filters or {}
            if f.get("type"): c.types.add(f["type"])
            if f.get("class_name"): c.classes.add(f["class_name"])
            if f.get("zone_id"): c.zone_ids.add(f["zone_id"])
            if f.get("review_status"): c.review_status.add(f["review_status"])
            if f.get("after_ms") is not None: c.after_ms = int(f["after_ms"])
            if f.get("before_ms") is not None: c.before_ms = int(f["before_ms"])
            interpreted = {"event_types": sorted(c.types), "classes": sorted(c.classes), "zone_ids": sorted(c.zone_ids), "review_status": sorted(c.review_status),
                           "after_ms": c.after_ms, "before_ms": c.before_ms, "understood": c.recognised, "ignored_terms": c.ignored}
            if r.state != "completed":
                return {"results": [], "interpreted": interpreted, "unsupported": False, "notices": ["The run is not completed, so there are no finalized events to search."], "limit": lim}
            if c.notices:
                return {"results": [], "interpreted": interpreted, "unsupported": True, "notices": c.notices + ["No events were inferred for this query."], "limit": lim}
            if c.is_empty():
                msg = "The query matched no supported constraint (event type, object class, zone, review status or time). No events were inferred." if (body.query or "").strip() else "Provide a query or at least one filter."
                return {"results": [], "interpreted": interpreted, "unsupported": bool((body.query or "").strip()), "notices": [msg], "limit": lim}
            res = search_engine.apply(_events(s, r), c, lim)
            return {"results": res, "interpreted": interpreted, "unsupported": False, "notices": [], "total_matching_returned": len(res), "limit": lim,
                    "ordering": "start time (no relevance probability is computed)"}

    # ---------- semantic search (optional; the core app never depends on it) ----------
    def get_embedder():
        if os.environ.get("VI_SEMANTIC", "on").lower() == "off":
            raise ApiError(503, "semantic_unavailable", "Semantic search is switched off on this server (VI_SEMANTIC=off). Structured search still works.")
        emb = getattr(app.state, "embedder", None)
        if emb is not None:
            return emb
        try:
            app.state.embedder = semantic.default_embedder()
            return app.state.embedder
        except semantic.EmbedderUnavailable as e:
            raise ApiError(503, "semantic_unavailable", f"{e.message} Structured search still works.")

    def run_attempt_dir(r: m.Run) -> Path:
        return (data_dir() / r.manifest_rel).parent

    def completed_run(s, run_id: str) -> m.Run:
        r = current_run(s, run_id)
        if r.state != "completed" or not r.manifest_rel:
            raise ApiError(409, "invalid_state", "Semantic search needs a completed run.", state=r.state)
        return r

    def ensure_index(s, r: m.Run, embedder):
        got = semantic.load_index(run_attempt_dir(r), r.manifest_sha256)
        if got is not None and got[0]["model"]["name"] == embedder.name and got[0]["model"]["revision"] == embedder.revision and got[0]["model"]["source"] == embedder.source:
            return got
        attempt = run_attempt_dir(r)
        evs = json.loads((attempt / "events.json").read_text())
        obs = [json.loads(x) for x in (attempt / "observations.jsonl").read_text().splitlines()]
        semantic.build_index(attempt, evs, obs, embedder, run_id=r.id, manifest_sha256=r.manifest_sha256)
        return semantic.load_index(attempt, r.manifest_sha256)

    @app.get("/api/runs/{run_id}/semantic")
    def semantic_status(run_id: str):
        with session_scope(F()) as s:
            r = current_run(s, run_id)
            idx = semantic.load_index(run_attempt_dir(r), r.manifest_sha256) if r.state == "completed" and r.manifest_rel else None
            emb = getattr(app.state, "embedder", None)
            off = os.environ.get("VI_SEMANTIC", "on").lower() == "off"
            return {"run_id": run_id, "enabled": not off, "model_loaded": emb is not None, "indexed": idx is not None,
                    "index": None if idx is None else {"items": len(idx[0]["items"]), "built_at": idx[0]["built_at"], "model": idx[0]["model"], "embeddings_sha256": idx[0]["embeddings_sha256"]},
                    "score_meaning": semantic.SCORE_MEANING}

    @app.post("/api/runs/{run_id}/semantic/index")
    def semantic_build(run_id: str):
        with session_scope(F()) as s:
            r = completed_run(s, run_id)
            meta, emb = ensure_index(s, r, get_embedder())
            return {"run_id": run_id, "indexed": True, "items": len(meta["items"]), "model": meta["model"], "built_at": meta["built_at"]}

    @app.post("/api/runs/{run_id}/search/semantic")
    def semantic_search(run_id: str, body: schemas.SemanticSearchBody):
        with session_scope(F()) as s:
            r = completed_run(s, run_id)
            lim = min(body.limit or settings.search.default_limit, settings.search.max_limit)
            c = search_engine.parse_query(body.query, r.zones)
            f = body.filters or {}
            if f.get("type"): c.types = {f["type"]}            # explicit filters are authoritative: they replace what the text implied
            if f.get("class_name"): c.classes = {f["class_name"]}
            if f.get("zone_id"): c.zone_ids = {f["zone_id"]}
            if f.get("review_status"): c.review_status = {f["review_status"]}
            if f.get("after_ms") is not None: c.after_ms = int(f["after_ms"])
            if f.get("before_ms") is not None: c.before_ms = int(f["before_ms"])
            base = {"score_meaning": semantic.SCORE_MEANING, "ordering": "semantic similarity, highest first (a ranking aid, not a confidence)", "limit": lim,
                    "structured_constraints_applied": {"event_types": sorted(c.types), "classes": sorted(c.classes), "zone_ids": sorted(c.zone_ids), "review_status": sorted(c.review_status),
                                                       "after_ms": c.after_ms, "before_ms": c.before_ms}}
            if c.notices:                       # same refusal policy as structured search: intent, identity and blame are not inferred from pixels
                return {**base, "results": [], "unsupported": True, "notices": c.notices + ["No events were ranked for this query."]}
            embedder = get_embedder()
            meta, emb = ensure_index(s, r, embedder)
            all_events = _events(s, r)
            pool = search_engine.apply(all_events, c, 10_000) if not c.is_empty() else all_events
            keys = {e["event_key"] for e in pool}
            qv = embedder.embed_texts([body.query])[0]
            ranked = semantic.rank_events(meta, emb, qv, keys, lim, body.min_similarity)
            by_key = {e["event_key"]: e for e in pool}
            results = []
            for h in ranked:
                e = by_key[h["event_key"]]; b = h["best"]
                results.append({**e, "semantic": {"similarity": h["similarity"], "rank": h["rank"], "best_item": {**b, "frame_url": f"{e['evidence_base']}{b['role']}_original.jpg"},
                                                  "model": meta["model"]["name"], "index_built_at": meta["built_at"]}})
            return {**base, "results": results, "unsupported": False, "notices": [], "candidates_after_structured_filter": len(pool), "model": meta["model"], "source": embedder.source}

    # ---------- optional video-language explanations (advisory; the core app never depends on them) ----------
    def get_explainer():
        if os.environ.get("VI_EXPLAIN", "on").lower() == "off":
            raise ApiError(503, "explainer_unavailable", "Explanations are switched off on this server (VI_EXPLAIN=off). Everything else works.")
        ex = getattr(app.state, "explainer", None)
        if ex is not None:
            return ex
        try:
            app.state.explainer = vlm.default_explainer()
            return app.state.explainer
        except vlm.ExplainerUnavailable as e:
            raise ApiError(503, "explainer_unavailable", f"{e.message} Everything else works.")

    def explanation_out(x: m.Explanation, event: m.Event) -> dict:
        return {"id": x.id, "event_id": x.event_id, "status": x.status, "text": x.text, "flags": x.flags, "model": x.model, "created_at": x.created_at.isoformat() + "Z",
                "prompt_sha256": x.prompt_sha256, "prompt": x.prompt, "disclaimer": vlm.DISCLAIMER,
                "frames": [{**f, "frame_url": f"/api/runs/{event.run_id}/evidence/{event.event_key}/{f['role']}_original.jpg"} for f in x.frames]}

    @app.get("/api/explainer")
    def explainer_status():
        off = os.environ.get("VI_EXPLAIN", "on").lower() == "off"
        ex = getattr(app.state, "explainer", None)
        return {"enabled": not off, "model_loaded": ex is not None, "model": {"name": vlm.SmolVlmExplainer.name, "revision": vlm.SmolVlmExplainer.revision, "license": "apache-2.0"},
                "disclaimer": vlm.DISCLAIMER}

    @app.post("/api/events/{event_id}/explain", status_code=201)
    def explain_event(event_id: str, body: schemas.ExplainBody):
        with session_scope(F()) as s:
            e = get_or_404(s, m.Event, event_id, "event"); r = s.get(m.Run, e.run_id)
            if r.state != "completed" or not r.manifest_rel:
                raise ApiError(409, "invalid_state", "Explanations need a completed run.", state=r.state)
            explainer = get_explainer()
            attempt = (data_dir() / r.manifest_rel).parent
            obs = [json.loads(x) for x in (attempt / "observations.jsonl").read_text().splitlines()]
            ev = {"type": e.type, "class_name": e.class_name, "start_ms": e.start_ms, "end_ms": e.end_ms, "track_ids": e.track_ids, "evidence": e.evidence}
            try:
                res = vlm.explain(attempt, ev, obs, explainer, tuple(body.frames))
            except vlm.ExplainerUnavailable as ex:
                raise ApiError(409, "no_evidence", ex.message)
            x = m.Explanation(event_id=e.id, run_id=e.run_id, status=res["status"], text=res["text"], flags=res["flags"], frames=res["frames"], labels=res["labels"], prompt=res["prompt"],
                              prompt_sha256=res["prompt_sha256"], model=res["model"])
            s.add(x); s.flush()
            return explanation_out(x, e)

    @app.get("/api/events/{event_id}/explanations")
    def list_explanations(event_id: str):
        with session_scope(F()) as s:
            e = get_or_404(s, m.Event, event_id, "event")
            xs = s.scalars(select(m.Explanation).where(m.Explanation.event_id == e.id).order_by(m.Explanation.created_at.desc()))
            return {"event_id": e.id, "explanations": [explanation_out(x, e) for x in xs], "disclaimer": vlm.DISCLAIMER}

    # ---------- review ----------
    @app.put("/api/events/{event_id}/review")
    def review(event_id: str, body: schemas.ReviewPut):
        from ..db.session import with_lock_retry

        def go():
            with session_scope(F()) as s:
                e = get_or_404(s, m.Event, event_id, "event")
                if e.review_version != body.expected_version:
                    raise ApiError(409, "review_conflict", "This event was reviewed by someone else or in another tab. Reload and retry.", current_version=e.review_version,
                                   current_status=e.review_status)
                e.review_version += 1; e.review_status, e.review_note, e.reviewed_at = body.verdict, body.note, datetime.now(timezone.utc).replace(tzinfo=None)
                s.add(m.Review(event_id=e.id, verdict=body.verdict, note=body.note, revision=e.review_version))
                return event_out(e)
        return with_lock_retry(go)

    # ---------- evidence files and report ----------
    @app.get("/api/runs/{run_id}/evidence/{event_key}/{name}")
    def evidence_file(run_id: str, event_key: str, name: str):
        if not EVIDENCE_NAME.match(name) or not re.fullmatch(r"[0-9a-f]{12}", event_key):
            raise ApiError(404, "evidence_not_found", "No such evidence file.")
        with session_scope(F()) as s:
            r = current_run(s, run_id)
            if r.state != "completed" or not r.manifest_rel:
                raise ApiError(404, "evidence_not_found", "The run has no finalized evidence.")
            p = (data_dir() / r.manifest_rel).parent / "evidence" / event_key / name
        if not p.is_file():
            raise ApiError(404, "evidence_not_found", "No such evidence file.")
        return FileResponse(p, media_type="video/mp4" if name.endswith(".mp4") else "image/jpeg", headers={"Accept-Ranges": "bytes"})

    @app.get("/api/runs/{run_id}/report")
    def report(run_id: str, format: str = Query("json", pattern="^(json|markdown|html)$")):
        with session_scope(F()) as s:
            r = current_run(s, run_id)
            if r.state != "completed":
                raise ApiError(409, "invalid_state", "Only completed runs can be exported.", state=r.state)
            v = s.get(m.Video, r.video_id)
            rep = export.build_report(run_out(r), video_out(v), _events(s, r))
        if format == "markdown":
            return PlainTextResponse(export.to_markdown(rep), media_type="text/markdown")
        if format == "html":
            return HTMLResponse(export.to_html(rep))
        return rep

    # ---------- evaluations ----------
    @app.get("/api/evaluations")
    def list_evals():
        return {"evaluations": sorted(p.stem for p in evaluations_dir().glob("*.json"))}

    @app.get("/api/evaluations/{eval_id}")
    def get_eval(eval_id: str):
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", eval_id):
            raise ApiError(404, "evaluation_not_found", "No such evaluation.")
        p = evaluations_dir() / f"{eval_id}.json"
        if not p.is_file():
            raise ApiError(404, "evaluation_not_found", "No such evaluation.")
        return json.loads(p.read_text())

    web_dist = os.environ.get("VI_WEB_DIST")
    if web_dist and Path(web_dist).is_dir():                       # single-origin hosting: the API also serves the built UI
        app.mount("/", StaticFiles(directory=web_dist, html=True), name="web")

    return app


app = create_app()

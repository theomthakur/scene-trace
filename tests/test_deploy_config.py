"""Deployment-readiness behaviour: optional access token, single-origin static hosting, health stays open."""
import pytest
from fastapi.testclient import TestClient


def make(monkeypatch, tmp_path, **env):
    monkeypatch.setenv("VI_DATA_DIR", str(tmp_path / "data"))
    for k in ("VI_API_TOKEN", "VI_WEB_DIST"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    from video_investigator.api.app import create_app
    return TestClient(create_app())


def test_no_token_configured_means_open_loopback_behaviour(monkeypatch, tmp_path):
    with make(monkeypatch, tmp_path) as c:
        assert c.get("/api/videos").status_code == 200
        assert c.get("/api/session").json() == {"required": False, "authenticated": True}


def test_token_protects_api_but_not_health_and_supports_bearer_and_cookie(monkeypatch, tmp_path):
    with make(monkeypatch, tmp_path, VI_API_TOKEN="s3cret-token") as c:
        assert c.get("/api/health").status_code == 200
        r = c.get("/api/videos"); assert r.status_code == 401 and r.json()["error"]["code"] == "auth_required"
        assert c.get("/api/runs").status_code == 401 and c.get("/api/evaluations").status_code == 401
        assert c.get("/api/videos", headers={"Authorization": "Bearer s3cret-token"}).status_code == 200
        assert c.get("/api/videos", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert c.get("/api/session").json() == {"required": True, "authenticated": False}
        bad = c.post("/api/session", json={"token": "nope"}); assert bad.status_code == 401 and bad.json()["error"]["code"] == "auth_failed"
        ok = c.post("/api/session", json={"token": "s3cret-token"}); assert ok.status_code == 200
        assert "httponly" in ok.headers["set-cookie"].lower() and "samesite=lax" in ok.headers["set-cookie"].lower() and "s3cret-token" not in ok.headers["set-cookie"]
        assert c.get("/api/videos").status_code == 200                               # the cookie now authenticates
        assert c.get("/api/session").json()["authenticated"] is True


def test_token_does_not_gate_cors_preflight(monkeypatch, tmp_path):
    with make(monkeypatch, tmp_path, VI_API_TOKEN="t") as c:
        r = c.options("/api/videos", headers={"Origin": "http://127.0.0.1:5173", "Access-Control-Request-Method": "GET"})
        assert r.status_code == 200


def test_single_origin_hosting_serves_the_built_ui_and_keeps_the_api(monkeypatch, tmp_path):
    dist = tmp_path / "dist"; dist.mkdir(); (dist / "index.html").write_text("<!doctype html><title>SceneTrace</title><div id=root></div>")
    with make(monkeypatch, tmp_path, VI_WEB_DIST=str(dist)) as c:
        assert "SceneTrace" in c.get("/").text
        assert c.get("/api/health").json()["ok"] is True and c.get("/api/videos").status_code == 200


def test_cors_allowlist_is_explicit(monkeypatch, tmp_path):
    with make(monkeypatch, tmp_path) as c:
        ok = c.get("/api/health", headers={"Origin": "http://127.0.0.1:5173"}); assert ok.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"
        evil = c.get("/api/health", headers={"Origin": "https://evil.example"}); assert "access-control-allow-origin" not in evil.headers


def test_clean_install_exposes_saved_evaluations_and_prefers_local_reports(monkeypatch, tmp_path):
    with make(monkeypatch, tmp_path) as c:
        ids = c.get("/api/evaluations").json()["evaluations"]
        assert {"development", "frozen-test", "benchmark-reliability", "robustness-sweep"} <= set(ids)
        assert c.get("/api/evaluations/frozen-test").json()["lanes"]["test"]["status"] != "not_evaluated"
        assert c.get("/api/evaluations/test3-results").status_code == 404

        path = tmp_path / "data" / "evaluations" / "development.json"
        path.write_text('{"headline": "Local report"}', encoding="utf-8")
        assert c.get("/api/evaluations/development").json() == {"headline": "Local report"}

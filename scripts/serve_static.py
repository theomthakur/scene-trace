"""Serve a built folder locally with the headers from its vercel.json (including the Content-Security-Policy) and HTTP Range support,
so a static build can be checked in a browser before it is deployed anywhere.   python scripts/serve_static.py web/dist-demo [--port 4173]"""
import argparse, json, re, sys
from pathlib import Path
import uvicorn
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.staticfiles import StaticFiles


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("root"); ap.add_argument("--port", type=int, default=4173)
    a = ap.parse_args(); root = Path(a.root).resolve()
    cfg = json.loads((root / "vercel.json").read_text()) if (root / "vercel.json").exists() else {"headers": []}
    rules = [(re.compile("^" + r["source"].replace("(.*)", ".*") + "$"), {h["key"]: h["value"] for h in r["headers"]}) for r in cfg.get("headers", [])]

    class Headers(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            resp = await call_next(request)
            for pat, hs in rules:
                if pat.match(request.url.path):
                    for k, v in hs.items():
                        resp.headers[k] = v
            return resp
    app = Starlette(); app.add_middleware(Headers); app.mount("/", StaticFiles(directory=root, html=True))
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning"); return 0


if __name__ == "__main__":
    sys.exit(main())

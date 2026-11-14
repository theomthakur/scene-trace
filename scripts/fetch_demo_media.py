"""Download the two CC0 demonstration clips from Wikimedia Commons into var/candidates/ and verify their SHA-1 (as published by Commons).

  python scripts/fetch_demo_media.py

Both files were uploaded by Taurus Media Technik (Xiph.org test media) under CC0. See THIRD-PARTY-NOTICES.md and docs/DATA-CARD.md.
Commons rate-limits automated clients, so requests are spaced out and use a descriptive User-Agent.
"""
from __future__ import annotations
import hashlib, json, sys, time, urllib.request
from pathlib import Path

UA = "video-investigation-prototype/0.1 (local research)"
ROOT = Path(__file__).resolve().parents[1]
CLIPS = [
    {"name": "pedestrian_area.webm", "url": "https://upload.wikimedia.org/wikipedia/commons/a/ae/Video_Codec_Test_pedestrian_area_1080p25.y4m.webm", "sha1": "51e89a672896e45cca17aa46cd223630a6266e26"},
    {"name": "rush_hour.webm", "url": "https://upload.wikimedia.org/wikipedia/commons/", "sha1": "a80ae4df93bc2b24004ca1f850e4b1e3e666a603", "title": "File:Video Codec Test rush hour 1080p25.y4m.webm"},
]


def resolve_url(title: str) -> str:
    import urllib.parse
    u = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({"action": "query", "titles": title, "prop": "imageinfo", "iiprop": "url", "format": "json"})
    d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=30))
    return list(d["query"]["pages"].values())[0]["imageinfo"][0]["url"]


def main() -> int:
    out = ROOT / "var" / "candidates"; out.mkdir(parents=True, exist_ok=True)
    for c in CLIPS:
        dest = out / c["name"]
        if dest.exists() and hashlib.sha1(dest.read_bytes()).hexdigest() == c["sha1"]:
            print(f"ok (already present): {dest.name}"); continue
        url = c["url"] if c["url"].endswith(".webm") else resolve_url(c["title"])
        time.sleep(3)
        data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=120).read()
        got = hashlib.sha1(data).hexdigest()
        if got != c["sha1"]:
            print(f"HASH MISMATCH for {dest.name}: expected {c['sha1']}, got {got}. Not saved.", file=sys.stderr); return 1
        dest.write_bytes(data); print(f"downloaded and verified: {dest.name} ({len(data) // 1024} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

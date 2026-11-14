"""Download chosen harvest candidates from Commons into var/candidates/new/ and verify the SHA-1 Commons publishes.  python scripts/fetch_candidates.py 61 71 83
Index numbers refer to var/candidates/harvest.json (written by harvest_commons_candidates.py). Each download also stores its licence and author."""
import hashlib, json, re, sys, time, urllib.parse, urllib.request
from pathlib import Path
UA = "video-investigation-prototype/0.1 (local research)"
ROOT = Path(__file__).resolve().parents[1]; OUT = ROOT / "var" / "candidates" / "new"; OUT.mkdir(parents=True, exist_ok=True)


def meta(title):
    u = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({"action": "query", "titles": title, "prop": "imageinfo", "iiprop": "url|size|sha1|extmetadata", "format": "json"})
    for k in range(5):
        try:
            return list(json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=30))["query"]["pages"].values())[0]["imageinfo"][0]
        except Exception:
            time.sleep(15 * (k + 1))
    raise SystemExit("could not read metadata for " + title)


def main(ids):
    items = json.loads((ROOT / "var" / "candidates" / "harvest.json").read_text())
    for i in map(int, ids):
        it = items[i]; ii = meta(it["title"]); m = ii["extmetadata"]; slug = re.sub(r"[^A-Za-z0-9]+", "_", it["title"][5:])[:60].strip("_"); ext = Path(it["title"]).suffix
        dest = OUT / f"{i:03d}_{slug}{ext}"
        if not dest.exists():
            data = None
            for k in range(6):                                           # Commons rate-limits: back off and retry
                try:
                    time.sleep(4 + 20 * k); data = urllib.request.urlopen(urllib.request.Request(ii["url"], headers={"User-Agent": UA}), timeout=180).read(); break
                except urllib.error.HTTPError as e:
                    if e.code != 429:
                        raise
            if data is None:
                print(f"gave up on {i} (rate limited)"); continue
            if hashlib.sha1(data).hexdigest() != ii["sha1"]:
                print(f"HASH MISMATCH {i}"); continue
            dest.write_bytes(data)
        rec = {"index": i, "title": it["title"], "file": dest.name, "sha1": ii["sha1"], "license": (m.get("LicenseShortName", {}) or {}).get("value"), "license_url": (m.get("LicenseUrl", {}) or {}).get("value"),
               "author": re.sub("<[^>]+>", "", (m.get("Artist", {}) or {}).get("value", ""))[:120], "source_page": "https://commons.wikimedia.org/wiki/" + it["title"].replace(" ", "_"), "size": ii["size"]}
        (OUT / f"{dest.stem}.json").write_text(json.dumps(rec, indent=1)); print("ok", i, dest.name, rec["license"])


if __name__ == "__main__":
    main(sys.argv[1:])

"""Search Wikimedia Commons for candidate benchmark clips and fetch poster frames for visual review. Metadata only: nothing is downloaded as a benchmark clip here.
Filters: licence CC0 / public domain / CC BY / CC BY-SA, 6 to 90 s, webm or ogv, and no title words that suggest violence, crime, disasters or private individuals.
   python scripts/harvest_commons_candidates.py        writes var/candidates/harvest.json and poster images under var/candidates/posters/"""
import json, re, sys, time, urllib.parse, urllib.request
from pathlib import Path
UA = "video-investigation-prototype/0.1 (local research)"
ROOT = Path(__file__).resolve().parents[1]; OUT = ROOT / "var" / "candidates"; (OUT / "posters").mkdir(parents=True, exist_ok=True)
QUERIES = ["timelapse street pedestrians", "static camera street", "traffic intersection", "railway station platform", "bus station", "market square", "shopping street", "cycle path bicycles",
           "tram stop", "crossing pedestrians", "airport arrivals", "harbour boats", "car park", "roundabout traffic", "escalator", "pedestrian bridge", "zebra crossing", "queue ticket",
           "plaza fountain people", "highway traffic"]
BAD = re.compile(r"police|crash|shoot|attack|riot|protest|fire|kill|arrest|collision|explosion|war|military|bomb|fight|stabb|assault|injur|death|dead|murder|victim|raid|strike|hostage|terror|refugee|migrant|funeral|hospital|child|baby|school|girl|boy|nude|beach", re.I)
OK_LICENSE = re.compile(r"CC0|Public domain|CC BY( |-)?(SA)? ?[0-9.]*", re.I)


def api(params):
    u = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({**params, "format": "json"})
    for k in range(5):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=30))
        except Exception:
            time.sleep(20 * (k + 1))
    return {}


def main():
    found = {}
    for q in QUERIES:
        d = api({"action": "query", "generator": "search", "gsrsearch": q + " filetype:video", "gsrnamespace": 6, "gsrlimit": 15, "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 480})
        for p in (d.get("query", {}).get("pages", {}) or {}).values():
            ii = p["imageinfo"][0]; m = ii.get("extmetadata", {}); lic = (m.get("LicenseShortName", {}) or {}).get("value", ""); dur = ii.get("duration") or 0
            if BAD.search(p["title"]) or not OK_LICENSE.search(lic) or "NC" in lic or "ND" in lic or not (6 <= dur <= 90) or ii["size"] > 120e6:
                continue
            found[p["title"]] = {"title": p["title"], "license": lic, "duration_s": round(dur, 1), "size_mb": round(ii["size"] / 1e6, 1), "mime": ii["mime"], "thumb": ii.get("thumburl"), "url": ii["url"],
                                 "artist": re.sub("<[^>]+>", "", (m.get("Artist", {}) or {}).get("value", ""))[:80], "query": q}
        time.sleep(12)
    items = sorted(found.values(), key=lambda x: x["title"]); (OUT / "harvest.json").write_text(json.dumps(items, indent=1))
    for i, it in enumerate(items):
        if it["thumb"]:
            try:
                (OUT / "posters" / f"{i:03d}.jpg").write_bytes(urllib.request.urlopen(urllib.request.Request(it["thumb"], headers={"User-Agent": UA}), timeout=30).read()); time.sleep(1.2)
            except Exception as e:
                print("poster failed", i, e)
        print(i, it["title"][:70], "|", it["license"], "|", it["duration_s"], "s |", it["size_mb"], "MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())

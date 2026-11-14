"""The TypeScript interfaces in web/src/api.ts must list fields the real API actually returns (so the UI and backend cannot drift apart silently)."""
import re
from pathlib import Path
from helpers import FixtureDetector, person_in_zone_script
from test_api_flow import run_with_fixture, upload, make_run

TS = (Path(__file__).resolve().parent.parent / "web" / "src" / "api.ts").read_text()


def fields(name: str) -> set[str]:
    body = re.search(rf"export interface {name} \{{(.*?)\n\}}", TS, re.S).group(1)
    while re.search(r"\{[^{}]*\}", body):            # drop nested object types: only top-level fields are compared
        body = re.sub(r"\{[^{}]*\}", "", body)
    return set(re.findall(r"(?:^|[;\n{]|\s)([a-z0-9_]+)\??:", body))


def test_ts_interfaces_match_real_responses(client, tmp_path):
    v = upload(client, tmp_path); run = make_run(client, v["id"]); run_with_fixture(client, run["id"])
    vid = client.get(f"/api/videos/{v['id']}").json(); r = client.get(f"/api/runs/{run['id']}").json(); e = client.get(f"/api/runs/{run['id']}/events").json()["events"][0]
    for iface, payload in (("VideoT", vid), ("RunT", r), ("EventT", e)):
        declared = fields(iface)
        missing = declared - set(payload) - {"zone_version"} if iface != "VideoT" else declared - set(payload)
        assert not missing, f"{iface} declares fields the API does not return: {missing}"
        extra = set(payload) - declared
        assert not extra, f"{iface} is missing fields the API returns: {extra}"

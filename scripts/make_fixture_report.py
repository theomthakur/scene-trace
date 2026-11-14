"""Write fixtures/reports/fixture-report.json: the deterministic fixture-lane report (no detector, no variable fields).
A fresh checkout must reproduce it byte for byte; tests/test_benchmark.py checks that."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from video_investigator.config import load_settings
from video_investigator.evaluation.benchmark import fixture_lane


def render() -> str:
    return json.dumps({"lane": fixture_lane(load_settings()), "config_hash": load_settings().config_hash()}, indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    out = Path(__file__).resolve().parents[1] / "fixtures" / "reports" / "fixture-report.json"
    out.parent.mkdir(parents=True, exist_ok=True); out.write_text(render()); print("wrote", out)

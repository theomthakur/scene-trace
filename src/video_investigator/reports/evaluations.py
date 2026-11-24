"""Evaluation reports shared by the live API and the static demo."""
import json
import re
from pathlib import Path

from ..config import REPO
from ..paths import evaluations_dir


BUILT_IN_REPORTS = {
    "development": "evaluation-development",
    "frozen-test": "evaluation-frozen-test",
    **{name: name for name in (
        "semantic-eval", "explanation-eval", "crosscam-eval", "finetune-development",
        "finetune-test", "benchmark-expansion", "benchmark-reliability", "robustness-sweep",
    )},
}


def report_paths() -> dict[str, Path]:
    evidence = REPO / "docs" / "evidence"
    paths = {report_id: evidence / f"{name}.json" for report_id, name in BUILT_IN_REPORTS.items()}
    paths = {report_id: path for report_id, path in paths.items() if path.is_file()}
    paths.update({
        path.stem: path for path in evaluations_dir().glob("*.json")
        if path.is_file() and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", path.stem)
    })
    return paths


def read_report(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))

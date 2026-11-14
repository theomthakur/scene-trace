"""Local data layout. All user data lives under VI_DATA_DIR (default: ./var), which is git-ignored. The API never exposes these paths."""
from __future__ import annotations
import os
from pathlib import Path
from .config import REPO


def data_dir() -> Path:
    d = Path(os.environ.get("VI_DATA_DIR", REPO / "var")).resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path() -> Path:
    return data_dir() / "app.db"


def videos_dir() -> Path:
    p = data_dir() / "videos"; p.mkdir(parents=True, exist_ok=True); return p


def runs_dir() -> Path:
    p = data_dir() / "runs"; p.mkdir(parents=True, exist_ok=True); return p


def uploads_tmp() -> Path:
    p = data_dir() / "uploads-tmp"; p.mkdir(parents=True, exist_ok=True); return p


def evaluations_dir() -> Path:
    p = data_dir() / "evaluations"; p.mkdir(parents=True, exist_ok=True); return p

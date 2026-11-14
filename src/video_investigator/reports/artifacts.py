"""Attempt directories and atomic manifest publication.

A worker writes every file of an attempt into var/runs/<run_id>/attempt-<n>/, fsyncs them, then publishes manifest.json with an
atomic rename. Readers treat an attempt without a manifest as incomplete. A completed attempt is never modified or overwritten.
"""
from __future__ import annotations
import hashlib, json, os
from pathlib import Path


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def write_file(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(data); f.flush(); os.fsync(f.fileno())
    return sha256_bytes(data)


def write_json(path: Path, obj) -> str:
    return write_file(path, (json.dumps(obj, indent=2, sort_keys=True) + "\n").encode())


def write_jsonl(path: Path, rows) -> str:
    return write_file(path, ("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows)).encode())


def next_attempt_dir(run_dir: Path) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    n = 1 + max([int(p.name.split("-")[1]) for p in run_dir.glob("attempt-*") if p.name.split("-")[1].isdigit()] or [0])
    d = run_dir / f"attempt-{n}"
    d.mkdir()
    return d


def publish_manifest(attempt_dir: Path, files: dict[str, str], extra: dict | None = None) -> Path:
    """files maps relative path -> sha256. Verifies each file exists with the stated hash before announcing completion."""
    for rel, digest in files.items():
        p = attempt_dir / rel
        if not p.is_file() or sha256_bytes(p.read_bytes()) != digest:
            raise RuntimeError(f"artifact {rel} is missing or changed; refusing to publish the manifest")
    manifest = {"files": files, **(extra or {})}
    tmp = attempt_dir / "manifest.json.tmp"
    write_file(tmp, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
    final = attempt_dir / "manifest.json"
    os.replace(tmp, final)
    return final


def is_complete(attempt_dir: Path) -> bool:
    return (attempt_dir / "manifest.json").is_file()


def load_manifest(attempt_dir: Path) -> dict:
    return json.loads((attempt_dir / "manifest.json").read_text())

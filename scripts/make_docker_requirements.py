"""Derive requirements.docker.txt (Linux CPU image) from requirements.lock. Run after the lock changes:  python scripts/make_docker_requirements.py
Mac-only or editable lines are dropped; torch and torchvision keep their versions and are installed from the CPU wheel index by the Dockerfile."""
from pathlib import Path
root = Path(__file__).resolve().parents[1]
out = ["# Generated from requirements.lock by scripts/make_docker_requirements.py for the Linux CPU image. Do not edit by hand."]
for line in (root / "requirements.lock").read_text().splitlines():
    s = line.strip()
    if not s or s.startswith("#") or s.startswith("-e") or s.lower().startswith(("pyobjc", "appnope")):
        continue
    out.append(s)
(root / "requirements.docker.txt").write_text("\n".join(out) + "\n"); print("wrote requirements.docker.txt with", len(out) - 1, "pins")

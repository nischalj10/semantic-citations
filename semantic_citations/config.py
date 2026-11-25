"""Paths and API keys. Keys come from the environment or a git-ignored .env file."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache"  # raw API responses and full text; never committed
DATA = ROOT / "data"  # contexts, predictions, gold labels, reports


def load_env(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def require(name: str) -> str:
    load_env()
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is not set. Put it in .env (see .env.example) or export it.")
    return value

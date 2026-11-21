"""Load config.yaml from the project root, and resolve data directories.

Code and config live in the project; the checked-in data (docs/, index/, the figure records) lives
under data_root(): the project itself, or another copy of that layout when PHARMASSIST_DATA_ROOT is set.
"""

import os
from functools import cache
from pathlib import Path

import yaml

# src/pharmassist/config.py -> project root is three levels up
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_KEYS = ("docs", "index")   # `paths` entries that are data, not code or outputs


@cache
def load_config(path: Path = PROJECT_ROOT / "config.yaml") -> dict:
    return yaml.safe_load(path.read_text())


def data_root() -> Path:
    return Path(os.environ.get("PHARMASSIST_DATA_ROOT") or PROJECT_ROOT)


def project_path(key: str) -> Path:
    """Resolve a directory from config.yaml's `paths` section (data directories under data_root())."""
    return (data_root() if key in DATA_KEYS else PROJECT_ROOT) / load_config()["paths"][key]


def figure_records_path() -> Path:
    """The indexed figures' vision records (scripts/extract_figures.py)."""
    return data_root() / "storage" / "figures" / "records.json"

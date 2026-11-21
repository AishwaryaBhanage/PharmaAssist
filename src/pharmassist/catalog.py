"""Read docs/catalog.yaml, the single list of corpus documents."""

from pathlib import Path

import yaml

from pharmassist.config import project_path


def docs_dir() -> Path:
    return project_path("docs")


def load_catalog() -> list[dict]:
    return yaml.safe_load((docs_dir() / "catalog.yaml").read_text())["documents"]

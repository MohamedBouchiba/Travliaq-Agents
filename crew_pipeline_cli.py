"""Wrapper CLI cross-platform to run Crew pipeline regardless of working directory."""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_project_root_on_path() -> None:
    project_root = Path(__file__).resolve().parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))


_ensure_project_root_on_path()

from app.crew_pipeline.__main__ import main  # noqa: E402  (import après ajustement du PATH)


if __name__ == "__main__":
    sys.exit(main())

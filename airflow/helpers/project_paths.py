from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(os.getenv("PROJECT_ROOT", "/opt/project/dados-desestruturados"))


def project_path(*parts: str) -> str:
    return str(PROJECT_ROOT.joinpath(*parts))

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(os.getenv("PROJECT_ROOT", "/opt/project/dados-desestruturados"))


class ProjectPaths:
    """Resolve caminhos do projeto de forma consistente dentro e fora do container."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or PROJECT_ROOT

    def path(self, *parts: str) -> str:
        """Concatena partes relativas ao root configurado do projeto."""
        return str(self.root.joinpath(*parts))


PROJECT_PATHS = ProjectPaths()

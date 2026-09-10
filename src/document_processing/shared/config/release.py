"""Rotulo de versao do projeto usado para comparar execucoes no Langfuse.

Toda execucao observada carrega um `release`. Comparar duas versoes do projeto
sobre os mesmos documentos e o que transforma metrica em criterio de decisao:
sem rotulo estavel, uma media agregada mistura codigo velho e novo e nao diz se
uma mudanca melhorou ou piorou o fluxo.

Formatos:

- producao:     `prod-<tag ou versao do pyproject>`
- homologacao:  `stg-<branch>-<sha curto>`
- desenvolvimento: `dev-<branch>-<sha curto>[-dirty]`

`ATLAS_RELEASE` sempre vence, para permitir rotular um experimento
manualmente (por exemplo `exp-prompt-selecao-v2`).
"""

from __future__ import annotations

import os
import re
import subprocess
from functools import lru_cache
from pathlib import Path

MAX_RELEASE_LENGTH = 64


def _run_git(*args: str, cwd: Path | None = None) -> str:
    """Executa um comando git curto e tolera qualquer falha."""
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _slugify(value: str) -> str:
    """Normaliza branches e tags para um rotulo estavel e curto."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return slug[:32]


def _project_version(root: Path) -> str:
    """Le a versao declarada no pyproject, quando existir."""
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return ""
    try:
        content = pyproject.read_text(encoding="utf-8")
    except OSError:
        return ""
    match = re.search(r'^version\s*=\s*"([^"]+)"', content, flags=re.MULTILINE)
    return match.group(1) if match else ""


@lru_cache(maxsize=8)
def resolve_release(environment: str = "development", root: str | None = None) -> str:
    """Monta o rotulo de versao do projeto para o ambiente informado."""
    explicit = os.getenv("ATLAS_RELEASE", "").strip()
    if explicit:
        return _slugify(explicit)[:MAX_RELEASE_LENGTH]

    base = Path(root) if root else Path(__file__).resolve().parents[4]
    branch = _slugify(_run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=base) or "sem-branch")
    sha = _run_git("rev-parse", "--short", "HEAD", cwd=base) or "sem-sha"
    dirty = bool(_run_git("status", "--porcelain", cwd=base))

    normalized = (environment or "development").strip().lower()
    if normalized in {"production", "producao", "prod"}:
        tag = _run_git("describe", "--tags", "--abbrev=0", cwd=base)
        version = _slugify(tag or _project_version(base) or sha)
        return f"prod-{version}"[:MAX_RELEASE_LENGTH]

    prefix = "stg" if normalized in {"staging", "homologacao", "stg"} else "dev"
    suffix = "-dirty" if dirty else ""
    return f"{prefix}-{branch}-{sha}{suffix}"[:MAX_RELEASE_LENGTH]


def describe_release(environment: str = "development") -> dict[str, str]:
    """Descreve a versao atual, util para logs e para o cabecalho das DAGs."""
    base = Path(__file__).resolve().parents[4]
    return {
        "release": resolve_release(environment),
        "environment": environment,
        "branch": _run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=base),
        "commit": _run_git("rev-parse", "HEAD", cwd=base),
        "arvore_suja": "sim" if _run_git("status", "--porcelain", cwd=base) else "nao",
    }

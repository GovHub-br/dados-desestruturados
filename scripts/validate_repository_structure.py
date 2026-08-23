"""Valida referências locais essenciais de documentação e skills versionadas."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
BACKTICK_PATH = re.compile(r"`((?:docs|specs|src|airflow|skills)/[^`\s]+)`")


def referenced_paths(path: Path) -> set[str]:
    content = path.read_text(encoding="utf-8")
    links = {match.group(1).split("#", maxsplit=1)[0] for match in MARKDOWN_LINK.finditer(content)}
    inline = {match.group(1) for match in BACKTICK_PATH.finditer(content)}
    return {value for value in links | inline if value and not value.startswith(("http://", "https://"))}


def main() -> int:
    errors: list[str] = []
    for skill in sorted((ROOT / "skills").glob("*/SKILL.md")):
        for reference in referenced_paths(skill):
            if not (ROOT / reference).exists():
                errors.append(f"{skill.relative_to(ROOT)} referencia caminho inexistente: {reference}")

    for required in (ROOT / "docs" / "README.md", ROOT / "specs" / "README.md"):
        if not required.exists():
            errors.append(f"Documento canônico ausente: {required.relative_to(ROOT)}")

    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("Estrutura de documentação e skills validada.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

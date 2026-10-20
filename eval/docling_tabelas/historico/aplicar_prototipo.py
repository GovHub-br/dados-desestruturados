"""Copia docling_pipeline para o scratchpad e aplica o PROTOTIPO da correcao (A + B1 + B2).
Nao altera o repositorio. Cada substituicao exige exatamente 1 ocorrencia (falha ruidosa).
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

# Codigo-base (c017c16, antes das correcoes): git archive c017c16 docling_pipeline | tar -x -C <dir>
SRC = Path(os.environ["CODIGO_BASE"]) / "docling_pipeline"
parts = sys.argv[1] if len(sys.argv) > 1 else "A,B1,B2"
DST_ROOT = Path(tempfile.gettempdir()) / ("docling_tabelas_proto" if parts == "A,B1,B2" else "docling_tabelas_proto_" + parts.replace(",", "_"))
DST = DST_ROOT / "docling_pipeline"
group = ""
if DST_ROOT.exists():
    shutil.rmtree(DST_ROOT)
shutil.copytree(SRC, DST, ignore=shutil.ignore_patterns("__pycache__"))


def sub(path: Path, old: str, new: str) -> None:
    if group not in parts.split(","):
        return
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"{path.name}: trecho esperado apareceu {text.count(old)}x:\n{old[:80]}"
    path.write_text(text.replace(old, new), encoding="utf-8")


# ---------------- A) common.py: titulo mais proximo ACIMA da tabela, nao o mais largo ----------------
common = DST / "extractors" / "common.py"
group = "A"

sub(
    common,
    """    # Better candidates have:
    # 1. more horizontal overlap
    # 2. smaller vertical distance
    # 3. smaller horizontal center distance
    return (-horizontal_overlap, vertical_distance, horizontal_distance)
""",
    """    # Better candidates have:
    # 1. smaller vertical distance (the closest heading above the anchor)
    # 2. more horizontal overlap
    # 3. smaller horizontal center distance
    # A largura do titulo nao pode ser o criterio principal: o H1 da pagina cobre toda a largura e
    # sempre "ganharia" de um subtitulo estreito colado na tabela (ex.: "4 - Construcao").
    return (vertical_distance, -horizontal_overlap, horizontal_distance)


def _section_is_above(anchor: BoundingBox, section_bbox: BoundingBox) -> bool:
    anchor_top = anchor.top if anchor.top is not None else anchor.bottom
    section_top = section_bbox.top if section_bbox.top is not None else section_bbox.bottom
    if anchor_top is None or section_top is None:
        return False
    return section_top >= anchor_top
""",
)

sub(
    common,
    """        with_bbox = [s for s in candidates if s.bbox is not None]
        if with_bbox:
            return min(with_bbox, key=lambda section: _section_match_score(anchor_bbox, section.bbox))  # type: ignore[arg-type]
""",
    """        with_bbox = [s for s in candidates if s.bbox is not None]
        if with_bbox:
            above = [
                s
                for s in with_bbox
                if _section_is_above(anchor_bbox, s.bbox)  # type: ignore[arg-type]
                and _bbox_horizontal_overlap(anchor_bbox, s.bbox) > 0.0  # type: ignore[arg-type]
            ]
            pool = above or with_bbox
            return min(pool, key=lambda section: _section_match_score(anchor_bbox, section.bbox))  # type: ignore[arg-type]
""",
)

# ---------------- B1) tables.py: rotulo com palavra + ano nao e "dado" ----------------
tables = DST / "extractors" / "tables.py"
group = "B1"

sub(
    tables,
    '''_LONG_NUMERIC_RE = re.compile(r"^\\d{4,}$")
''',
    '''_LONG_NUMERIC_RE = re.compile(r"^\\d{4,}$")
_WORD_RE = re.compile(r"[^\\W\\d_]{3,}")
''',
)

sub(
    tables,
    """def _value_is_data_like(value: str) -> bool:
    compact = re.sub(r"\\s+", "", value)
    digits_only = re.sub(r"\\D", "", compact)
    return bool(
        value
        and (
            _UUIDISH_RE.search(compact)
            or (digits_only and _LONG_NUMERIC_RE.fullmatch(digits_only))
            or compact.isdigit()
        )
    )
""",
    """def _value_is_data_like(value: str) -> bool:
    compact = re.sub(r"\\s+", "", value)
    if not value:
        return False
    if _UUIDISH_RE.search(compact):
        return True
    if _WORD_RE.search(compact):
        # Rotulo com palavra ("Posicao: JUN/2026.R$ Milhoes") nao e dado, mesmo citando um ano.
        return False
    digits_only = re.sub(r"\\D", "", compact)
    return bool((digits_only and _LONG_NUMERIC_RE.fullmatch(digits_only)) or compact.isdigit())
""",
)

# ---------------- B2) tables.py: titulo entre dois itens da mesma pagina = tabelas distintas ----------------
group = "B2"
sub(
    tables,
    """def _merge_pair(
    left: ExtractedTableCandidate,
    right: ExtractedTableCandidate,
) -> Optional[ExtractedTableCandidate]:
    if not _page_gap_ok(left, right) or not _bboxes_align(left.bbox, right.bbox):
        return None
""",
    """def _section_between(
    left: ExtractedTableCandidate,
    right: ExtractedTableCandidate,
    sections: Optional[list[SectionRecord]],
) -> bool:
    \"\"\"True quando ha um titulo entre dois fragmentos da MESMA pagina: sao tabelas, nao continuacao.

    Continuacao de pagina para pagina nao e afetada: la o titulo/marcador da pagina nova sempre
    existe entre os fragmentos, e isso nao indica tabela nova.
    \"\"\"
    if not sections or right.page_number is None:
        return False
    left_page = left.end_page_number if left.end_page_number is not None else left.page_number
    if left_page != right.page_number:
        return False
    left_last = left.source_order_indices[-1]
    right_first = right.source_order_indices[0]
    return any(
        s.page_number == right.page_number and left_last < s.order_index < right_first for s in sections
    )


def _merge_pair(
    left: ExtractedTableCandidate,
    right: ExtractedTableCandidate,
    sections: Optional[list[SectionRecord]] = None,
) -> Optional[ExtractedTableCandidate]:
    if (
        not _page_gap_ok(left, right)
        or not _bboxes_align(left.bbox, right.bbox)
        or _section_between(left, right, sections)
    ):
        return None
""",
)

sub(
    tables,
    """def _merge_table_fragments(candidates: list[ExtractedTableCandidate]) -> list[ExtractedTableCandidate]:""",
    """def _merge_table_fragments(
    candidates: list[ExtractedTableCandidate],
    sections: Optional[list[SectionRecord]] = None,
) -> list[ExtractedTableCandidate]:""",
)
sub(tables, "candidate = _merge_pair(current, candidates[next_index])", "candidate = _merge_pair(current, candidates[next_index], sections)")
sub(tables, "candidates = _merge_table_fragments(candidates)\n\n    return", "candidates = _merge_table_fragments(candidates, sections)\n\n    return")

print("prototipo aplicado em:", DST)

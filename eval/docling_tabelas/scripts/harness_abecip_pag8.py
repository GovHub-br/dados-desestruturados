"""Harness: roda as funcoes REAIS de associacao secao<->tabela, propagacao de cabecalho e
merge, contra os dados REAIS da extracao da ABECIP (pag. 6-8), sem precisar do Docling.

Uso: harness.py <raiz que contem docling_pipeline/> <rotulo>

Entradas reconstruidas a partir dos artefatos:
  - secoes: sections/sections.jsonl (geometria e order_index reais)
  - tabelas das pag. 6-7: tables/table001-004 (cada uma e um unico item do Docling)
  - tabelas da pag. 8: table005 desfeita nos 3 itens de origem (97, 99, 101),
    cada um com o cabecalho original como colunas (era a 1a linha do bloco)
"""
from __future__ import annotations

import importlib
import inspect
import json
import sys
import types
from pathlib import Path

import pandas as pd

root = Path(sys.argv[1])
label = sys.argv[2]
REPO = Path(__file__).resolve().parents[3]
EXT = REPO / "resultados_construtoras/abecip/extraction"

pkg = types.ModuleType("docling_pipeline")
pkg.__path__ = [str(root / "docling_pipeline")]
sys.modules["docling_pipeline"] = pkg
ext = types.ModuleType("docling_pipeline.extractors")
ext.__path__ = [str(root / "docling_pipeline" / "extractors")]
sys.modules["docling_pipeline.extractors"] = ext

from docling_pipeline.helpers import slugify  # noqa: E402
from docling_pipeline.models import BoundingBox, SectionRecord  # noqa: E402

T = importlib.import_module("docling_pipeline.extractors.tables")
C = importlib.import_module("docling_pipeline.extractors.common")
CLOSEST_ABOVE = {"closest_above": True} if "closest_above" in inspect.signature(C.nearest_section).parameters else {}

sections = [SectionRecord(**json.loads(l)) for l in (EXT / "sections/sections.jsonl").read_text().splitlines()]
meta = json.loads((EXT / "tables/metadata.json").read_text())["items"]


def load_table(n: int):
    return json.loads((EXT / f"tables/table{n:03d}.json").read_text())


items = []
for n, idx in ((1, 73), (2, 82), (3, 86), (4, 89)):
    t = load_table(n)
    items.append(
        dict(idx=idx, page=meta[n - 1]["page_number"], bbox=BoundingBox(**meta[n - 1]["bbox"]),
             df=pd.DataFrame(t["rows"], columns=t["schema"]))
    )

t5 = load_table(5)["rows"]
b5 = meta[4]["bbox"]
# 3 blocos da tabela fundida: [0:11], [11:23], [23:36]; 1a linha de cada bloco = cabecalho original
by_title = {s.title_raw: s for s in sections if s.page_number == 8}
tops = {
    97: b5["top"],  # o topo da caixa fundida e o topo do 1o item
    99: by_title["5 - Aquisicao"].bbox.bottom + 0.63,   # mesmo desvio observado no 1o item (702.85-702.22)
    101: by_title["6 - Aquisicao e Construcao"].bbox.bottom + 0.63,
}
for idx, (a, b) in zip((97, 99, 101), ((0, 11), (11, 23), (23, 36))):
    block = [list(r) for r in t5[a:b]]
    import os
    if os.environ.get("IGUALAR_OCR"):  # simula um mes em que o OCR leu os 3 cabecalhos de forma identica
        block[0] = [c.replace("RS Milhoes", "R$ Milhoes").replace("Posicao:ano2026", "Posicao: ano 2026") for c in block[0]]
    items.append(
        dict(idx=idx, page=8,
             bbox=BoundingBox(page_number=8, left=b5["left"], right=b5["right"], top=tops[idx],
                              bottom=tops[idx] - 160.0, coord_origin=b5["coord_origin"]),
             df=pd.DataFrame(block[1:], columns=block[0]))
    )

# --- replica o laco de extract_tables(), trocando so a leitura do TableItem ---
candidates = []
for it in items:
    section = C.nearest_section(sections, page_number=it["page"], anchor_bbox=it["bbox"], order_index=it["idx"], **CLOSEST_ABOVE)
    title_raw = section.title_raw if section else None
    candidates.append(
        T.ExtractedTableCandidate(
            source_order_indices=(it["idx"],), page_number=it["page"], end_page_number=it["page"],
            section=section, bbox=it["bbox"], df=it["df"], title_raw=title_raw,
            title_canonical=slugify(title_raw) if title_raw else None,
        )
    )

candidates = T._propagate_headers(candidates)
if "sections" in inspect.signature(T._merge_table_fragments).parameters:
    candidates = T._merge_table_fragments(candidates, sections)
else:
    candidates = T._merge_table_fragments(candidates)

print(f"===== {label}: {len(candidates)} tabelas resultantes =====")
result = []
for c in candidates:
    cols = [str(x) for x in c.df.columns]
    first = str(c.df.iloc[0, 0]) if len(c.df) else "-"
    last = str(c.df.iloc[-1, 0]) if len(c.df) else "-"
    result.append(dict(src=c.source_order_indices, page=c.page_number, section=c.title_raw, rows=len(c.df), cols=cols))
    print(f"  itens {str(c.source_order_indices):14s} pag {c.page_number} | titulo: {str(c.title_raw)[:52]:52s} | linhas={len(c.df):2d} | 1a col: {first!r}..{last!r}")
    print(f"       cabecalho: {cols[:3]}...")

# comparacao com o que foi gravado de fato
rec = [(m["page_number"], m["section_title"], len(m["schema"])) for m in meta]
rec_rows = [load_table(i)["rows"].__len__() for i in range(1, 6)]
now = [(r["page"], r["section"], len(r["cols"])) for r in result]
now_rows = [r["rows"] for r in result]
print()
print("reproduz EXATAMENTE a saida gravada (secao/colunas/linhas)?",
      "SIM" if (rec == now and rec_rows == now_rows) else "NAO")

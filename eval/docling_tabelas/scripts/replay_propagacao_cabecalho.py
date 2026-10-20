"""Reexecuta _propagate_headers sobre a SEQUENCIA de tabelas gravada de cada extracao.

Ressalva: as tabelas gravadas ja passaram por propagacao/fusao, entao este replay nao reconstroi
o estado original; ele mede onde a regra NOVA agiria de forma diferente da ANTIGA sobre a mesma
sequencia (ex.: copiar um cabecalho 'lembrado' para uma tabela com colunas genericas).
"""
from __future__ import annotations

import glob
import importlib
import json
import sys
import types
from pathlib import Path

import pandas as pd

root, out = Path(sys.argv[1]), Path(sys.argv[2])
REPO = Path(__file__).resolve().parents[3]
BASE = REPO
pkg = types.ModuleType("docling_pipeline")
pkg.__path__ = [str(root / "docling_pipeline")]
sys.modules["docling_pipeline"] = pkg
ext = types.ModuleType("docling_pipeline.extractors")
ext.__path__ = [str(root / "docling_pipeline" / "extractors")]
sys.modules["docling_pipeline.extractors"] = ext
from docling_pipeline.models import BoundingBox  # noqa: E402

T = importlib.import_module("docling_pipeline.extractors.tables")

dirs = sorted(glob.glob(str(BASE / "airflow/state/resolution_inputs/*/extraction")))
dirs += [str(BASE / "extraction_cury")]
res = []
for d in dirs:
    d = Path(d)
    mp = d / "tables/metadata.json"
    if not mp.exists():
        continue
    nome = d.parent.name.replace("dag_detecta_pdf_e_extrai__", "") if d.parent.name.startswith("dag_") else d.name
    cands, rec = [], []
    for i, it in enumerate(json.loads(mp.read_text())["items"]):
        t = json.loads((d / it["path"]).read_text())
        md = json.loads((d / it["metadata_path"]).read_text())
        df = pd.DataFrame(t["rows"], columns=t["schema"])
        cands.append(
            T.ExtractedTableCandidate(
                source_order_indices=(i,), page_number=it["page_number"], end_page_number=it["page_number"],
                section=None, bbox=BoundingBox(**md["bbox"]) if md.get("bbox") else None, df=df,
                title_raw=md.get("title_raw"), title_canonical=md.get("title_canonical"),
            )
        )
        rec.append(list(t["schema"]))
    new = T._propagate_headers(cands)
    res.append(dict(ext=nome, recorded=rec, replay=[[str(c) for c in c2.df.columns] for c2 in new],
                    pages=[c.page_number for c in cands], rows=[len(c.df) for c in cands],
                    first=[str(c.df.iloc[0, 0]) if len(c.df) else "" for c in cands]))
out.write_text(json.dumps(res, ensure_ascii=False))
print(root.name, "ok", len(res), "extracoes")

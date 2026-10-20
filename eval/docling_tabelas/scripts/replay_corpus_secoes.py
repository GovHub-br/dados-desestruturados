"""Reexecuta, em TODAS as extracoes do repositorio, a associacao tabela<->secao e a regra
de 'cabecalho parece dado', com o codigo de <raiz>. Escreve JSON em <saida>.

Para cada tabela de item unico (table_id = stable_id(doc, "table", idx) com idx achado por forca
bruta) recalcula a secao com nearest_section(idx, bbox gravado). Tabelas fundidas (varios itens)
ficam de fora da comparacao de secao, mas entram na checagem de cabecalho.
"""
from __future__ import annotations

import glob
import importlib
import inspect
import json
import sys
import types
from pathlib import Path

root, out = Path(sys.argv[1]), Path(sys.argv[2])
REPO = Path(__file__).resolve().parents[3]
BASE = REPO

pkg = types.ModuleType("docling_pipeline")
pkg.__path__ = [str(root / "docling_pipeline")]
sys.modules["docling_pipeline"] = pkg
ext = types.ModuleType("docling_pipeline.extractors")
ext.__path__ = [str(root / "docling_pipeline" / "extractors")]
sys.modules["docling_pipeline.extractors"] = ext

from docling_pipeline.helpers import stable_id  # noqa: E402
from docling_pipeline.models import BoundingBox, SectionRecord  # noqa: E402

T = importlib.import_module("docling_pipeline.extractors.tables")
C = importlib.import_module("docling_pipeline.extractors.common")
CLOSEST_ABOVE = {"closest_above": True} if "closest_above" in inspect.signature(C.nearest_section).parameters else {}

dirs = sorted(glob.glob(str(BASE / "airflow/state/resolution_inputs/*/extraction")))
dirs += [str(BASE / "extraction_cury"), str(BASE / "resultados_construtoras/abecip/extraction")]

res = {"tabelas": [], "cabecalhos": []}
for d in dirs:
    d = Path(d)
    sec_path = d / "sections/sections.jsonl"
    meta_path = d / "tables/metadata.json"
    if not sec_path.exists() or not meta_path.exists():
        continue
    sections = [SectionRecord(**json.loads(l)) for l in sec_path.read_text().splitlines() if l.strip()]
    meta = json.loads(meta_path.read_text())["items"]
    nome = d.parent.name.replace("dag_detecta_pdf_e_extrai__", "") if d.name == "extraction" and d.parent.name.startswith("dag_") else d.name
    if d.name == "extraction" and not d.parent.name.startswith("dag_"):
        nome = d.parent.name + "/extraction"
    for it in meta:
        md = json.loads((d / it["metadata_path"]).read_text())
        schema = md["schema"]
        # --- regra de cabecalho (vale p/ qualquer tabela, fundida ou nao)
        res["cabecalhos"].append(
            dict(ext=nome, table=it["name"][:60], page=it["page_number"], cols=schema[:4],
                 usable=T._header_is_usable(schema), looks_data=T._schema_looks_like_data(schema))
        )
        # --- secao (so itens unicos)
        doc_id, tid = md["document_id"], md["table_id"]
        idx = next((i for i in range(0, 9000) if stable_id(doc_id, "table", i) == tid), None)
        bb = md.get("bbox")
        if idx is None or not bb:
            res["tabelas"].append(dict(ext=nome, table=it["name"][:60], page=it["page_number"], idx=None))
            continue
        sec = C.nearest_section(
            sections, page_number=it["page_number"], anchor_bbox=BoundingBox(**bb), order_index=idx, **CLOSEST_ABOVE
        )
        res["tabelas"].append(
            dict(ext=nome, table=it["name"][:60], page=it["page_number"], idx=idx,
                 recorded=md["section_title"], replay=sec.title_raw if sec else None)
        )

out.write_text(json.dumps(res, ensure_ascii=False))
print(f"{root.name}: {len(res['tabelas'])} tabelas, {sum(1 for t in res['tabelas'] if t['idx'] is not None)} itens unicos")

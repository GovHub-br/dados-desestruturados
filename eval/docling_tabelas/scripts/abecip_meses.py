"""Para cada extracao ABECIP com a pagina de modalidades FUNDIDA, desfaz a fusao (divide nas linhas
cujo 1o campo e 'Agentes'), monta os 3 itens originais e roda o fluxo real (secao + propagacao + merge).

Uso: abecip_meses.py <raiz do codigo>
Valida primeiro que o fluxo, com o codigo ATUAL, reproduz a tabela fundida gravada.
"""
from __future__ import annotations

import glob
import importlib
import inspect
import json
import re
import sys
import types
import uuid
from pathlib import Path

import pandas as pd

root = Path(sys.argv[1])
REPO = Path(__file__).resolve().parents[3]
B = REPO
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
RX = re.compile(r"^\s*[456]\s*[-–]\s*(constru|aquisi)", re.I)


def sid(*p):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "||".join(str(x) for x in p if x is not None)))


dirs = sorted(glob.glob(str(B / "airflow/state/resolution_inputs/*abecip*/extraction")))
print(f"[{root.name}]")
for d in dirs:
    d = Path(d)
    mes = d.parent.name.split("__")[2] + "/" + d.parent.name.split("__")[3][:9]
    sections = [SectionRecord(**json.loads(l)) for l in (d / "sections/sections.jsonl").read_text().splitlines()]
    meta = json.loads((d / "tables/metadata.json").read_text())["items"]
    titulos = sorted((s for s in sections if RX.match(s.title_raw)), key=lambda s: s.order_index)
    tabs = []
    for it in meta:
        t = json.loads((d / it["path"]).read_text())
        md = json.loads((d / it["metadata_path"]).read_text())
        idx = next((i for i in range(0, 9000) if sid(md["document_id"], "table", i) == md["table_id"]), None)
        tabs.append((it, t, md, idx))
    fundida = [x for x in tabs if sum(1 for r in x[1]["rows"] if str(r[0]).strip().lower() == "agentes") >= 1 and len(x[1]["rows"]) > 15]
    if not fundida or len(titulos) != 3:
        print(f"  {mes}: sem tabela fundida ({len(titulos)} titulos) - ignorado")
        continue
    it, t, md, idx = fundida[0]
    rows = t["rows"]
    cortes = [i for i, r in enumerate(rows) if str(r[0]).strip().lower() == "agentes"]
    if cortes[0] != 0:  # 1o bloco: o cabecalho original pode nao estar demovido; assume bloco comeca em 0
        cortes = [0] + cortes
    blocos = [rows[a:b] for a, b in zip(cortes, cortes[1:] + [len(rows)])]
    if len(blocos) != 3:
        print(f"  {mes}: {len(blocos)} blocos (esperado 3) - ignorado")
        continue
    bb = md["bbox"]
    items = []
    for ti, blk in zip(titulos, blocos):
        items.append(dict(idx=ti.order_index + 1, page=it["page_number"],
                          bbox=BoundingBox(page_number=bb["page_number"], left=bb["left"], right=bb["right"],
                                           top=ti.bbox.bottom + 0.63, bottom=ti.bbox.bottom - 160, coord_origin=bb["coord_origin"]),
                          df=pd.DataFrame(blk[1:], columns=blk[0])))
    for it2, t2, md2, idx2 in tabs:  # demais tabelas (de item unico) entram em ordem
        if (it2, t2, md2, idx2) is not fundida[0] and idx2 is not None:
            items.append(dict(idx=idx2, page=it2["page_number"], bbox=BoundingBox(**md2["bbox"]),
                              df=pd.DataFrame(t2["rows"], columns=t2["schema"])))
    items.sort(key=lambda x: x["idx"])
    cands = []
    for x in items:
        s = C.nearest_section(sections, page_number=x["page"], anchor_bbox=x["bbox"], order_index=x["idx"], **CLOSEST_ABOVE)
        tr = s.title_raw if s else None
        cands.append(T.ExtractedTableCandidate(source_order_indices=(x["idx"],), page_number=x["page"], end_page_number=x["page"],
                                               section=s, bbox=x["bbox"], df=x["df"], title_raw=tr,
                                               title_canonical=slugify(tr) if tr else None))
    cands = T._propagate_headers(cands)
    cands = T._merge_table_fragments(cands, sections) if "sections" in inspect.signature(T._merge_table_fragments).parameters else T._merge_table_fragments(cands)
    p8 = [c for c in cands if c.page_number == it["page_number"] and ({idx_ for idx_ in c.source_order_indices} & {x["idx"] for x in items[:0]} or True)]
    alvo = [c for c in cands if any(i in {ti.order_index + 1 for ti in titulos} for i in c.source_order_indices)]
    resumo = " | ".join(f"{c.source_order_indices} '{str(c.title_raw)[:22]}' {len(c.df)}l cab0={str(c.df.columns[0])[:8]!r}" for c in alvo)
    print(f"  {mes}: fundida gravada={len(rows)}l -> {len(alvo)} tabela(s): {resumo}")

"""Desfaz a substituicao de cabecalho nas tabelas com a assinatura do defeito (Gerdau/Vale) e reexecuta
_propagate_headers na sequencia da extracao. O codigo ATUAL deve reproduzir o cabecalho trocado gravado."""
import sys, types, importlib, json, glob, re
from pathlib import Path
import pandas as pd
root = Path(sys.argv[1])
pkg = types.ModuleType("docling_pipeline"); pkg.__path__ = [str(root / "docling_pipeline")]; sys.modules["docling_pipeline"] = pkg
ext = types.ModuleType("docling_pipeline.extractors"); ext.__path__ = [str(root / "docling_pipeline" / "extractors")]; sys.modules["docling_pipeline.extractors"] = ext
from docling_pipeline.models import BoundingBox
T = importlib.import_module("docling_pipeline.extractors.tables")
REPO = Path(__file__).resolve().parents[3]
B = REPO / "airflow/state/resolution_inputs"
print(f"[{root.name}]")
for emp in ("gerdau", "vale"):
    d = Path(glob.glob(str(B / f"dag_detecta_pdf_e_extrai__{emp}__*/extraction"))[0])
    items = json.loads((d / "tables/metadata.json").read_text())["items"]
    cands, flagged, recorded = [], [], []
    vistos = []
    for k, it in enumerate(items):
        t = json.loads((d / it["path"]).read_text()); md = json.loads((d / it["metadata_path"]).read_text())
        sch, rows = list(t["schema"]), t["rows"]
        recorded.append(sch)
        stale = bool(rows) and any(sch == v for v in vistos) and sum(1 for c in rows[0] if re.search(r"[A-Za-zÀ-ÿ]{3,}", str(c))) >= 3 and list(rows[0]) != sch
        vistos.append(sch)
        if stale:  # desfaz: o cabecalho verdadeiro e a linha 0
            df = pd.DataFrame(rows[1:], columns=[str(c) for c in rows[0]]); flagged.append(k)
        else:
            df = pd.DataFrame(rows, columns=sch)
        cands.append(T.ExtractedTableCandidate(source_order_indices=(k,), page_number=it["page_number"], end_page_number=it["page_number"],
                     section=None, bbox=BoundingBox(**md["bbox"]) if md.get("bbox") else None, df=df,
                     title_raw=md.get("title_raw"), title_canonical=md.get("title_canonical")))
    out = T._propagate_headers(cands)
    print(f"  {emp}: tabelas com defeito reconstruidas = {len(flagged)}")
    for k in flagged:
        got = [str(c) for c in out[k].df.columns]
        if got == recorded[k]: res = "REPRODUZ o cabecalho TROCADO gravado (defeito)"
        elif got == [str(c) for c in cands[k].df.columns]: res = "MANTEM o cabecalho verdadeiro (ok)"
        else: res = "outro: " + str(got[:2])
        print(f"     tab#{k+1} p{items[k]['page_number']} ({len(cands[k].df)} linhas) -> {res} | cab={[c[:18] for c in got[:2]]}")

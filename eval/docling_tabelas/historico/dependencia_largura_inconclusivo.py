"""Quantas tabelas de hoje parecem DEPENDER do atalho 'copiar cabecalho so pela largura'?
Sinal: schema identico ao de tabela anterior da mesma extracao (mesma largura) e linha 0 NAO e cabecalho
(logo o cabecalho copiado esta certo). Para cada uma: a chave (titulo canonico, largura) coincide?"""
import sys, types, importlib, json, glob
from pathlib import Path
root = Path(sys.argv[1])
pkg = types.ModuleType("docling_pipeline"); pkg.__path__ = [str(root / "docling_pipeline")]; sys.modules["docling_pipeline"] = pkg
ext = types.ModuleType("docling_pipeline.extractors"); ext.__path__ = [str(root / "docling_pipeline" / "extractors")]; sys.modules["docling_pipeline.extractors"] = ext
T = importlib.import_module("docling_pipeline.extractors.tables")
B = Path(__file__).resolve().parents[3]
dirs = sorted(glob.glob(str(B / "airflow/state/resolution_inputs/*/extraction"))) + [str(B / "extraction_cury")]
tot = por_chave = so_largura = 0; ex = []
for d in dirs:
    d = Path(d); mp = d / "tables/metadata.json"
    if not mp.exists(): continue
    ant = []  # (schema tuple, title_canonical, page)
    nome = d.parent.name.split("__")[1] if d.parent.name.startswith("dag_") else d.name
    for it in json.loads(mp.read_text())["items"]:
        t = json.loads((d / it["path"]).read_text()); md = json.loads((d / it["metadata_path"]).read_text())
        sch = tuple(t["schema"]); key = md.get("title_canonical")
        if t["rows"] and any(sch == a[0] for a in ant) and not T._row_looks_like_header(t["rows"][0]):
            tot += 1
            prev = [a for a in ant if a[0] == sch]
            if any(a[1] == key for a in prev): por_chave += 1
            else:
                so_largura += 1
                if len(ex) < 8: ex.append(f"{nome} p{it['page_number']} titulo={str(key)[:34]!r} anterior={str(prev[-1][1])[:34]!r} (pag {prev[-1][2]}) | schema={list(sch)[:3]}")
        ant.append((sch, key, it["page_number"]))
print(f"[{root.name}] tabelas com schema repetido e linha 0 = dado (propagacao legitima provavel): {tot} | casam por (titulo,largura): {por_chave} | so por largura: {so_largura}")
for e in ex: print("   so-largura:", e)

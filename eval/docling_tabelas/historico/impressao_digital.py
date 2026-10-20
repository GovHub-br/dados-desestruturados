"""Procura, em TODAS as extracoes gravadas, a assinatura do defeito B (cabecalho velho + fusao):

  F1 (cabecalho velho): a 1a linha de dados parece um cabecalho (>=3 celulas com letras, <=1 dado)
      e o schema da tabela e IDENTICO ao de uma tabela anterior da mesma extracao, com largura igual.
      => o cabecalho real foi rebaixado a linha de dados e trocado por um cabecalho copiado.
  F2 (fusao): alguma linha do corpo (indice >= 1) parece cabecalho => varias tabelas coladas.

Usa as funcoes do codigo ATUAL do projeto (_row_looks_like_header etc.).
"""
from __future__ import annotations

import collections
import glob
import importlib
import json
import sys
import types
from pathlib import Path

BASE = Path(__file__).resolve().parents[3]
CODE = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE
pkg = types.ModuleType("docling_pipeline")
pkg.__path__ = [str(CODE / "docling_pipeline")]
sys.modules["docling_pipeline"] = pkg
ext = types.ModuleType("docling_pipeline.extractors")
ext.__path__ = [str(CODE / "docling_pipeline" / "extractors")]
sys.modules["docling_pipeline.extractors"] = ext
T = importlib.import_module("docling_pipeline.extractors.tables")

dirs = sorted(glob.glob(str(BASE / "airflow/state/resolution_inputs/*/extraction")))
dirs += [str(BASE / "extraction_cury"), str(BASE / "resultados_construtoras/abecip/extraction")]

por_emp = collections.defaultdict(lambda: dict(extracoes=0, tabelas=0, f1=0, f2=0, exemplos=[]))
for d in dirs:
    d = Path(d)
    mp = d / "tables/metadata.json"
    if not mp.exists():
        continue
    nome = d.parent.name.replace("dag_detecta_pdf_e_extrai__", "").split("__")[0] if d.name == "extraction" else d.name
    if nome.startswith("extraction") or nome == "extraction":
        nome = d.parent.name
    if d.name == "extraction" and d.parent.name == "abecip":
        nome = "abecip"
    items = json.loads(mp.read_text())["items"]
    e = por_emp[nome]
    e["extracoes"] += 1
    vistos: dict[int, list[list[str]]] = collections.defaultdict(list)
    for it in items:
        t = json.loads((d / it["path"]).read_text())
        schema, rows = t["schema"], t["rows"]
        e["tabelas"] += 1
        w = len(schema)
        f1 = (
            bool(rows)
            and T._row_looks_like_header(rows[0])
            and any(schema == prev for prev in vistos[w])
            and list(rows[0]) != list(schema)
        )
        f2 = any(T._row_looks_like_header(r) for r in rows[1:])
        vistos[w].append(schema)
        if f1:
            e["f1"] += 1
        if f2:
            e["f2"] += 1
        if (f1 or f2) and len(e["exemplos"]) < 2:
            e["exemplos"].append(f"p{it['page_number']} linhas={len(rows)} {'F1' if f1 else ''}{'F2' if f2 else ''} | schema={schema[:2]} | linha0={rows[0][:2] if rows else ''}")

print(f"{'empresa':14} {'extr.':>5} {'tabelas':>7} {'F1 cab.velho':>12} {'F2 fusao':>9}")
for k in sorted(por_emp):
    e = por_emp[k]
    print(f"{k:14} {e['extracoes']:>5} {e['tabelas']:>7} {e['f1']:>12} {e['f2']:>9}")
print("\nexemplos fora da ABECIP:")
for k in sorted(por_emp):
    if k.startswith("abecip"):
        continue
    for ex in por_emp[k]["exemplos"]:
        print(f"  {k:12} {ex}")

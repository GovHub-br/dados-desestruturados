"""Prova 1: quais itens do Docling (order_index) compoem a table005 da pagina 8?

O table_id e stable_id(document_id, "table", *source_order_indices). Como o hash
e deterministico, da para descobrir por forca bruta quais indices geraram o id.
"""
from __future__ import annotations

import itertools
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXTRACTION = ROOT / "resultados_construtoras/abecip/extraction"

# Carrega so helpers/text_utils.py, sem executar o __init__ do pacote (que puxa o docling).
pkg = types.ModuleType("docling_pipeline")
pkg.__path__ = [str(ROOT / "docling_pipeline")]
sys.modules["docling_pipeline"] = pkg
helpers = types.ModuleType("docling_pipeline.helpers")
helpers.__path__ = [str(ROOT / "docling_pipeline" / "helpers")]
sys.modules["docling_pipeline.helpers"] = helpers
import importlib

text_utils = importlib.import_module("docling_pipeline.helpers.text_utils")
stable_id = text_utils.stable_id

meta = json.loads((EXTRACTION / "tables/metadata.json").read_text())
doc_id = None
alvo = {}
for it in meta["items"]:
    md = json.loads((ROOT / "resultados_construtoras/abecip/extraction" / it["metadata_path"]).read_text())
    doc_id = md["document_id"]
    alvo[md["table_id"]] = (it["page_number"], it["name"][:50])

print("document_id:", doc_id)
print("tabelas a explicar:", len(alvo))

# order_index dos itens de secao (o iterate_items e unico, entao tabelas ficam entre eles)
secs = [json.loads(l) for l in (EXTRACTION / "sections/sections.jsonl").read_text().splitlines()]
ordens = sorted((s["order_index"], s["page_number"], s["title_raw"][:40]) for s in secs if s["page_number"] in (7, 8))
print("\norder_index das secoes das paginas 7-8 (lacunas = itens que nao sao secao):")
for o in ordens:
    print("  ", o)

encontrados = {}
faixa = range(0, 200)
# combinacoes de 1 a 3 itens, em ordem crescente (como o merge as concatena)
for n in (1, 2, 3):
    for combo in itertools.combinations(faixa, n):
        tid = stable_id(doc_id, "table", *combo)
        if tid in alvo and tid not in encontrados:
            encontrados[tid] = combo
    if len(encontrados) == len(alvo):
        break

print("\nRESULTADO (table_id -> itens de origem):")
for tid, (pg, nome) in alvo.items():
    print(f"  pag {pg} | {nome:50s} -> {encontrados.get(tid, 'nao encontrado (>3 itens ou fora da faixa)')}")

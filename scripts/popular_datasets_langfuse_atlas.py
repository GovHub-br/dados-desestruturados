#!/usr/bin/env python3
"""Popula os datasets de avaliacao off-line do Atlas a partir do MinIO.

Cada dataset cobre um recorte diferente da avaliacao:

- `atlas-e2e-regressao`: execucoes com layout publicado, para regressao ponta a ponta;
- `atlas-fallback-selecao-artefatos`: etapa isolada de selecao de evidencias;
- `atlas-fallback-layout-candidato`: etapa isolada de geracao de mapeamento;
- `atlas-transicao-resolucao-fallback`: decisao de escopo no handoff DAG2 -> DAG3.

Somente execucoes aprovadas viram saida esperada. Execucoes reprovadas entram
como itens negativos, com `metadata.rotulo = "reprovado"`, para que a avaliacao
tambem meça falsos positivos.

Uso:

    python scripts/popular_datasets_langfuse_atlas.py --dry-run
    python scripts/popular_datasets_langfuse_atlas.py
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from backfill_langfuse_atlas import (  # type: ignore  # noqa: E402
    FALLBACK_PREFIX,
    MinioReader,
    _group_fallback_executions,
)

DATASET_E2E = "atlas-e2e-regressao"
DATASET_SELECAO = "atlas-fallback-selecao-artefatos"
DATASET_CANDIDATO = "atlas-fallback-layout-candidato"
DATASET_TRANSICAO = "atlas-transicao-resolucao-fallback"


class LangfuseApi:
    """Chamadas REST autenticadas ao Langfuse."""

    def __init__(self) -> None:
        self.base = os.environ["LANGFUSE_BASE_URL"].rstrip("/")
        raw = f"{os.environ['LANGFUSE_PUBLIC_KEY']}:{os.environ['LANGFUSE_SECRET_KEY']}"
        self.auth = base64.b64encode(raw.encode()).decode()

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Executa um POST JSON e devolve a resposta decodificada."""
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(payload, ensure_ascii=False, default=str).encode(),
            method="POST",
            headers={
                "Authorization": f"Basic {self.auth}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode() or "{}")


def _truncate_json(value: Any, limit: int = 100_000) -> Any:
    """Impede que artefatos grandes estourem o item de dataset."""
    serialized = json.dumps(value, ensure_ascii=False, default=str)
    if len(serialized) <= limit:
        return value
    return {"_truncado": True, "_amostra": serialized[:limit]}


def build_items(reader: MinioReader) -> list[dict[str, Any]]:
    """Monta os itens de dataset a partir das execucoes de fallback do MinIO."""
    keys = reader.list_keys(FALLBACK_PREFIX)
    grouped = _group_fallback_executions(keys)
    items: list[dict[str, Any]] = []

    for identity, execution_keys in sorted(grouped.items(), key=lambda item: item[0][3]):
        dominio, entidade, document_id, execution_id = identity
        root = (
            f"{FALLBACK_PREFIX}{dominio}/{entidade}/"
            f"document_id={document_id}/execution_id={execution_id}/"
        )
        by_name = {key[len(root) :]: key for key in execution_keys if key.startswith(root)}

        publication = (
            reader.get_json(by_name["publicacao_layout_signature.json"])
            if "publicacao_layout_signature.json" in by_name
            else {}
        )
        revalidation = (
            reader.get_json(by_name["revalidation/resultado_revalidacao_candidato.json"])
            if "revalidation/resultado_revalidacao_candidato.json" in by_name
            else {}
        )
        candidate = (
            reader.get_json(by_name["layout_signature_candidato.json"])
            if "layout_signature_candidato.json" in by_name
            else {}
        )
        selection = (
            reader.get_json(by_name["selecao_artefatos_layout.json"])
            if "selecao_artefatos_layout.json" in by_name
            else {}
        )
        selection_input = (
            reader.get_json(by_name["entrada_llm_selecao_artefatos.json"])
            if "entrada_llm_selecao_artefatos.json" in by_name
            else {}
        )
        candidate_input = (
            reader.get_json(by_name["entrada_llm_layout_signature_candidato.json"])
            if "entrada_llm_layout_signature_candidato.json" in by_name
            else {}
        )
        schema_resolved = (
            reader.get_json(by_name["revalidation/schema_saida_resolvido.json"])
            if "revalidation/schema_saida_resolvido.json" in by_name
            else {}
        )

        aprovado = bool(revalidation.get("aprovado_para_publicacao"))
        publicado = str(publication.get("status") or "") == "publicado"
        rotulo = "aprovado" if aprovado else "reprovado"
        base_metadata = {
            "dominio": dominio,
            "entidade": entidade,
            "document_id": document_id,
            "execution_id": execution_id,
            "rotulo": rotulo,
            "fallback_prefix": root,
        }

        if publicado and schema_resolved:
            items.append(
                {
                    "datasetName": DATASET_E2E,
                    "id": f"e2e::{entidade}::{document_id}",
                    "input": _truncate_json(
                        {
                            "dominio": dominio,
                            "entidade": entidade,
                            "document_id": document_id,
                            "layout_signature_publicado": publication.get(
                                "published_layout_uri"
                            ),
                        }
                    ),
                    "expectedOutput": _truncate_json(schema_resolved),
                    "metadata": {
                        **base_metadata,
                        "versao_layout": publication.get("versao_publicada"),
                    },
                }
            )

        if selection and selection_input:
            items.append(
                {
                    "datasetName": DATASET_SELECAO,
                    "id": f"selecao::{entidade}::{document_id}::{execution_id[-24:]}",
                    "input": _truncate_json(
                        selection_input.get("user_payload") or selection_input.get("messages")
                    ),
                    "expectedOutput": _truncate_json(selection),
                    "metadata": base_metadata,
                }
            )

        if candidate and candidate_input:
            items.append(
                {
                    "datasetName": DATASET_CANDIDATO,
                    "id": f"candidato::{entidade}::{document_id}::{execution_id[-24:]}",
                    "input": _truncate_json(
                        candidate_input.get("user_payload") or candidate_input.get("messages")
                    ),
                    "expectedOutput": _truncate_json(
                        {
                            "mapeamento_canonico": candidate.get("mapeamento_canonico"),
                            "regras_deteccao_mudanca": candidate.get(
                                "regras_deteccao_mudanca"
                            ),
                            "escopo_correcao": candidate.get("escopo_correcao"),
                        }
                    ),
                    "metadata": base_metadata,
                }
            )

        if candidate:
            items.append(
                {
                    "datasetName": DATASET_TRANSICAO,
                    "id": f"transicao::{entidade}::{document_id}::{execution_id[-24:]}",
                    "input": _truncate_json(
                        {
                            "entidade": entidade,
                            "document_id": document_id,
                            "status_revalidacao": revalidation.get("status_compatibilidade"),
                            "codigos_alerta": revalidation.get("codigos_alerta"),
                        }
                    ),
                    "expectedOutput": _truncate_json(
                        {"escopo_correcao": candidate.get("escopo_correcao")}
                    ),
                    "metadata": base_metadata,
                }
            )

    return items


def main() -> int:
    """Envia os itens montados para os datasets do Langfuse."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    reader = MinioReader()
    items = build_items(reader)
    if args.limit:
        items = items[: args.limit]

    counts: dict[str, int] = {}
    for item in items:
        counts[item["datasetName"]] = counts.get(item["datasetName"], 0) + 1
    print("itens montados por dataset:")
    for name, count in sorted(counts.items()):
        print(f"  {name:<40} {count}")

    if args.dry_run:
        print("\ndry-run: nada enviado.")
        return 0

    api = LangfuseApi()
    sent = 0
    for item in items:
        try:
            api.post("/api/public/dataset-items", item)
            sent += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  falha em {item['id']}: {exc}")
    print(f"\n{sent}/{len(items)} itens enviados.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

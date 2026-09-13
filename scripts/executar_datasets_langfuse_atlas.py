#!/usr/bin/env python3
"""Executa os datasets do Atlas e preenche a aba Experiments do Langfuse.

A aba Experiments lista *dataset runs*. Ter datasets criados nao basta: sem
nenhuma execucao registrada, a aba fica vazia mesmo com todos os itens no lugar.
Este script cria essas execucoes, em dois modos:

`replay` (padrao, nao chama LLM)
    Liga os traces ja projetados aos itens de dataset correspondentes, casando por
    document_id + execution_id. Custo zero: aproveita a base historica que o
    backfill ja projetou e da uma linha de base imediata por release.

`executar` (opt-in, chama LLM e custa dinheiro)
    Reexecuta a etapa isolada sobre o `input` do item e pontua a saida contra o
    `expectedOutput` de forma deterministica. E a avaliacao off-line por etapa
    descrita em docs/guides/desenvolvimento-orientado-a-metricas.md.

Uso:

    python scripts/executar_datasets_langfuse_atlas.py --modo replay
    python scripts/executar_datasets_langfuse_atlas.py --modo replay --release prod-0.1.0
    python scripts/executar_datasets_langfuse_atlas.py --modo executar \\
        --dataset atlas-fallback-selecao-artefatos --limit 5
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from document_processing.application.use_cases.fallback.candidate_evaluation import (  # noqa: E402
    validar_candidato,
)
from document_processing.domain.observability import (  # noqa: E402
    MetricValue,
    avaliar_mapeamento_canonico,
    avaliar_selecao_artefatos,
    metrica_de_validade,
)

DATASETS_REPLAY = (
    "atlas-e2e-regressao",
    "atlas-fallback-selecao-artefatos",
    "atlas-fallback-layout-candidato",
    "atlas-transicao-resolucao-fallback",
)

# Datasets cuja etapa e autocontida: o `input` guarda tudo que a LLM recebeu, entao
# a etapa pode ser reexecutada isolada. Os outros dois dependem da DAG inteira e
# so existem em modo replay.
DATASETS_EXECUTAVEIS = {
    "atlas-fallback-selecao-artefatos": "selecao_artefatos",
    "atlas-fallback-layout-candidato": "layout_signature_candidato",
}


class LangfuseApi:
    """Acesso REST ao Langfuse, so com a biblioteca padrao."""

    def __init__(self) -> None:
        self.base = os.environ["LANGFUSE_BASE_URL"].rstrip("/")
        raw = f"{os.environ['LANGFUSE_PUBLIC_KEY']}:{os.environ['LANGFUSE_SECRET_KEY']}"
        self.auth = base64.b64encode(raw.encode()).decode()

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Executa uma chamada autenticada e devolve o corpo decodificado."""
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Basic {self.auth}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode() or "{}")

    def _paginate(self, path: str, limit: int = 100) -> list[dict[str, Any]]:
        """Percorre todas as paginas de um endpoint de listagem."""
        itens: list[dict[str, Any]] = []
        page = 1
        separator = "&" if "?" in path else "?"
        while True:
            data = self._request("GET", f"{path}{separator}limit={limit}&page={page}")
            lote = data.get("data", [])
            itens.extend(lote)
            total = int(data.get("meta", {}).get("totalItems", 0))
            if not lote or page * limit >= total:
                return itens
            page += 1

    def traces(self) -> list[dict[str, Any]]:
        """Le todos os traces do projeto."""
        return self._paginate("/api/public/traces")

    def dataset_items(self, dataset: str) -> list[dict[str, Any]]:
        """Le os itens correntes de um dataset."""
        return self._paginate(
            f"/api/public/dataset-items?datasetName={urllib.parse.quote(dataset)}"
        )

    def criar_run_item(
        self,
        *,
        dataset_item_id: str,
        run_name: str,
        trace_id: str,
        run_description: str,
        metadata: dict[str, Any],
    ) -> None:
        """Vincula um item de dataset a um trace dentro de uma execucao."""
        self._request(
            "POST",
            "/api/public/dataset-run-items",
            {
                "datasetItemId": dataset_item_id,
                "runName": run_name,
                "traceId": trace_id,
                "runDescription": run_description,
                "metadata": metadata,
            },
        )


def _chave_execucao(metadata: Any) -> tuple[str, str] | None:
    """Chave de pareamento entre item de dataset e trace.

    E a mesma identidade usada por comparar_releases_langfuse.py: documento mais
    execucao. Casar so por documento juntaria execucoes diferentes do mesmo PDF.
    """
    if not isinstance(metadata, dict):
        return None
    documento = str(metadata.get("document_id") or "").strip()
    execucao = str(metadata.get("execution_id") or "").strip()
    if not documento or not execucao:
        return None
    return documento, execucao


def indexar_traces(traces: list[dict[str, Any]]) -> dict[str, dict[tuple[str, str], str]]:
    """Mapeia release -> (documento, execucao) -> trace_id."""
    indice: dict[str, dict[tuple[str, str], str]] = defaultdict(dict)
    for trace in traces:
        metadata = trace.get("metadata")
        chave = _chave_execucao(metadata)
        if not chave:
            continue
        release = str(trace.get("release") or "sem-release")
        # Varios traces podem compartilhar a chave em reprojecoes; o ultimo vence,
        # e a listagem vem do mais recente para o mais antigo.
        indice[release].setdefault(chave, trace["id"])
    return indice


def executar_replay(
    api: LangfuseApi,
    *,
    datasets: tuple[str, ...],
    releases: list[str] | None,
    dry_run: bool,
) -> int:
    """Liga traces historicos aos itens de dataset, criando um run por release."""
    indice = indexar_traces(api.traces())
    if not indice:
        print("nenhum trace com document_id e execution_id no metadata.")
        return 1

    alvos = releases or sorted(indice)
    total_vinculos = 0
    for dataset in datasets:
        itens = api.dataset_items(dataset)
        print(f"\n{dataset} ({len(itens)} itens)")
        for release in alvos:
            por_chave = indice.get(release, {})
            if not por_chave:
                continue
            run_name = f"replay-{release}"
            vinculados = 0
            for item in itens:
                chave = _chave_execucao(item.get("metadata"))
                trace_id = por_chave.get(chave) if chave else None
                if not trace_id:
                    continue
                if not dry_run:
                    api.criar_run_item(
                        dataset_item_id=item["id"],
                        run_name=run_name,
                        trace_id=trace_id,
                        run_description=(
                            "Vinculo entre itens do dataset e os traces ja projetados "
                            f"da release {release}. Nao houve reexecucao."
                        ),
                        metadata={"modo": "replay", "release": release},
                    )
                vinculados += 1
            if vinculados:
                marca = "[dry-run] " if dry_run else ""
                print(f"  {marca}{run_name}: {vinculados}/{len(itens)} itens vinculados")
                total_vinculos += vinculados
    print(f"\n{total_vinculos} vinculos no total.")
    return 0


def _caminhos_selecao(payload: Any) -> set[str]:
    """Extrai os paths de artefato de uma selecao, ignorando o resto."""
    if not isinstance(payload, dict):
        return set()
    return {
        str(item.get("path"))
        for item in payload.get("artifact_paths", [])
        if isinstance(item, dict) and item.get("path")
    }


def _avaliar_selecao(resposta: Any, item: dict[str, Any]) -> list[MetricValue]:
    """Pontua a selecao de evidencias contra os artefatos da referencia."""
    esperado = _caminhos_selecao(item.get("expectedOutput"))
    return avaliar_selecao_artefatos(_caminhos_selecao(resposta), esperado)


def _avaliar_candidato(resposta: Any, item: dict[str, Any]) -> list[MetricValue]:
    """Pontua o mapeamento canonico e aplica as regras de negocio da producao.

    A validade vem junto de proposito: F1 alto num candidato que a DAG rejeitaria
    e um numero que engana. Quando o contexto historico nao permite validar, a
    metrica nao e emitida — ausencia e diferente de reprovacao.
    """
    obtido = resposta if isinstance(resposta, dict) else {}
    esperado = item.get("expectedOutput")
    esperado = esperado if isinstance(esperado, dict) else {}
    metricas = avaliar_mapeamento_canonico(
        obtido.get("mapeamento_canonico"),
        esperado.get("mapeamento_canonico"),
    )
    veredito = validar_candidato(resposta, mensagens=item.get("input"))
    if veredito.validavel:
        metricas.append(
            metrica_de_validade(valido=veredito.valido, motivo=veredito.motivo)
        )
    return metricas


AVALIADORES = {
    "selecao_artefatos": _avaliar_selecao,
    "layout_signature_candidato": _avaliar_candidato,
}


def _resumo(erro: str | None, metricas: list[MetricValue]) -> str:
    """Linha curta de acompanhamento, com os degraus que existirem no item."""
    if erro:
        return "erro"
    por_nome = {metrica.name: metrica.value for metrica in metricas}
    partes = []
    for rotulo, nome in (
        ("f1", "avaliacao_f1"),
        ("tipo", "avaliacao_acerto_tipo_origem"),
        ("arquivo", "avaliacao_acerto_arquivo_origem"),
        ("instrucao", "avaliacao_acerto_instrucao_origem"),
    ):
        valor = por_nome.get(nome)
        if isinstance(valor, (int, float)):
            partes.append(f"{rotulo}={valor:.2f}")
    validade = por_nome.get("avaliacao_candidato_valido")
    if validade is not None:
        partes.append("valido" if validade else "INVALIDO")
    return "  ".join(partes) or "sem referencia"


def executar_etapa(
    api: LangfuseApi,
    *,
    dataset: str,
    limite: int,
    run_name: str,
    dry_run: bool,
) -> int:
    """Reexecuta uma etapa isolada sobre os itens e pontua contra o esperado."""
    from document_processing.infrastructure.llm.client import (
        FallbackLlmClient,
        FallbackLlmClientError,
    )
    from document_processing.infrastructure.observability.langfuse_client import (
        LangfuseIngestionClient,
        new_id,
    )

    etapa = DATASETS_EXECUTAVEIS[dataset]
    avaliar = AVALIADORES[etapa]
    itens = api.dataset_items(dataset)[:limite]
    cliente_llm = FallbackLlmClient()
    observador = LangfuseIngestionClient.from_environment()

    print(f"\n{dataset} -> etapa {etapa}: {len(itens)} itens, run '{run_name}'")
    executados = 0
    for item in itens:
        entrada = item.get("input")
        inicio = datetime.now(UTC)
        if dry_run:
            print(f"  [dry-run] {item['id']}")
            continue

        erro: str | None = None
        resposta: Any = None
        try:
            if isinstance(entrada, list):
                # O dataset do candidato guarda a conversa inteira ja montada.
                resposta, _ = cliente_llm.generate_json(messages=entrada)
            else:
                from document_processing.application.use_cases.fallback.prompts import (
                    artifact_selection_system_prompt,
                )

                resposta, _ = cliente_llm.generate_json(
                    system_prompt=artifact_selection_system_prompt(),
                    user_payload=entrada,
                )
        except FallbackLlmClientError as exc:
            erro = str(exc)

        trace_id = new_id()
        observador.trace(
            trace_id=trace_id,
            name=f"atlas.avaliacao.{etapa}",
            session_id=str((item.get("metadata") or {}).get("document_id") or item["id"]),
            user_id=str((item.get("metadata") or {}).get("entidade") or "desconhecida"),
            timestamp=inicio.isoformat(),
            input_payload=entrada,
            output_payload=resposta if erro is None else {"erro": erro},
            metadata={
                "dataset": dataset,
                "etapa": etapa,
                "dataset_item_id": item["id"],
                **(item.get("metadata") or {}),
            },
            tags=[f"dataset:{dataset}", f"etapa:{etapa}", "avaliacao_offline"],
        )
        metricas = [
            MetricValue(
                name="avaliacao_schema_valido",
                value=0.0 if erro else 1.0,
                data_type="BOOLEAN",
                comment=erro[:500] if erro else "A LLM devolveu JSON utilizavel.",
            )
        ]
        if erro is None:
            metricas.extend(avaliar(resposta, item))
        for metrica in metricas:
            observador.score(
                trace_id=trace_id,
                name=metrica.name,
                value=metrica.value,
                data_type=metrica.data_type,
                comment=metrica.comment,
            )
        observador.flush()

        api.criar_run_item(
            dataset_item_id=item["id"],
            run_name=run_name,
            trace_id=trace_id,
            run_description=f"Reexecucao isolada da etapa {etapa}.",
            metadata={"modo": "executar", "etapa": etapa},
        )
        executados += 1
        print(f"  {item['id'][:58]}  {_resumo(erro, metricas)}")

    print(f"\n{executados} itens executados.")
    return 0


def main() -> int:
    """Cria dataset runs no Langfuse, por replay ou por reexecucao da etapa."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modo", choices=("replay", "executar"), default="replay")
    parser.add_argument("--dataset", action="append", dest="datasets")
    parser.add_argument("--release", action="append", dest="releases")
    parser.add_argument("--run-nome")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    api = LangfuseApi()

    if args.modo == "replay":
        datasets = tuple(args.datasets or DATASETS_REPLAY)
        return executar_replay(
            api, datasets=datasets, releases=args.releases, dry_run=args.dry_run
        )

    if not args.limit:
        parser.error(
            "--limit e obrigatorio no modo executar: cada item consome uma chamada de LLM."
        )
    datasets = tuple(args.datasets or DATASETS_EXECUTAVEIS)
    desconhecidos = [nome for nome in datasets if nome not in DATASETS_EXECUTAVEIS]
    if desconhecidos:
        parser.error(
            f"datasets sem etapa autocontida: {', '.join(desconhecidos)}. "
            f"Executaveis: {', '.join(DATASETS_EXECUTAVEIS)}."
        )

    release = os.getenv("ATLAS_RELEASE", "").strip() or "local-dev"
    for dataset in datasets:
        executar_etapa(
            api,
            dataset=dataset,
            limite=args.limit,
            run_name=args.run_nome or f"exec-{release}",
            dry_run=args.dry_run,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

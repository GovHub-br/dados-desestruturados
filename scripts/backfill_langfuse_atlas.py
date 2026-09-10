#!/usr/bin/env python3
"""Reconstroi no Langfuse as execucoes do Atlas ja persistidas no MinIO.

O script le os artefatos de `execucoes/` e `fallback/` e emite, por execucao,
um trace com spans deterministicos, generations de LLM e as metricas do
catalogo em `document_processing.domain.observability`.

Serve para dois propositos:

1. dar base historica as metricas antes de qualquer nova execucao;
2. permitir comparar releases do projeto sobre os mesmos documentos.

Uso:

    python scripts/backfill_langfuse_atlas.py --dry-run
    python scripts/backfill_langfuse_atlas.py --release baseline-2026-09
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from document_processing.domain.observability import (  # noqa: E402
    end_to_end_metrics,
    fallback_execution_metrics,
    fallback_stage_metrics,
    layout_validation_metrics,
    prompt_set_fingerprint,
    resolution_metrics,
    transition_metrics,
)
from document_processing.infrastructure.observability import (  # noqa: E402
    LangfuseIngestionClient,
    new_id,
)

FALLBACK_PREFIX = "fallback/"
EXECUTION_PREFIX = "execucoes/"

LLM_STAGES = (
    "selecao_artefatos",
    "fragmento_layout_signature",
    "layout_signature_candidato",
)


def _iso(value: Any, *, fallback: datetime | None = None) -> str:
    """Normaliza timestamps dos artefatos para ISO-8601 com timezone."""
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.isoformat()
        except ValueError:
            pass
    return (fallback or datetime.now(UTC)).isoformat()


def _execution_started_at(execution_id: str) -> datetime:
    """Extrai o inicio da execucao do proprio `execution_id`."""
    match = re.search(r"(\d{4}-\d{2}-\d{2}T[\d_]+\.\d+)", execution_id)
    if match:
        raw = match.group(1).replace("_", ":")
        try:
            return datetime.fromisoformat(raw).replace(tzinfo=UTC)
        except ValueError:
            pass
    match = re.search(r"(\d{8}T\d{6}Z)", execution_id)
    if match:
        try:
            return datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        except ValueError:
            pass
    return datetime.now(UTC)


class MinioReader:
    """Leitura direta do bucket de data lake, sem passar pelo runtime do Airflow."""

    def __init__(self) -> None:
        from minio import Minio

        endpoint = os.getenv("MINIO_BACKFILL_ENDPOINT", "").strip() or os.getenv(
            "MINIO_ENDPOINT", "localhost:9000"
        )
        self.bucket = os.getenv("MINIO_BUCKET_DATA_LAKE", "ocr-cidades")
        self.client = Minio(
            endpoint,
            access_key=os.getenv("MINIO_ROOT_USER", "minioadmin"),
            secret_key=os.getenv("MINIO_ROOT_PASSWORD", "minioadmin123"),
            secure=os.getenv("MINIO_SECURE", "false").strip().lower() in {"1", "true", "yes"},
        )

    def list_keys(self, prefix: str) -> list[str]:
        """Lista recursivamente as chaves sob um prefixo."""
        return [
            obj.object_name
            for obj in self.client.list_objects(self.bucket, prefix=prefix, recursive=True)
        ]

    def get_json(self, key: str) -> dict[str, Any]:
        """Le um objeto JSON; devolve dicionario vazio quando ausente ou invalido."""
        try:
            response = self.client.get_object(self.bucket, key)
            try:
                return json.loads(response.read().decode("utf-8"))
            finally:
                response.close()
                response.release_conn()
        except Exception:
            return {}


def _parse_execution_path(key: str) -> dict[str, str] | None:
    """Extrai dominio, entidade, document_id e execution_id de uma chave."""
    match = re.match(
        r"^fallback/(?P<dominio>[^/]+)/(?P<entidade>[^/]+)/"
        r"document_id=(?P<document_id>[^/]+)/execution_id=(?P<execution_id>[^/]+)/(?P<resto>.*)$",
        key,
    )
    if not match:
        return None
    return match.groupdict()


def _group_fallback_executions(keys: list[str]) -> dict[tuple[str, ...], list[str]]:
    """Agrupa as chaves do fallback por execucao."""
    grouped: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for key in keys:
        parsed = _parse_execution_path(key)
        if not parsed:
            continue
        identity = (
            parsed["dominio"],
            parsed["entidade"],
            parsed["document_id"],
            parsed["execution_id"],
        )
        grouped[identity].append(key)
    return grouped


def _stage_artifacts(keys: list[str], root: str) -> dict[str, dict[int, dict[str, str]]]:
    """Indexa os artefatos de LLM por estagio e tentativa."""
    index: dict[str, dict[int, dict[str, str]]] = defaultdict(lambda: defaultdict(dict))
    for key in keys:
        filename = key.split("/")[-1]
        for kind in ("entrada_llm", "resposta_llm", "erro_llm"):
            if not filename.startswith(f"{kind}_"):
                continue
            remainder = filename[len(kind) + 1 :].removesuffix(".json")
            attempt = 0
            attempt_match = re.search(r"_tentativa_(\d+)$", remainder)
            if attempt_match:
                attempt = int(attempt_match.group(1))
                remainder = remainder[: attempt_match.start()]
            relative = key[len(root) :]
            unit = relative.rsplit("/", 1)[0].strip("/") if "/" in relative else ""
            stage = f"{unit}/{remainder}" if unit else remainder
            index[stage][attempt][kind] = key
    return index


def backfill_fallback_execution(
    reader: MinioReader,
    client: LangfuseIngestionClient,
    identity: tuple[str, ...],
    keys: list[str],
    *,
    dry_run: bool,
) -> dict[str, Any]:
    """Emite um trace completo para uma execucao de fallback ja persistida."""
    dominio, entidade, document_id, execution_id = identity
    root = (
        f"{FALLBACK_PREFIX}{dominio}/{entidade}/"
        f"document_id={document_id}/execution_id={execution_id}/"
    )
    started_at = _execution_started_at(execution_id)
    trace_id = new_id()

    by_name = {key[len(root) :]: key for key in keys if key.startswith(root)}

    classification = reader.get_json(by_name.get("classificacao_falha.json", "")) if (
        "classificacao_falha.json" in by_name
    ) else {}
    candidate = reader.get_json(by_name["layout_signature_candidato.json"]) if (
        "layout_signature_candidato.json" in by_name
    ) else {}
    revalidation = reader.get_json(
        by_name["revalidation/resultado_revalidacao_candidato.json"]
    ) if "revalidation/resultado_revalidacao_candidato.json" in by_name else {}
    revalidation_validation = reader.get_json(
        by_name["revalidation/validacao_layout_signature.json"]
    ) if "revalidation/validacao_layout_signature.json" in by_name else {}
    revalidation_audit = reader.get_json(
        by_name["revalidation/auditoria_resolucao.json"]
    ) if "revalidation/auditoria_resolucao.json" in by_name else {}
    publication = reader.get_json(by_name["publicacao_layout_signature.json"]) if (
        "publicacao_layout_signature.json" in by_name
    ) else {}

    scope = (
        candidate.get("escopo_correcao")
        or classification.get("escopo_correcao")
        or classification.get("escopo")
        or ("sem_candidato" if not candidate else None)
    )

    tags = [
        f"dominio:{dominio}",
        f"entidade:{entidade}",
        "etapa:fallback",
        "dag:dag_valida_e_fallback_llm",
        "origem:backfill",
    ]
    if scope:
        tags.append(f"escopo:{scope}")

    client.trace(
        trace_id=trace_id,
        name="atlas.fallback",
        session_id=document_id,
        user_id=entidade,
        timestamp=started_at.isoformat(),
        input_payload={
            "dominio": dominio,
            "entidade": entidade,
            "document_id": document_id,
            "execution_id": execution_id,
        },
        output_payload={
            "escopo_correcao": scope,
            "revalidacao": revalidation.get("status_compatibilidade"),
            "publicacao": publication.get("status"),
            "versao_publicada": publication.get("versao_publicada"),
        },
        metadata={
            "dominio": dominio,
            "entidade": entidade,
            "document_id": document_id,
            "execution_id": execution_id,
            "fallback_prefix": root,
        },
        tags=tags,
    )

    stage_index = _stage_artifacts(keys, root)
    total_attempts = 0
    total_tokens = 0
    cursor = started_at

    for stage, attempts in sorted(stage_index.items()):
        stage_usages: list[dict[str, Any]] = []
        stage_success = False
        last_generation_id: str | None = None
        prompts_usados: list[dict[str, Any]] = []
        conjunto_prompt: str | None = None
        versao_conjunto: int | None = None
        attempt_numbers = sorted(attempts)
        for attempt in attempt_numbers:
            artifacts = attempts[attempt]
            request = reader.get_json(artifacts.get("entrada_llm", "")) if artifacts.get(
                "entrada_llm"
            ) else {}
            response = reader.get_json(artifacts.get("resposta_llm", "")) if artifacts.get(
                "resposta_llm"
            ) else {}
            error = reader.get_json(artifacts.get("erro_llm", "")) if artifacts.get(
                "erro_llm"
            ) else {}

            # So execucoes posteriores a adocao dos prompts no Langfuse trazem
            # estes campos. Artefato antigo nao recebe atribuicao inventada.
            prompts_usados = request.get("prompts_utilizados") or prompts_usados
            conjunto_prompt = request.get("prompt_conjunto") or conjunto_prompt
            if request.get("prompt_conjunto_versao") is not None:
                versao_conjunto = request.get("prompt_conjunto_versao")

            metadata_api = response.get("api_response_metadata") or {}
            usage = metadata_api.get("usage") if isinstance(metadata_api, dict) else {}
            if isinstance(usage, dict):
                stage_usages.append(usage)
                total_tokens += int(usage.get("total_tokens") or 0)

            start = _iso(request.get("persistido_em"), fallback=cursor)
            end = _iso(
                response.get("persistido_em") or error.get("persistido_em"),
                fallback=cursor + timedelta(seconds=1),
            )
            cursor = datetime.fromisoformat(end)
            total_attempts += 1
            failed = bool(error)
            if not failed:
                stage_success = True

            generation_id = client.generation(
                trace_id=trace_id,
                name=f"fallback.{stage}",
                model=request.get("model"),
                model_parameters={
                    "max_tokens": (request.get("opcoes_requisicao_llm") or {}).get("max_tokens"),
                    "thinking_mode": (request.get("opcoes_requisicao_llm") or {}).get(
                        "thinking_mode"
                    ),
                },
                start_time=start,
                end_time=end,
                input_payload=request.get("messages")
                or {
                    "system_prompt": request.get("system_prompt"),
                    "user_payload": request.get("user_payload"),
                },
                output_payload=response.get("parsed_response") or error.get("parsed_response"),
                usage=usage if isinstance(usage, dict) else None,
                level="ERROR" if failed else "DEFAULT",
                status_message=error.get("error_message") if failed else None,
                metadata={
                    "stage": stage,
                    "attempt": attempt,
                    "provider": request.get("provider"),
                    "finish_reason": metadata_api.get("finish_reason")
                    if isinstance(metadata_api, dict)
                    else None,
                    "error_type": error.get("error_type"),
                    "prompts_utilizados": prompts_usados or None,
                },
                prompt_name=(
                    f"atlas/fallback/conjuntos/{conjunto_prompt}"
                    if conjunto_prompt
                    else None
                ),
                prompt_version=versao_conjunto,
            )
            last_generation_id = generation_id

        for metric in fallback_stage_metrics(
            stage=stage,
            attempts=len(attempt_numbers),
            succeeded=stage_success,
            usage_by_attempt=stage_usages,
            prompt_fingerprint=(
                prompt_set_fingerprint(conjunto_prompt, prompts_usados)
                if conjunto_prompt
                else None
            ),
        ):
            client.score(
                trace_id=trace_id,
                name=metric.name,
                value=metric.value,
                observation_id=last_generation_id,
                data_type=metric.data_type,
                comment=metric.comment,
                metadata=metric.metadata,
            )

    revalidation_span = None
    if revalidation or revalidation_validation:
        revalidation_span = client.span(
            trace_id=trace_id,
            name="fallback.revalidacao_dag2",
            start_time=cursor.isoformat(),
            end_time=_iso(
                revalidation_validation.get("executado_em"),
                fallback=cursor + timedelta(seconds=1),
            ),
            input_payload={"candidato": revalidation.get("candidate_layout_object_key")},
            output_payload=revalidation_validation.get("status_compatibilidade"),
            metadata={"aprovado": revalidation.get("aprovado_para_publicacao")},
        )
        for metric in layout_validation_metrics(revalidation_validation):
            client.score(
                trace_id=trace_id,
                name=metric.name,
                value=metric.value,
                observation_id=revalidation_span,
                data_type=metric.data_type,
                comment=metric.comment,
                metadata={**metric.metadata, "etapa": "revalidacao_candidato"},
            )

    resolution_scores: list[Any] = []
    if revalidation_audit:
        resolution_scores = resolution_metrics(revalidation_audit)
        for metric in resolution_scores:
            client.score(
                trace_id=trace_id,
                name=metric.name,
                value=metric.value,
                observation_id=revalidation_span,
                data_type=metric.data_type,
                comment=metric.comment,
                metadata={**metric.metadata, "etapa": "revalidacao_candidato"},
            )

    if publication:
        client.span(
            trace_id=trace_id,
            name="fallback.publicacao_layout",
            start_time=_iso(publication.get("publicado_em"), fallback=cursor),
            end_time=_iso(publication.get("publicado_em"), fallback=cursor),
            output_payload={
                "status": publication.get("status"),
                "versao_publicada": publication.get("versao_publicada"),
                "published_layout_uri": publication.get("published_layout_uri"),
            },
        )

    for metric in fallback_execution_metrics(
        scope=scope,
        candidate_valid=bool(candidate),
        revalidation=revalidation,
        revalidation_validation=revalidation_validation,
        publication=publication,
        total_llm_attempts=total_attempts,
        total_tokens=total_tokens,
    ):
        client.score(
            trace_id=trace_id,
            name=metric.name,
            value=metric.value,
            data_type=metric.data_type,
            comment=metric.comment,
            metadata=metric.metadata,
        )

    coverage = next(
        (m.value for m in resolution_scores if m.name == "resolucao_cobertura_obrigatorios"),
        None,
    )
    for metric in transition_metrics(
        origem="fallback",
        destino="resolucao",
        habilitada=bool(revalidation.get("aprovado_para_publicacao")),
        motivo=revalidation.get("status_compatibilidade"),
    ):
        client.score(
            trace_id=trace_id,
            name=metric.name,
            value=metric.value,
            data_type=metric.data_type,
            comment=metric.comment,
            metadata=metric.metadata,
        )

    for metric in end_to_end_metrics(
        sucesso=str(publication.get("status") or "") == "publicado",
        exigiu_llm=True,
        tokens_totais=total_tokens,
        cobertura_final=float(coverage) if isinstance(coverage, (int, float)) else None,
        apto_para_bronze=bool(revalidation.get("aprovado_para_publicacao")),
    ):
        client.score(
            trace_id=trace_id,
            name=metric.name,
            value=metric.value,
            data_type=metric.data_type,
            comment=metric.comment,
            metadata=metric.metadata,
        )

    return {
        "trace_id": trace_id,
        "entidade": entidade,
        "execution_id": execution_id,
        "llm_calls": total_attempts,
        "tokens": total_tokens,
        "publicado": str(publication.get("status") or "") == "publicado",
    }


def main() -> int:
    """Percorre o MinIO e envia as execucoes historicas para o Langfuse."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", default=None, help="Rotulo de versao do backfill.")
    parser.add_argument("--limit", type=int, default=0, help="Maximo de execucoes.")
    parser.add_argument("--entidade", default=None, help="Filtra por entidade.")
    parser.add_argument("--dry-run", action="store_true", help="Nao envia ao Langfuse.")
    args = parser.parse_args()

    if args.release:
        os.environ["ATLAS_RELEASE"] = args.release
    os.environ.setdefault("LANGFUSE_ENVIRONMENT", "backfill")

    reader = MinioReader()
    client = LangfuseIngestionClient.from_environment()
    if args.dry_run:
        client.enabled = False

    keys = reader.list_keys(FALLBACK_PREFIX)
    grouped = _group_fallback_executions(keys)
    if args.entidade:
        grouped = {k: v for k, v in grouped.items() if k[1] == args.entidade}

    identities = sorted(grouped, key=lambda item: item[3])
    if args.limit:
        identities = identities[: args.limit]

    print(f"execucoes de fallback encontradas: {len(grouped)} | processando: {len(identities)}")
    print(f"release: {client.release} | environment: {client.environment}")

    results = []
    for index, identity in enumerate(identities, start=1):
        summary = backfill_fallback_execution(
            reader, client, identity, grouped[identity], dry_run=args.dry_run
        )
        results.append(summary)
        print(
            f"[{index}/{len(identities)}] {summary['entidade']:<14} "
            f"llm={summary['llm_calls']:<3} tokens={summary['tokens']:<7} "
            f"publicado={summary['publicado']}"
        )
        if not args.dry_run and index % 10 == 0:
            client.flush()

    if not args.dry_run:
        client.flush()
        print("lote final enviado ao Langfuse.")

    total_tokens = sum(item["tokens"] for item in results)
    published = len([item for item in results if item["publicado"]])
    print(
        f"\nresumo: {len(results)} execucoes | {published} publicadas | "
        f"{total_tokens} tokens de LLM"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

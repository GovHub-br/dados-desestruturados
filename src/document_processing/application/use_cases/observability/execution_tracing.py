"""Projeta uma execucao ja persistida no MinIO para um trace do Langfuse.

A observabilidade e feita como projecao de artefatos, nao como instrumentacao
espalhada pelas etapas. Uma task no fim de cada DAG le o que a execucao gravou
e emite trace, spans, generations e metricas.

Essa escolha tem tres consequencias praticas:

- a observabilidade nunca altera o caminho critico nem alarga assinaturas;
- a mesma projecao serve para execucoes novas e para backfill historico;
- se o Langfuse estiver fora, a execucao continua e apenas nao e observada.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from document_processing.domain.observability import (
    artifact_selection_quality_metrics,
    end_to_end_metrics,
    extraction_metrics,
    fallback_execution_metrics,
    fallback_stage_metrics,
    layout_validation_metrics,
    prompt_set_fingerprint,
    resolution_metrics,
    transition_metrics,
)
from document_processing.infrastructure.observability import LangfuseIngestionClient, new_id
from document_processing.infrastructure.storage.minio_artifact_repository import (
    MinioStorageClient,
)
from document_processing.shared.config.runtime import RUNTIME_CONFIG_LOADER

LOGGER = logging.getLogger(__name__)

LLM_ARTIFACT_KINDS = ("entrada_llm", "resposta_llm", "erro_llm")


class AtlasExecutionTracer:
    """Emite para o Langfuse o que uma execucao do Atlas ja gravou no MinIO."""

    def __init__(
        self,
        *,
        config_loader: Any = None,
        minio_client: MinioStorageClient | None = None,
        langfuse_client: LangfuseIngestionClient | None = None,
    ) -> None:
        self.config_loader = config_loader or RUNTIME_CONFIG_LOADER
        self._minio_client = minio_client
        self._langfuse_client = langfuse_client

    @property
    def minio_client(self) -> MinioStorageClient:
        """Cria o repositorio MinIO apenas quando ha algo para observar."""
        if self._minio_client is None:
            self._minio_client = MinioStorageClient(
                self.config_loader.load_local_platform_config()
            )
        return self._minio_client

    @property
    def langfuse_client(self) -> LangfuseIngestionClient:
        """Cria o cliente do Langfuse a partir da configuracao de runtime."""
        if self._langfuse_client is None:
            self._langfuse_client = LangfuseIngestionClient.from_config(
                self.config_loader.load_local_platform_config()
            )
        return self._langfuse_client

    # -- leitura tolerante -------------------------------------------------

    def _read_json(self, object_key: str) -> dict[str, Any]:
        """Le um artefato JSON sem quebrar a task quando ele nao existe."""
        if not object_key:
            return {}
        try:
            return dict(self.minio_client.get_json(object_key=object_key))
        except Exception:  # noqa: BLE001
            return {}

    def _list_keys(self, prefix: str) -> list[str]:
        """Lista artefatos de um prefixo, tolerando indisponibilidade."""
        try:
            return list(self.minio_client.list_object_keys(prefix=prefix))
        except Exception:  # noqa: BLE001
            return []

    @staticmethod
    def _execution_id_from_key(object_key: Any) -> str:
        """Le o execution_id do proprio caminho do artefato.

        E o id da execucao de extracao, que se mantem quando a DAG 2 e a DAG 3
        rodam de novo sobre a mesma extracao. Por isso serve de chave de
        pareamento entre releases; o id da propria rodada nao serviria.
        """
        match = re.search(r"execution_id=([^/]+)", str(object_key or ""))
        return match.group(1) if match else ""

    @staticmethod
    def _code_provenance() -> dict[str, str]:
        """Anexa a identidade do codigo ao trace, que o rotulo de release nao guarda.

        `release` e apenas a chave de agrupamento do experimento: um `-dirty` nao
        distingue uma arvore suja de outra. O commit e o estado da arvore ficam
        aqui, e observabilidade nunca pode derrubar o pipeline.
        """
        try:
            from document_processing.shared.config.release import describe_release

            descricao = describe_release(
                os.getenv("LANGFUSE_ENVIRONMENT", "development").strip().lower()
            )
        except Exception:  # noqa: BLE001
            return {}
        return {
            chave: str(descricao.get(chave, ""))
            for chave in ("commit", "branch", "arvore_suja")
            if descricao.get(chave)
        }

    @staticmethod
    def _object_key_from_uri(value: Any) -> str:
        """Converte `minio://bucket/chave` na object key usada pelo repositorio."""
        text = str(value or "").strip()
        if not text:
            return ""
        if text.startswith("minio://"):
            without_scheme = text[len("minio://") :]
            _, _, object_key = without_scheme.partition("/")
            return object_key
        return text

    @staticmethod
    def _iso(value: Any, *, fallback: datetime) -> str:
        """Normaliza timestamps de artefatos para ISO-8601 com timezone."""
        if isinstance(value, str) and value.strip():
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                return parsed.isoformat()
            except ValueError:
                pass
        return fallback.isoformat()

    # -- indexacao dos artefatos de LLM ------------------------------------

    @staticmethod
    def _index_llm_artifacts(
        keys: list[str], prefix: str
    ) -> dict[str, dict[int, dict[str, str]]]:
        """Agrupa entrada, resposta e erro de LLM por etapa e tentativa."""
        index: dict[str, dict[int, dict[str, str]]] = {}
        for key in keys:
            filename = key.split("/")[-1]
            for kind in LLM_ARTIFACT_KINDS:
                if not filename.startswith(f"{kind}_"):
                    continue
                remainder = filename[len(kind) + 1 :]
                if remainder.endswith(".json"):
                    remainder = remainder[: -len(".json")]
                attempt = 0
                match = re.search(r"_tentativa_(\d+)$", remainder)
                if match:
                    attempt = int(match.group(1))
                    remainder = remainder[: match.start()]
                relative = key[len(prefix) :]
                unit = relative.rsplit("/", 1)[0].strip("/") if "/" in relative else ""
                stage = f"{unit}/{remainder}" if unit else remainder
                index.setdefault(stage, {}).setdefault(attempt, {})[kind] = key
        return index

    # -- projecao do fallback (DAG 3) --------------------------------------

    def trace_fallback_execution(self, *, fallback_context: dict[str, Any]) -> dict[str, Any]:
        """Emite o trace de uma execucao de fallback assistido por LLM."""
        client = self.langfuse_client
        if not client.should_sample():
            return {"observado": False, "motivo": "langfuse_desabilitado_ou_amostrado"}

        try:
            return self._emit_fallback_trace(client, fallback_context)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Observabilidade do fallback falhou e foi ignorada: %s", exc)
            return {"observado": False, "erro": str(exc)}

    def _emit_fallback_trace(
        self, client: LangfuseIngestionClient, fallback_context: dict[str, Any]
    ) -> dict[str, Any]:
        """Monta trace, generations e metricas do fallback a partir do MinIO."""
        entity_slug = str(
            fallback_context.get("entity_slug") or fallback_context.get("company_slug") or ""
        ).strip()
        document_id = str(fallback_context.get("document_id") or "").strip()
        config = self.config_loader.load_local_platform_config()
        domain = str(fallback_context.get("domain") or config.dominio).strip()
        execution_id = str(
            fallback_context.get("fallback_execution_id")
            or fallback_context.get("execution_id")
            or ""
        ).strip()

        # O id da execucao de fallback muda a cada rodada, entao nao serve para
        # parear a mesma execucao entre duas releases. A chave estavel e a
        # execucao de extracao que originou o documento.
        source_execution_id = str(
            fallback_context.get("source_execution_id")
            or fallback_context.get("execution_id")
            or ""
        ).strip()

        prefix = str(fallback_context.get("fallback_prefix") or "").rstrip("/")
        if not prefix:
            if not (entity_slug and document_id and execution_id):
                return {"observado": False, "motivo": "contexto_de_fallback_incompleto"}
            prefix = (
                f"fallback/{domain}/{entity_slug}/"
                f"document_id={document_id}/execution_id={execution_id}"
            )
        prefix = f"{prefix}/"

        keys = self._list_keys(prefix)
        by_name = {key[len(prefix) :]: key for key in keys}

        candidate = self._read_json(by_name.get("layout_signature_candidato.json", ""))
        revalidation = self._read_json(
            by_name.get("revalidation/resultado_revalidacao_candidato.json", "")
        )
        revalidation_validation = self._read_json(
            by_name.get("revalidation/validacao_layout_signature.json", "")
        )
        revalidation_audit = self._read_json(
            by_name.get("revalidation/auditoria_resolucao.json", "")
        )
        publication = self._read_json(by_name.get("publicacao_layout_signature.json", ""))

        scope = candidate.get("escopo_correcao") or (
            "sem_candidato" if not candidate else "desconhecido"
        )
        started_at = datetime.now(UTC)
        trace_id = new_id()

        client.trace(
            trace_id=trace_id,
            name="atlas.fallback",
            session_id=document_id or None,
            user_id=entity_slug or None,
            input_payload={
                "dominio": domain,
                "entidade": entity_slug,
                "document_id": document_id,
                "fallback_execution_id": execution_id,
            },
            output_payload={
                "escopo_correcao": scope,
                "revalidacao": revalidation.get("status_compatibilidade"),
                "publicacao": publication.get("status"),
                "versao_publicada": publication.get("versao_publicada"),
            },
            metadata={
                "dominio": domain,
                "entidade": entity_slug,
                "document_id": document_id,
                "execution_id": source_execution_id
                or candidate.get("execution_id_origem")
                or execution_id,
                "fallback_execution_id": execution_id,
                "fallback_prefix": prefix,
                "dag": "dag_valida_e_fallback_llm",
                # Distingue projecao ao vivo de reprojecao por backfill: o conteudo
                # e o mesmo, o caminho nao, e a diferenca precisa ficar legivel.
                "origem_projecao": "execucao",
                **self._code_provenance(),
            },
            tags=[
                f"dominio:{domain}",
                f"entidade:{entity_slug}",
                "etapa:fallback",
                "dag:dag_valida_e_fallback_llm",
                f"escopo:{scope}",
            ],
        )

        stage_index = self._index_llm_artifacts(keys, prefix)
        total_attempts = 0
        total_tokens = 0
        cursor = started_at
        # started_at e o instante da projecao, que roda depois da execucao. Medir
        # contra ele da duracao negativa. O intervalo real e o que separa o
        # primeiro do ultimo artefato persistido.
        first_mark: datetime | None = None
        last_mark: datetime | None = None

        for stage, attempts in sorted(stage_index.items()):
            usages: list[dict[str, Any]] = []
            succeeded = False
            last_generation: str | None = None
            prompts_usados: list[dict[str, Any]] = []
            conjunto_prompt: str | None = None
            versao_conjunto: int | None = None
            for attempt in sorted(attempts):
                artifacts = attempts[attempt]
                request = self._read_json(artifacts.get("entrada_llm", ""))
                response = self._read_json(artifacts.get("resposta_llm", ""))
                error = self._read_json(artifacts.get("erro_llm", ""))

                api_metadata = response.get("api_response_metadata")
                usage = api_metadata.get("usage") if isinstance(api_metadata, dict) else None
                if isinstance(usage, dict):
                    usages.append(usage)
                    total_tokens += int(usage.get("total_tokens") or 0)

                start = self._iso(request.get("persistido_em"), fallback=cursor)
                end = self._iso(
                    response.get("persistido_em") or error.get("persistido_em"),
                    fallback=cursor + timedelta(seconds=1),
                )
                cursor = datetime.fromisoformat(end)
                inicio_marca = datetime.fromisoformat(start)
                first_mark = inicio_marca if first_mark is None else min(first_mark, inicio_marca)
                last_mark = cursor if last_mark is None else max(last_mark, cursor)
                total_attempts += 1
                failed = bool(error)
                if not failed:
                    succeeded = True

                options = request.get("opcoes_requisicao_llm") or {}
                # Registrado pela execucao quando o prompt veio do Langfuse; em
                # artefatos antigos o campo nao existe e nada e atribuido.
                prompts_usados = request.get("prompts_utilizados") or prompts_usados
                conjunto_prompt = request.get("prompt_conjunto") or conjunto_prompt
                versao_conjunto = (
                    request.get("prompt_conjunto_versao")
                    if request.get("prompt_conjunto_versao") is not None
                    else versao_conjunto
                )
                last_generation = client.generation(
                    trace_id=trace_id,
                    name=f"fallback.{stage}",
                    model=request.get("model"),
                    model_parameters={
                        "max_tokens": options.get("max_tokens"),
                        "thinking_mode": options.get("thinking_mode"),
                    },
                    start_time=start,
                    end_time=end,
                    input_payload=request.get("messages")
                    or {
                        "system_prompt": request.get("system_prompt"),
                        "user_payload": request.get("user_payload"),
                    },
                    output_payload=response.get("parsed_response")
                    or error.get("parsed_response"),
                    usage=usage if isinstance(usage, dict) else None,
                    level="ERROR" if failed else "DEFAULT",
                    status_message=error.get("error_message") if failed else None,
                    metadata={
                        "etapa_llm": stage,
                        "tentativa": attempt,
                        "provider": request.get("provider"),
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

            for metric in fallback_stage_metrics(
                stage=stage,
                attempts=len(attempts),
                succeeded=succeeded,
                usage_by_attempt=usages,
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
                    observation_id=last_generation,
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
                end_time=self._iso(
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

        coverage: float | None = None
        if revalidation_audit:
            for metric in resolution_metrics(revalidation_audit):
                if metric.name == "resolucao_cobertura_obrigatorios" and isinstance(
                    metric.value, (int, float)
                ):
                    coverage = float(metric.value)
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
                start_time=self._iso(publication.get("publicado_em"), fallback=cursor),
                end_time=self._iso(publication.get("publicado_em"), fallback=cursor),
                output_payload={
                    "status": publication.get("status"),
                    "versao_publicada": publication.get("versao_publicada"),
                    "published_layout_uri": publication.get("published_layout_uri"),
                },
            )

        approved = bool(revalidation.get("aprovado_para_publicacao"))
        published = str(publication.get("status") or "") == "publicado"

        for nome_artefato, chave in sorted(by_name.items()):
            if not nome_artefato.endswith("/poda_evidencia.json"):
                continue
            for metric in artifact_selection_quality_metrics(self._read_json(chave)):
                client.score(
                    trace_id=trace_id,
                    name=metric.name,
                    value=metric.value,
                    data_type=metric.data_type,
                    comment=metric.comment,
                    metadata=metric.metadata,
                )

        metrics = list(
            fallback_execution_metrics(
                scope=scope,
                candidate_valid=bool(candidate),
                revalidation=revalidation,
                revalidation_validation=revalidation_validation,
                publication=publication,
                total_llm_attempts=total_attempts,
                total_tokens=total_tokens,
            )
        )
        metrics += transition_metrics(
            origem="fallback",
            destino="resolucao",
            habilitada=approved,
            motivo=str(revalidation.get("status_compatibilidade") or ""),
        )
        metrics += end_to_end_metrics(
            sucesso=published,
            exigiu_llm=True,
            duracao_segundos=(
                (last_mark - first_mark).total_seconds()
                if first_mark is not None and last_mark is not None
                else None
            ),
            tokens_totais=total_tokens,
            cobertura_final=coverage,
            apto_para_bronze=approved,
        )
        for metric in metrics:
            client.score(
                trace_id=trace_id,
                name=metric.name,
                value=metric.value,
                data_type=metric.data_type,
                comment=metric.comment,
                metadata=metric.metadata,
            )

        client.flush()
        return {
            "observado": True,
            "trace_id": trace_id,
            "release": client.release,
            "environment": client.environment,
            "chamadas_llm": total_attempts,
            "tokens": total_tokens,
        }

    # -- projecao da resolucao (DAG 2) -------------------------------------

    def trace_resolution_execution(
        self, *, resolution_result: dict[str, Any]
    ) -> dict[str, Any]:
        """Emite o trace de uma execucao de resolucao deterministica."""
        client = self.langfuse_client
        if not client.should_sample():
            return {"observado": False, "motivo": "langfuse_desabilitado_ou_amostrado"}
        try:
            return self._emit_resolution_trace(client, resolution_result)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Observabilidade da resolucao falhou e foi ignorada: %s", exc)
            return {"observado": False, "erro": str(exc)}

    def _emit_resolution_trace(
        self, client: LangfuseIngestionClient, resolution_result: dict[str, Any]
    ) -> dict[str, Any]:
        """Monta trace e metricas da DAG 2 a partir dos artefatos gravados."""
        persisted = resolution_result.get("persisted")
        persisted = persisted if isinstance(persisted, dict) else {}
        object_keys = {
            "validacao_layout_signature": self._object_key_from_uri(
                persisted.get("validacao_layout_signature_uri")
            ),
            "auditoria_resolucao": self._object_key_from_uri(
                persisted.get("auditoria_resolucao_uri")
            ),
            "schema_saida_resolvido": self._object_key_from_uri(
                persisted.get("schema_saida_resolvido_uri")
            ),
            "manifesto_execucao": str(resolution_result.get("manifest_key") or ""),
        }

        validation = self._read_json(object_keys["validacao_layout_signature"])
        audit = self._read_json(object_keys["auditoria_resolucao"])
        manifest = self._read_json(object_keys["manifesto_execucao"])

        entity_slug = str(
            resolution_result.get("entity_slug")
            or resolution_result.get("company_slug")
            or ""
        )
        document_id = str(resolution_result.get("document_id") or "")
        domain = str(resolution_result.get("domain") or "")
        execution_mode = str(resolution_result.get("modo_execucao") or "resolucao")
        execution_id = str(
            resolution_result.get("execution_id") or ""
        ).strip() or self._execution_id_from_key(object_keys["manifesto_execucao"])

        started_at = datetime.now(UTC)
        trace_id = new_id()
        status = str(resolution_result.get("status_compatibilidade") or "desconhecido")
        fallback_needed = status != "compativel"

        client.trace(
            trace_id=trace_id,
            name="atlas.resolucao",
            session_id=document_id or None,
            user_id=entity_slug or None,
            input_payload={
                "dominio": domain,
                "entidade": entity_slug,
                "document_id": document_id,
                "modo_execucao": execution_mode,
                "contrato_semantico_uri": resolution_result.get("contrato_semantico_uri"),
            },
            output_payload={
                "status_compatibilidade": status,
                "object_keys": object_keys,
            },
            metadata={
                "dominio": domain,
                "entidade": entity_slug,
                "document_id": document_id,
                "execution_id": execution_id,
                "dag": "dag_resolve_schema_saida",
                "modo_execucao": execution_mode,
                "origem_projecao": "execucao",
                **self._code_provenance(),
            },
            tags=[
                f"dominio:{domain}",
                f"entidade:{entity_slug}",
                "etapa:resolucao",
                "dag:dag_resolve_schema_saida",
                f"modo:{execution_mode}",
            ],
        )

        validation_span = client.span(
            trace_id=trace_id,
            name="resolucao.validacao_regras",
            start_time=started_at.isoformat(),
            end_time=self._iso(validation.get("executado_em"), fallback=started_at),
            output_payload=validation.get("status_compatibilidade"),
        )
        resolution_span = client.span(
            trace_id=trace_id,
            name="resolucao.mapeamento_canonico",
            start_time=self._iso(validation.get("executado_em"), fallback=started_at),
            end_time=datetime.now(UTC).isoformat(),
            output_payload={"campos": len(audit.get("auditoria_resolucao") or [])},
        )

        coverage: float | None = None
        for metric in layout_validation_metrics(validation):
            client.score(
                trace_id=trace_id,
                name=metric.name,
                value=metric.value,
                observation_id=validation_span,
                data_type=metric.data_type,
                comment=metric.comment,
                metadata=metric.metadata,
            )
        for metric in resolution_metrics(audit):
            if metric.name == "resolucao_cobertura_obrigatorios" and isinstance(
                metric.value, (int, float)
            ):
                coverage = float(metric.value)
            client.score(
                trace_id=trace_id,
                name=metric.name,
                value=metric.value,
                observation_id=resolution_span,
                data_type=metric.data_type,
                comment=metric.comment,
                metadata=metric.metadata,
            )
        if manifest:
            for metric in extraction_metrics(manifest):
                client.score(
                    trace_id=trace_id,
                    name=metric.name,
                    value=metric.value,
                    data_type=metric.data_type,
                    comment=metric.comment,
                    metadata=metric.metadata,
                )

        metrics = transition_metrics(
            origem="extracao",
            destino="resolucao",
            habilitada=bool(audit),
            motivo=None if audit else "auditoria_de_resolucao_ausente",
        )
        metrics += transition_metrics(
            origem="resolucao",
            destino="fallback",
            habilitada=fallback_needed,
            motivo=status,
        )
        metrics += transition_metrics(
            origem="resolucao",
            destino="bronze",
            habilitada=not fallback_needed,
            motivo=status,
        )
        metrics += end_to_end_metrics(
            sucesso=not fallback_needed,
            exigiu_llm=execution_mode == "revalidacao_layout_candidato",
            # A resolucao nao persiste marco de inicio, so de conclusao. Medir
            # daqui mediria a propria projecao; emitir 0 seria pior, porque
            # "nao aplicavel" viraria "instantaneo" na media.
            duracao_segundos=None,
            cobertura_final=coverage,
            apto_para_bronze=not fallback_needed,
        )
        for metric in metrics:
            client.score(
                trace_id=trace_id,
                name=metric.name,
                value=metric.value,
                data_type=metric.data_type,
                comment=metric.comment,
                metadata=metric.metadata,
            )

        client.flush()
        return {
            "observado": True,
            "trace_id": trace_id,
            "release": client.release,
            "environment": client.environment,
            "status_compatibilidade": status,
        }


ATLAS_EXECUTION_TRACER = AtlasExecutionTracer()

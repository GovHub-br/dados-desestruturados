"""Cliente de ingestao do Langfuse baseado apenas na biblioteca padrao.

O cliente fala diretamente com `POST /api/public/ingestion`, que aceita um lote
de eventos (`trace-create`, `span-create`, `generation-create`, `score-create`).
Nenhuma dependencia nova entra no runtime das DAGs por causa disso.

A observabilidade nunca pode derrubar o pipeline: qualquer falha de rede,
credencial ou serializacao vira aviso silencioso e o fluxo continua.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import random
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

LOGGER = logging.getLogger(__name__)

MAX_SERIALIZED_FIELD_CHARS = 200_000


def _now() -> str:
    """Timestamp ISO-8601 em UTC, formato aceito pela API de ingestao."""
    return datetime.now(UTC).isoformat()


def new_id() -> str:
    """Identificador estavel para traces, spans e generations."""
    return uuid.uuid4().hex


def _truncate(value: Any) -> Any:
    """Evita enviar artefatos gigantes do MinIO inteiros para o Langfuse."""
    if value is None:
        return None
    try:
        serialized = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return {"_nao_serializavel": str(type(value))}
    if len(serialized) <= MAX_SERIALIZED_FIELD_CHARS:
        return value
    return {
        "_truncado": True,
        "_tamanho_original_caracteres": len(serialized),
        "_amostra": serialized[:MAX_SERIALIZED_FIELD_CHARS],
    }


class LangfuseIngestionClient:
    """Acumula eventos e envia em lote para o Langfuse."""

    def __init__(
        self,
        *,
        base_url: str,
        public_key: str,
        secret_key: str,
        environment: str = "development",
        release: str = "local-dev",
        timeout_seconds: int = 10,
        sample_rate: float = 1.0,
        enabled: bool = True,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.public_key = public_key or ""
        self.secret_key = secret_key or ""
        self.environment = environment or "development"
        self.release = release or "local-dev"
        self.timeout_seconds = timeout_seconds
        self.sample_rate = sample_rate
        self.enabled = bool(enabled and self.base_url and self.public_key and self.secret_key)
        self._events: list[dict[str, Any]] = []

    @classmethod
    def from_config(cls, config: Any) -> "LangfuseIngestionClient":
        """Constroi o cliente a partir do `LocalPlatformConfig` do projeto."""
        return cls(
            base_url=getattr(config, "langfuse_base_url", ""),
            public_key=getattr(config, "langfuse_public_key", ""),
            secret_key=getattr(config, "langfuse_secret_key", ""),
            environment=getattr(config, "langfuse_environment", "development"),
            release=getattr(config, "langfuse_release", "local-dev"),
            timeout_seconds=getattr(config, "langfuse_timeout_seconds", 10),
            sample_rate=getattr(config, "langfuse_sample_rate", 1.0),
            enabled=getattr(config, "langfuse_enabled", False),
        )

    @classmethod
    def from_environment(cls) -> "LangfuseIngestionClient":
        """Constroi o cliente direto do ambiente, util para scripts e backfill."""
        base_url = os.getenv("LANGFUSE_BASE_URL", "").strip().rstrip("/")
        public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
        secret_key = os.getenv("LANGFUSE_SECRET_KEY", "").strip()
        return cls(
            base_url=base_url,
            public_key=public_key,
            secret_key=secret_key,
            environment=os.getenv("LANGFUSE_ENVIRONMENT", "development").strip().lower(),
            release=(
                os.getenv("ATLAS_RELEASE", "").strip()
                or os.getenv("LANGFUSE_RELEASE", "").strip()
                or "local-dev"
            ),
            timeout_seconds=int(os.getenv("LANGFUSE_TIMEOUT_SECONDS", "10") or 10),
            enabled=bool(base_url and public_key and secret_key),
        )

    def should_sample(self) -> bool:
        """Decide se uma nova execucao deve ser rastreada."""
        if not self.enabled:
            return False
        if self.sample_rate >= 1.0:
            return True
        return random.random() < self.sample_rate

    def trace(
        self,
        *,
        trace_id: str,
        name: str,
        user_id: str | None = None,
        session_id: str | None = None,
        input_payload: Any = None,
        output_payload: Any = None,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        timestamp: str | None = None,
    ) -> str:
        """Registra a raiz de uma execucao do Atlas."""
        body: dict[str, Any] = {
            "id": trace_id,
            "name": name,
            "timestamp": timestamp or _now(),
            "environment": self.environment,
            "release": self.release,
            "version": self.release,
            "metadata": metadata or {},
            "tags": sorted(set(tags or [])),
        }
        if user_id:
            body["userId"] = user_id
        if session_id:
            body["sessionId"] = session_id
        if input_payload is not None:
            body["input"] = _truncate(input_payload)
        if output_payload is not None:
            body["output"] = _truncate(output_payload)
        self._append("trace-create", body)
        return trace_id

    def span(
        self,
        *,
        trace_id: str,
        name: str,
        span_id: str | None = None,
        parent_observation_id: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        input_payload: Any = None,
        output_payload: Any = None,
        metadata: dict[str, Any] | None = None,
        level: str = "DEFAULT",
        status_message: str | None = None,
    ) -> str:
        """Registra uma etapa deterministica do fluxo."""
        observation_id = span_id or new_id()
        body: dict[str, Any] = {
            "id": observation_id,
            "traceId": trace_id,
            "name": name,
            "startTime": start_time or _now(),
            "endTime": end_time or _now(),
            "environment": self.environment,
            "version": self.release,
            "metadata": metadata or {},
            "level": level,
        }
        if parent_observation_id:
            body["parentObservationId"] = parent_observation_id
        if input_payload is not None:
            body["input"] = _truncate(input_payload)
        if output_payload is not None:
            body["output"] = _truncate(output_payload)
        if status_message:
            body["statusMessage"] = status_message[:2000]
        self._append("span-create", body)
        return observation_id

    def generation(
        self,
        *,
        trace_id: str,
        name: str,
        generation_id: str | None = None,
        parent_observation_id: str | None = None,
        model: str | None = None,
        model_parameters: dict[str, Any] | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        completion_start_time: str | None = None,
        input_payload: Any = None,
        output_payload: Any = None,
        usage: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        level: str = "DEFAULT",
        status_message: str | None = None,
        prompt_name: str | None = None,
        prompt_version: int | None = None,
    ) -> str:
        """Registra uma chamada de LLM com uso de tokens quando disponivel.

        `prompt_name` e `prompt_version` ligam a chamada ao prompt versionado. E
        esse vinculo que habilita as dimensoes `observationPromptName` e
        `observationPromptVersion` nos paineis, permitindo comparar o resultado
        de uma etapa entre versoes de prompt sem cruzar dados na mao.
        """
        observation_id = generation_id or new_id()
        body: dict[str, Any] = {
            "id": observation_id,
            "traceId": trace_id,
            "name": name,
            "startTime": start_time or _now(),
            "endTime": end_time or _now(),
            "environment": self.environment,
            "version": self.release,
            "metadata": metadata or {},
            "level": level,
        }
        if parent_observation_id:
            body["parentObservationId"] = parent_observation_id
        if model:
            body["model"] = model
        if model_parameters:
            body["modelParameters"] = {
                key: value for key, value in model_parameters.items() if value is not None
            }
        if completion_start_time:
            body["completionStartTime"] = completion_start_time
        if input_payload is not None:
            body["input"] = _truncate(input_payload)
        if output_payload is not None:
            body["output"] = _truncate(output_payload)
        normalized_usage = self._normalize_usage(usage)
        if normalized_usage:
            body["usageDetails"] = normalized_usage
        if status_message:
            body["statusMessage"] = status_message[:2000]
        # O Langfuse so aceita o vinculo com os dois campos presentes; enviar so
        # o nome deixaria a observation orfa de versao e nao apareceria no corte.
        if prompt_name and prompt_version is not None:
            body["promptName"] = prompt_name
            body["promptVersion"] = prompt_version
        self._append("generation-create", body)
        return observation_id

    def score(
        self,
        *,
        trace_id: str,
        name: str,
        value: float | str,
        observation_id: str | None = None,
        data_type: str | None = None,
        comment: str | None = None,
        score_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Registra uma metrica avaliada do fluxo, numerica ou categorica."""
        identifier = score_id or new_id()
        body: dict[str, Any] = {
            "id": identifier,
            "traceId": trace_id,
            "name": name,
            "value": value,
            "environment": self.environment,
        }
        if observation_id:
            body["observationId"] = observation_id
        if data_type:
            body["dataType"] = data_type
        elif isinstance(value, str):
            body["dataType"] = "CATEGORICAL"
        if comment:
            body["comment"] = comment[:2000]
        if metadata:
            body["metadata"] = metadata
        self._append("score-create", body)
        return identifier

    @staticmethod
    def _normalize_usage(usage: dict[str, Any] | None) -> dict[str, int]:
        """Traduz o `usage` do provedor para o formato de tokens do Langfuse."""
        if not isinstance(usage, dict):
            return {}
        mapping = {
            "prompt_tokens": "input",
            "completion_tokens": "output",
            "total_tokens": "total",
            "prompt_cache_hit_tokens": "input_cached",
            "prompt_cache_miss_tokens": "input_uncached",
        }
        normalized: dict[str, int] = {}
        for source_key, target_key in mapping.items():
            raw = usage.get(source_key)
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                continue
            normalized[target_key] = int(raw)
        return normalized

    def _append(self, event_type: str, body: dict[str, Any]) -> None:
        """Enfileira um evento de ingestao."""
        if not self.enabled:
            return
        self._events.append(
            {
                "id": new_id(),
                "type": event_type,
                "timestamp": _now(),
                "body": body,
            }
        )

    def flush(self) -> bool:
        """Envia o lote acumulado; nunca propaga erro para o pipeline."""
        if not self.enabled or not self._events:
            self._events = []
            return True
        pending, self._events = self._events, []
        ok = True
        for chunk_start in range(0, len(pending), 50):
            chunk = pending[chunk_start : chunk_start + 50]
            ok = self._post_batch(chunk) and ok
        return ok

    def _post_batch(self, batch: list[dict[str, Any]]) -> bool:
        """Executa o POST de ingestao de um lote."""
        url = f"{self.base_url}/api/public/ingestion"
        credentials = base64.b64encode(
            f"{self.public_key}:{self.secret_key}".encode()
        ).decode()
        try:
            data = json.dumps({"batch": batch}, ensure_ascii=False, default=str).encode()
        except (TypeError, ValueError) as exc:
            LOGGER.warning("Langfuse: lote nao serializavel, descartado: %s", exc)
            return False
        request = Request(
            url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Basic {credentials}",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode() or "{}")
        except HTTPError as exc:
            LOGGER.warning(
                "Langfuse: ingestao rejeitada com HTTP %s: %s",
                exc.code,
                exc.read().decode(errors="replace")[:500],
            )
            return False
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            LOGGER.warning("Langfuse: ingestao indisponivel: %s", exc)
            return False
        errors = payload.get("errors") or []
        if errors:
            LOGGER.warning("Langfuse: %s evento(s) rejeitado(s): %s", len(errors), errors[:3])
            return False
        return True

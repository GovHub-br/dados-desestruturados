from __future__ import annotations

import json
from typing import Any

from helpers import RUNTIME_CONFIG_LOADER, RuntimeConfigLoader
from plugins.clients.http_client import HTTP_CLIENT, HttpClient


class FallbackLlmClientError(RuntimeError):
    """Erro padronizado para falhas de configuracao ou resposta da LLM."""

    def __init__(
        self,
        message: str,
        *,
        raw_content: str | None = None,
        response_metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.raw_content = raw_content
        self.response_metadata = response_metadata


class FallbackLlmClient:
    """Cliente LLM do fallback, compativel com OpenAI Chat Completions e Ollama."""

    def __init__(
        self,
        *,
        config_loader: RuntimeConfigLoader | None = None,
        http_client: HttpClient | None = None,
    ) -> None:
        self.config_loader = config_loader or RUNTIME_CONFIG_LOADER
        self.http_client = http_client or HTTP_CLIENT
        # A orquestracao persiste este resumo junto da resposta aceita. Em erros,
        # os metadados continuam no proprio FallbackLlmClientError.
        self.last_response_metadata: dict[str, Any] | None = None

    def generate_json(
        self,
        *,
        system_prompt: str | None = None,
        user_payload: dict[str, Any] | None = None,
        messages: list[dict[str, str]] | None = None,
        response_schema: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        thinking_mode: str | None = None,
    ) -> tuple[dict[str, Any], str]:
        """Chama a LLM configurada e exige que o conteudo retornado seja JSON object."""
        self.last_response_metadata = None
        chat_messages = self._build_chat_messages(
            system_prompt=system_prompt,
            user_payload=user_payload,
            messages=messages,
        )
        config = self.config_loader.load_local_platform_config()
        effective_max_tokens = max_tokens or config.fallback_llm_max_tokens
        effective_thinking_mode = (
            thinking_mode
            if thinking_mode is not None
            else getattr(config, "fallback_llm_thinking_mode", "")
        )
        provider = config.fallback_llm_provider
        if provider == "openai":
            raw = self._call_openai_compatible(
                api_url=config.fallback_llm_api_url or "https://api.openai.com/v1",
                api_key=config.fallback_llm_api_key,
                model=config.fallback_llm_model,
                messages=chat_messages,
                timeout=config.fallback_llm_timeout_seconds,
                max_tokens=effective_max_tokens,
                thinking_mode=effective_thinking_mode,
                response_schema=response_schema,
            )
            response_metadata = self._openai_response_metadata(raw)
            self.last_response_metadata = response_metadata
            content = self._extract_openai_content(raw, response_metadata=response_metadata)
            return self._parse_json_with_metadata(content, response_metadata), content

        if provider == "ollama":
            raw = self._call_ollama(
                api_url=config.fallback_llm_api_url or "http://ollama:11434",
                model=config.fallback_llm_model,
                messages=chat_messages,
                timeout=config.fallback_llm_timeout_seconds,
                max_tokens=effective_max_tokens,
                response_schema=response_schema,
            )
            response_metadata = self._ollama_response_metadata(raw)
            self.last_response_metadata = response_metadata
            content = self._extract_ollama_content(raw, response_metadata=response_metadata)
            return self._parse_json_with_metadata(content, response_metadata), content

        raise FallbackLlmClientError(
            "FALLBACK_LLM_PROVIDER invalido. Use 'openai' ou 'ollama'."
        )

    def _call_openai_compatible(
        self,
        *,
        api_url: str,
        api_key: str,
        model: str,
        messages: list[dict[str, str]],
        timeout: int,
        max_tokens: int,
        thinking_mode: str,
        response_schema: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Chama endpoint compativel com OpenAI Chat Completions."""
        if not model:
            raise FallbackLlmClientError(
                "FALLBACK_LLM_MODEL e obrigatorio para provider openai."
            )
        if not api_key:
            raise FallbackLlmClientError(
                "FALLBACK_LLM_API_KEY e obrigatorio para provider openai."
            )

        url = api_url.rstrip("/")
        if not url.endswith("/chat/completions"):
            url = (
                f"{url}/chat/completions"
                if url.endswith("/v1")
                else f"{url}/v1/chat/completions"
            )

        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        if thinking_mode:
            if thinking_mode not in {"enabled", "disabled"}:
                raise FallbackLlmClientError(
                    "Modo thinking invalido. Use 'enabled', 'disabled' ou deixe vazio."
                )
            payload["thinking"] = {"type": thinking_mode}
        try:
            return self.http_client.post_json(
                url,
                payload,
                timeout=timeout,
                headers={"Authorization": f"Bearer {api_key}"},
            )
        except RuntimeError as exc:
            raise FallbackLlmClientError(str(exc)) from exc

    def _call_ollama(
        self,
        *,
        api_url: str,
        model: str,
        messages: list[dict[str, str]],
        timeout: int,
        max_tokens: int,
        response_schema: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Chama Ollama local/remoto usando `/api/chat` com resposta JSON."""
        if not model:
            raise FallbackLlmClientError(
                "FALLBACK_LLM_MODEL e obrigatorio para provider ollama."
            )

        url = api_url.rstrip("/")
        if not url.endswith("/api/chat"):
            url = f"{url}/api/chat"

        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "format": response_schema or "json",
            "options": {
                "temperature": 0,
                "num_predict": max_tokens,
            },
        }
        try:
            return self.http_client.post_json(url, payload, timeout=timeout)
        except RuntimeError as exc:
            raise FallbackLlmClientError(str(exc)) from exc

    @staticmethod
    def _build_chat_messages(
        *,
        system_prompt: str | None,
        user_payload: dict[str, Any] | None,
        messages: list[dict[str, str]] | None,
    ) -> list[dict[str, str]]:
        """Normaliza chamadas legadas e chamadas com contexto instrucional distribuido."""
        if messages is not None:
            if system_prompt is not None or user_payload is not None:
                raise FallbackLlmClientError(
                    "Use messages ou system_prompt/user_payload, nunca os dois formatos."
                )
            normalized: list[dict[str, str]] = []
            for message in messages:
                role = str(message.get("role", "")).strip()
                content = message.get("content")
                if role not in {"system", "user"} or not isinstance(content, str) or not content.strip():
                    raise FallbackLlmClientError(
                        "Cada mensagem LLM deve ter role system/user e conteudo textual."
                    )
                normalized.append({"role": role, "content": content})
            if not normalized:
                raise FallbackLlmClientError("Lista de mensagens LLM nao pode ser vazia.")
            return normalized

        if not isinstance(system_prompt, str) or not system_prompt.strip():
            raise FallbackLlmClientError("system_prompt e obrigatorio na chamada legada.")
        if not isinstance(user_payload, dict):
            raise FallbackLlmClientError("user_payload deve ser um objeto na chamada legada.")
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ]

    @staticmethod
    def _extract_openai_content(
        payload: dict[str, Any],
        *,
        response_metadata: dict[str, Any] | None = None,
    ) -> str:
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise FallbackLlmClientError(
                "Resposta OpenAI sem choices[0].message.content.",
                response_metadata=response_metadata,
            ) from exc
        return FallbackLlmClient._required_text_content(
            content,
            response_metadata=response_metadata,
        )

    @staticmethod
    def _extract_ollama_content(
        payload: dict[str, Any],
        *,
        response_metadata: dict[str, Any] | None = None,
    ) -> str:
        message = payload.get("message")
        if isinstance(message, dict):
            return FallbackLlmClient._required_text_content(
                message.get("content"),
                response_metadata=response_metadata,
            )
        return FallbackLlmClient._required_text_content(
            payload.get("response"),
            response_metadata=response_metadata,
        )

    @staticmethod
    def _required_text_content(
        content: Any,
        *,
        response_metadata: dict[str, Any] | None = None,
    ) -> str:
        if not isinstance(content, str) or not content.strip():
            raise FallbackLlmClientError(
                "LLM retornou conteudo textual vazio.",
                response_metadata=response_metadata,
            )
        return content.strip()

    @staticmethod
    def _parse_json_content(content: str) -> dict[str, Any]:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise FallbackLlmClientError(
                "Conteudo da LLM nao e JSON valido.",
                raw_content=content,
            ) from exc
        if not isinstance(parsed, dict):
            raise FallbackLlmClientError(
                "Conteudo JSON da LLM deve ser um objeto.",
                raw_content=content,
            )
        return parsed

    @staticmethod
    def _parse_json_with_metadata(
        content: str,
        response_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Propaga os metadados do envelope quando a resposta textual nao for JSON."""
        try:
            return FallbackLlmClient._parse_json_content(content)
        except FallbackLlmClientError as exc:
            exc.response_metadata = response_metadata
            raise

    @staticmethod
    def _openai_response_metadata(payload: dict[str, Any]) -> dict[str, Any]:
        """Resume e preserva, de forma sanitizada, a resposta OpenAI compativel."""
        choice = payload.get("choices", [None])
        first_choice = choice[0] if isinstance(choice, list) and choice else {}
        if not isinstance(first_choice, dict):
            first_choice = {}
        message = first_choice.get("message", {})
        if not isinstance(message, dict):
            message = {}
        content = message.get("content")
        reasoning = message.get("reasoning_content")
        return {
            "provider": "openai_compatible",
            "finish_reason": first_choice.get("finish_reason"),
            "usage": payload.get("usage"),
            "content_presente": isinstance(content, str) and bool(content.strip()),
            "content_caracteres": len(content) if isinstance(content, str) else 0,
            "reasoning_content_presente": isinstance(reasoning, str) and bool(reasoning.strip()),
            "reasoning_content_caracteres": len(reasoning) if isinstance(reasoning, str) else 0,
            "envelope_sanitizado": FallbackLlmClient._sanitize_api_envelope(payload),
        }

    @staticmethod
    def _ollama_response_metadata(payload: dict[str, Any]) -> dict[str, Any]:
        """Mantem observabilidade equivalente para respostas do Ollama."""
        message = payload.get("message", {})
        content = message.get("content") if isinstance(message, dict) else payload.get("response")
        return {
            "provider": "ollama",
            "finish_reason": payload.get("done_reason"),
            "usage": {
                "prompt_eval_count": payload.get("prompt_eval_count"),
                "eval_count": payload.get("eval_count"),
            },
            "content_presente": isinstance(content, str) and bool(content.strip()),
            "content_caracteres": len(content) if isinstance(content, str) else 0,
            "envelope_sanitizado": FallbackLlmClient._sanitize_api_envelope(payload),
        }

    @staticmethod
    def _sanitize_api_envelope(value: Any) -> Any:
        """Remove segredos caso um provedor os replique no corpo da resposta."""
        sensitive_terms = ("api_key", "authorization", "token", "password", "secret")
        if isinstance(value, dict):
            sanitized: dict[str, Any] = {}
            for key, item in value.items():
                normalized_key = str(key).lower()
                sanitized[str(key)] = (
                    "<redigido>"
                    if any(term in normalized_key for term in sensitive_terms)
                    else FallbackLlmClient._sanitize_api_envelope(item)
                )
            return sanitized
        if isinstance(value, list):
            return [FallbackLlmClient._sanitize_api_envelope(item) for item in value]
        return value


FALLBACK_LLM_CLIENT = FallbackLlmClient()

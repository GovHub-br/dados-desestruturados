from __future__ import annotations

import json
from typing import Any

from helpers import RUNTIME_CONFIG_LOADER, RuntimeConfigLoader
from plugins.clients.http_client import HTTP_CLIENT, HttpClient


class FallbackLlmClientError(RuntimeError):
    """Erro padronizado para falhas de configuracao ou resposta da LLM."""


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

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        response_schema: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str]:
        """Chama a LLM configurada e exige que o conteudo retornado seja JSON object."""
        config = self.config_loader.load_local_platform_config()
        provider = config.fallback_llm_provider
        if provider == "openai":
            raw = self._call_openai_compatible(
                api_url=config.fallback_llm_api_url or "https://api.openai.com/v1",
                api_key=config.fallback_llm_api_key,
                model=config.fallback_llm_model,
                system_prompt=system_prompt,
                user_payload=user_payload,
                timeout=config.fallback_llm_timeout_seconds,
                max_tokens=config.fallback_llm_max_tokens,
                response_schema=response_schema,
            )
            content = self._extract_openai_content(raw)
            return self._parse_json_content(content), content

        if provider == "ollama":
            raw = self._call_ollama(
                api_url=config.fallback_llm_api_url or "http://ollama:11434",
                model=config.fallback_llm_model,
                system_prompt=system_prompt,
                user_payload=user_payload,
                timeout=config.fallback_llm_timeout_seconds,
                max_tokens=config.fallback_llm_max_tokens,
                response_schema=response_schema,
            )
            content = self._extract_ollama_content(raw)
            return self._parse_json_content(content), content

        raise FallbackLlmClientError(
            "FALLBACK_LLM_PROVIDER invalido. Use 'openai' ou 'ollama'."
        )

    def _call_openai_compatible(
        self,
        *,
        api_url: str,
        api_key: str,
        model: str,
        system_prompt: str,
        user_payload: dict[str, Any],
        timeout: int,
        max_tokens: int,
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
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            "temperature": 0,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
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
        system_prompt: str,
        user_payload: dict[str, Any],
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
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
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
    def _extract_openai_content(payload: dict[str, Any]) -> str:
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise FallbackLlmClientError(
                "Resposta OpenAI sem choices[0].message.content."
            ) from exc
        return FallbackLlmClient._required_text_content(content)

    @staticmethod
    def _extract_ollama_content(payload: dict[str, Any]) -> str:
        message = payload.get("message")
        if isinstance(message, dict):
            return FallbackLlmClient._required_text_content(message.get("content"))
        return FallbackLlmClient._required_text_content(payload.get("response"))

    @staticmethod
    def _required_text_content(content: Any) -> str:
        if not isinstance(content, str) or not content.strip():
            raise FallbackLlmClientError("LLM retornou conteudo textual vazio.")
        return content.strip()

    @staticmethod
    def _parse_json_content(content: str) -> dict[str, Any]:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise FallbackLlmClientError("Conteudo da LLM nao e JSON valido.") from exc
        if not isinstance(parsed, dict):
            raise FallbackLlmClientError("Conteudo JSON da LLM deve ser um objeto.")
        return parsed


FALLBACK_LLM_CLIENT = FallbackLlmClient()

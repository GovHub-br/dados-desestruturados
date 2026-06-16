from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..config import RuntimeConfig


class LlmClientError(RuntimeError):
    pass


class OpenAICompatibleLlmClient:
    def __init__(self, config: RuntimeConfig) -> None:
        if not config.llm_api_url:
            raise ValueError("llm_api_url is required")
        if not config.llm_api_model:
            raise ValueError("llm_api_model is required")
        self.api_url = config.llm_api_url.rstrip("/")
        self.api_key = config.llm_api_key
        self.model = config.llm_api_model
        self.timeout = config.llm_timeout
        self.max_tokens = config.llm_max_tokens

    def extract_json(self, *, system_prompt: str, user_payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
        }
        raw = self._post_chat_completions(payload)
        content = self._extract_message_content(raw)
        return self._parse_json_content(content), content

    def _post_chat_completions(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = self.api_url
        if not url.endswith("/chat/completions"):
            url = f"{url}/v1/chat/completions"
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(url, data=data, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LlmClientError(f"LLM API HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise LlmClientError(f"LLM API connection failed: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise LlmClientError("LLM API returned invalid JSON response") from exc

    @staticmethod
    def _extract_message_content(payload: dict[str, Any]) -> str:
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LlmClientError("LLM API response did not include choices[0].message.content") from exc
        if not isinstance(content, str) or not content.strip():
            raise LlmClientError("LLM API returned empty message content")
        return content.strip()

    @staticmethod
    def _parse_json_content(content: str) -> dict[str, Any]:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LlmClientError("LLM message content is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise LlmClientError("LLM message content must be a JSON object")
        return parsed


def build_llm_client(config: RuntimeConfig) -> OpenAICompatibleLlmClient:
    return OpenAICompatibleLlmClient(config)

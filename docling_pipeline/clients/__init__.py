from __future__ import annotations

from .llm_client import LlmClientError, build_llm_client


def build_standard_converter(*args, **kwargs):
    from .converter_client import build_standard_converter as _build_standard_converter

    return _build_standard_converter(*args, **kwargs)


def build_remote_vlm_converter(*args, **kwargs):
    from .converter_client import build_remote_vlm_converter as _build_remote_vlm_converter

    return _build_remote_vlm_converter(*args, **kwargs)


__all__ = ["LlmClientError", "build_llm_client", "build_remote_vlm_converter", "build_standard_converter"]

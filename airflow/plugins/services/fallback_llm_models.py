from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


FallbackCorrectionScope = Literal[
    "correcao_parcial_mapeamento",
    "regeneracao_total_mapeamento",
]


class BaseLayoutSignatureRef(BaseModel):
    """Referencia imutavel ao layout vigente usado como base do candidato."""

    model_config = ConfigDict(extra="forbid")

    versao: str | None = None
    object_key: str

    @field_validator("object_key")
    @classmethod
    def _object_key_not_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("object_key do layout base nao pode ser vazio")
        return cleaned


class LayoutSignatureCandidate(BaseModel):
    """Contrato aceito para o layout signature candidato gerado pela LLM."""

    model_config = ConfigDict(extra="forbid")

    tipo_artefato: Literal["layout_signature_candidato"]
    status_layout: Literal["candidato"]
    escopo_correcao: FallbackCorrectionScope
    document_id: str
    execution_id_origem: str
    base_layout_signature: BaseLayoutSignatureRef
    fontes_relevantes: dict[str, Any] = Field(default_factory=dict)
    regras_deteccao_mudanca: list[dict[str, Any]] = Field(default_factory=list)
    mapeamento_canonico: dict[str, dict[str, Any]] = Field(default_factory=dict)
    metadados_estruturais_evidencia: dict[str, Any] = Field(default_factory=dict)
    publicacao_automatica_habilitada: bool = True

    @field_validator("document_id", "execution_id_origem")
    @classmethod
    def _not_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("campo obrigatorio vazio")
        return cleaned

    @field_validator("mapeamento_canonico")
    @classmethod
    def _must_have_mapping(
        cls,
        value: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        if not value:
            raise ValueError("mapeamento_canonico deve conter pelo menos um campo")
        return value

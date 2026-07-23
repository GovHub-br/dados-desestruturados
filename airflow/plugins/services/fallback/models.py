from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


FallbackCorrectionScope = Literal[
    "correcao_parcial_mapeamento",
    "regeneracao_total_mapeamento",
    "criacao_inicial_layout",
]

SupportedMappingOrigin = Literal[
    "valor_fixo",
    "campo_derivado",
    "bloco_textual",
    "cabecalho_de_tabela",
    "celula_de_tabela",
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


class CanonicalMappingEntry(BaseModel):
    """Instrucao de origem aceita pelo resolvedor deterministico da DAG 2."""

    model_config = ConfigDict(extra="allow")

    tipo_origem: SupportedMappingOrigin
    arquivo_origem: str | None = None
    obrigatorio: bool = False


class LayoutSignatureCandidate(BaseModel):
    """Contrato aceito para o layout signature candidato gerado pela LLM."""

    model_config = ConfigDict(extra="allow")

    tipo_artefato: Literal["layout_signature_candidato"]
    status_layout: Literal["candidato"]
    escopo_correcao: FallbackCorrectionScope
    document_id: str
    execution_id_origem: str
    base_layout_signature: BaseLayoutSignatureRef | None = None
    fontes_relevantes: dict[str, Any] = Field(default_factory=dict)
    regras_deteccao_mudanca: list[dict[str, Any]] = Field(default_factory=list)
    mapeamento_canonico: dict[str, CanonicalMappingEntry] = Field(default_factory=dict)
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
        value: dict[str, CanonicalMappingEntry],
    ) -> dict[str, CanonicalMappingEntry]:
        if not value:
            raise ValueError("mapeamento_canonico deve conter pelo menos um campo")
        return value


class ArtifactSelectionItem(BaseModel):
    """Um artefato da extracao escolhido pela LLM para explorar."""

    model_config = ConfigDict(extra="forbid")

    path: str
    motivo: str
    coberturas: list["ArtifactSelectionCoverage"] = Field(min_length=1)

    @field_validator("path", "motivo")
    @classmethod
    def _text_not_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("campo textual obrigatorio vazio")
        return cleaned


class ArtifactSelectionCoverage(BaseModel):
    """Evidencia literal de que um artefato cobre um campo do contrato."""

    model_config = ConfigDict(extra="forbid")

    campo_saida: str
    ancoras: list[str] = Field(min_length=1)

    @field_validator("campo_saida")
    @classmethod
    def _field_not_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("campo_saida da cobertura nao pode ser vazio")
        return cleaned

    @field_validator("ancoras")
    @classmethod
    def _anchors_not_empty(cls, value: list[str]) -> list[str]:
        cleaned = [anchor.strip() for anchor in value if anchor.strip()]
        if not cleaned:
            raise ValueError("ancoras da cobertura nao podem ser vazias")
        return cleaned


class LayoutArtifactSelection(BaseModel):
    """Contrato da primeira chamada LLM que escolhe artefatos pelo inventario."""

    model_config = ConfigDict(extra="forbid")

    tipo_artefato: Literal["selecao_artefatos_layout"]
    artifact_paths: list[ArtifactSelectionItem]

    @field_validator("artifact_paths")
    @classmethod
    def _must_have_artifacts(
        cls,
        value: list[ArtifactSelectionItem],
    ) -> list[ArtifactSelectionItem]:
        if not value:
            raise ValueError("artifact_paths deve conter pelo menos um artefato")
        paths = [item.path.strip("/") for item in value]
        if len(paths) != len(set(paths)):
            raise ValueError("artifact_paths nao pode conter caminhos duplicados")
        return value

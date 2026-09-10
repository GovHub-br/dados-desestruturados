"""Calculo das metricas do fluxo Atlas a partir dos artefatos ja persistidos.

Este modulo e puro: recebe artefatos (dicionarios ja carregados do MinIO) e
devolve metricas. Ele nao conhece Langfuse, MinIO nem Airflow, o que permite
usar o mesmo calculo na instrumentacao ao vivo e no backfill historico.

Cada metrica e um `MetricValue`. Metricas numericas normalizadas em 0..1 sao
taxas; contagens ficam em valores absolutos; estados viram metricas
categoricas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

NUMERIC = "NUMERIC"
CATEGORICAL = "CATEGORICAL"
BOOLEAN = "BOOLEAN"


@dataclass(frozen=True)
class MetricValue:
    """Uma metrica calculada de uma etapa do fluxo."""

    name: str
    value: float | str
    data_type: str = NUMERIC
    comment: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def prompt_set_fingerprint(conjunto: str, utilizados: list[dict[str, Any]]) -> str:
    """Identidade da combinacao exata de versoes de prompt de uma chamada.

    Calculo puro sobre o que a execucao registrou. Fica no dominio porque tanto a
    projecao ao vivo quanto o backfill historico precisam derivar a mesma
    identidade a partir do mesmo artefato.
    """
    if not utilizados or all(item.get("origem") != "langfuse" for item in utilizados):
        return f"{conjunto}@codigo"
    versoes = ".".join(str(item.get("versao") or 0) for item in utilizados)
    return f"{conjunto}@{versoes}"


def _ratio(numerator: int, denominator: int) -> float:
    """Taxa segura em 0..1; denominador zero vira 0.0."""
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)


def _as_dict(value: Any) -> dict[str, Any]:
    """Normaliza entradas ausentes ou malformadas em dicionario vazio."""
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    """Normaliza entradas ausentes ou malformadas em lista vazia."""
    return value if isinstance(value, list) else []


# ---------------------------------------------------------------------------
# DAG 1 - extracao
# ---------------------------------------------------------------------------


def extraction_metrics(manifest: dict[str, Any]) -> list[MetricValue]:
    """Metricas da etapa de extracao Docling, a partir do manifesto."""
    manifest = _as_dict(manifest)
    artifact_uris = _as_list(manifest.get("artifact_uris"))
    counts: dict[str, int] = {}
    for uri in artifact_uris:
        text = str(uri)
        for kind in ("tables", "charts", "blocks", "sections", "metrics", "text_candidates"):
            if f"/{kind}/" in text:
                counts[kind] = counts.get(kind, 0) + 1

    metrics = [
        MetricValue(
            name="extracao_artefatos_total",
            value=float(len(artifact_uris)),
            comment="Quantidade de artefatos de extracao registrados no manifesto.",
        ),
        MetricValue(
            name="extracao_tabelas_detectadas",
            value=float(counts.get("tables", 0)),
            comment="Tabelas extraidas pelo Docling; base observavel do layout signature.",
        ),
        MetricValue(
            name="extracao_evidencias_textuais",
            value=float(counts.get("blocks", 0) + counts.get("text_candidates", 0)),
            comment="Blocos e candidatos textuais disponiveis para mapeamento.",
        ),
    ]
    resultado = _as_dict(manifest.get("resultado_runner"))
    status = str(resultado.get("status") or manifest.get("status") or "desconhecido")
    metrics.append(
        MetricValue(
            name="extracao_status",
            value=status,
            data_type=CATEGORICAL,
            comment="Status final do runner Docling.",
        )
    )
    metrics.append(
        MetricValue(
            name="extracao_ok",
            value=1.0 if counts.get("tables", 0) > 0 or counts.get("blocks", 0) > 0 else 0.0,
            data_type=BOOLEAN,
            comment="Extracao produziu evidencia utilizavel para a resolucao.",
        )
    )
    return metrics


# ---------------------------------------------------------------------------
# DAG 2 - validacao deterministica e resolucao
# ---------------------------------------------------------------------------


def layout_validation_metrics(validation: dict[str, Any]) -> list[MetricValue]:
    """Metricas da validacao deterministica do layout signature."""
    validation = _as_dict(validation)
    status_info = _as_dict(validation.get("status_compatibilidade"))
    total = int(status_info.get("regras_total") or 0)
    approved = int(status_info.get("regras_aprovadas") or 0)
    rejected = int(status_info.get("regras_reprovadas") or 0)
    status = str(status_info.get("status") or "desconhecido")
    alert_codes = [str(code) for code in _as_list(status_info.get("codigos_alerta"))]

    return [
        MetricValue(
            name="validacao_regras_total",
            value=float(total),
            comment="Regras deterministicas declaradas no layout e efetivamente executadas.",
        ),
        MetricValue(
            name="validacao_taxa_aprovacao_regras",
            value=_ratio(approved, total),
            comment="Fracao das regras deterministicas aprovadas na execucao.",
        ),
        MetricValue(
            name="validacao_regras_reprovadas",
            value=float(rejected),
            comment="Regras deterministicas reprovadas; dispara analise de fallback.",
        ),
        MetricValue(
            name="validacao_status",
            value=status,
            data_type=CATEGORICAL,
            comment="Status de compatibilidade entre layout signature e documento.",
        ),
        MetricValue(
            name="validacao_cobertura_de_regras",
            value=1.0 if total > 0 else 0.0,
            data_type=BOOLEAN,
            comment=(
                "Indica se a validacao realmente executou alguma regra. "
                "Status 'compativel' com zero regras e aprovacao vazia."
            ),
            metadata={"codigos_alerta": alert_codes},
        ),
    ]


def resolution_metrics(
    audit: list[dict[str, Any]] | dict[str, Any],
    *,
    contract: dict[str, Any] | None = None,
) -> list[MetricValue]:
    """Metricas de cobertura da resolucao a partir da auditoria de resolucao."""
    if isinstance(audit, dict):
        entries = _as_list(audit.get("auditoria_resolucao") or audit.get("entradas"))
    else:
        entries = _as_list(audit)
    entries = [item for item in entries if isinstance(item, dict)]

    total = len(entries)
    resolved = len([e for e in entries if str(e.get("status_resolucao")) == "resolvido"])
    required = [e for e in entries if bool(e.get("obrigatorio"))]
    required_resolved = len(
        [e for e in required if str(e.get("status_resolucao")) == "resolvido"]
    )

    by_source: dict[str, int] = {}
    for entry in entries:
        source = str(entry.get("tipo_origem") or "nao_informado")
        by_source[source] = by_source.get(source, 0) + 1

    literal_resolved = len(
        [
            e
            for e in entries
            if _as_dict(e.get("evidencia")).get("origem") == "literal_do_contrato_semantico"
        ]
    )
    observed_total = total - literal_resolved
    observed_resolved = resolved - literal_resolved

    metrics = [
        MetricValue(
            name="resolucao_campos_mapeados",
            value=float(total),
            comment="Campos do schema cobertos pelo mapeamento canonico do layout.",
        ),
        MetricValue(
            name="resolucao_cobertura_campos",
            value=_ratio(resolved, total),
            comment="Fracao dos campos mapeados que foram resolvidos com sucesso.",
        ),
        MetricValue(
            name="resolucao_campos_obrigatorios",
            value=float(len(required)),
            comment=(
                "Campos marcados como obrigatorios na auditoria. "
                "Zero significa que o contrato ou o layout nao declarou obrigatoriedade, "
                "e nao que a resolucao falhou."
            ),
        ),
        MetricValue(
            name="resolucao_campos_nao_resolvidos",
            value=float(total - resolved),
            comment="Campos mapeados que falharam na resolucao deterministica.",
        ),
        MetricValue(
            name="resolucao_cobertura_obs",
            value=_ratio(observed_resolved, observed_total),
            comment=(
                "Cobertura considerando apenas campos que exigem leitura do documento, "
                "excluindo literais preenchidos pelo contrato."
            ),
            metadata={"tipos_origem": by_source, "literais": literal_resolved},
        ),
    ]

    if required:
        metrics.append(
            MetricValue(
                name="resolucao_cobertura_obrigatorios",
                value=_ratio(required_resolved, len(required)),
                comment="Fracao dos campos obrigatorios do contrato que foram resolvidos.",
            )
        )

    if isinstance(contract, dict) and contract:
        dynamic_paths = _count_dynamic_leaves(contract.get("schema_saida"))
        metrics.append(
            MetricValue(
                name="resolucao_cobertura_do_contrato",
                value=_ratio(observed_resolved, dynamic_paths),
                comment=(
                    "Campos dinamicos do contrato semantico efetivamente resolvidos. "
                    "Mede o contrato inteiro, nao apenas o que o layout prometeu mapear."
                ),
                metadata={"campos_dinamicos_no_contrato": dynamic_paths},
            )
        )
    return metrics


_TYPE_DESCRIPTORS = {
    "string",
    "number",
    "integer",
    "boolean",
    "string | null",
    "number | null",
    "integer | null",
    "boolean | null",
}


def _count_dynamic_leaves(schema: Any) -> int:
    """Conta folhas dinamicas do `schema_saida`, ignorando literais do contrato."""
    if isinstance(schema, dict):
        return sum(_count_dynamic_leaves(value) for value in schema.values())
    if isinstance(schema, list):
        return sum(_count_dynamic_leaves(item) for item in schema)
    if isinstance(schema, str) and schema.strip().lower() in _TYPE_DESCRIPTORS:
        return 1
    return 0


# ---------------------------------------------------------------------------
# DAG 3 - fallback com LLM
# ---------------------------------------------------------------------------


def fallback_stage_metrics(
    *,
    stage: str,
    attempts: int,
    succeeded: bool,
    usage_by_attempt: list[dict[str, Any]] | None = None,
    prompt_fingerprint: str | None = None,
) -> list[MetricValue]:
    """Metricas de uma etapa de LLM do fallback, por estagio."""
    usage_by_attempt = usage_by_attempt or []
    total_tokens = 0
    output_tokens = 0
    cached_tokens = 0
    for usage in usage_by_attempt:
        usage = _as_dict(usage)
        total_tokens += int(usage.get("total_tokens") or 0)
        output_tokens += int(usage.get("completion_tokens") or 0)
        cached_tokens += int(usage.get("prompt_cache_hit_tokens") or 0)

    stage_metadata = {"etapa_llm": stage}
    metrics = [
        MetricValue(
            name="llm_tentativas",
            value=float(attempts),
            comment="Tentativas de LLM ate concluir a etapa; 1 e o ideal.",
            metadata=stage_metadata,
        ),
        MetricValue(
            name="llm_acerto_1a_tentativa",
            value=1.0 if succeeded and attempts <= 1 else 0.0,
            data_type=BOOLEAN,
            comment="Etapa aprovada na primeira resposta da LLM, sem ciclo de correcao.",
            metadata=stage_metadata,
        ),
        MetricValue(
            name="llm_etapa_sucesso",
            value=1.0 if succeeded else 0.0,
            data_type=BOOLEAN,
            comment="Etapa de LLM produziu artefato valido ao final das tentativas.",
            metadata=stage_metadata,
        ),
    ]
    if total_tokens:
        metrics.append(
            MetricValue(
                name="llm_tokens_total",
                value=float(total_tokens),
                comment="Tokens consumidos pela etapa, somando todas as tentativas.",
                metadata={
                    **stage_metadata,
                    "tokens_saida": output_tokens,
                    "tokens_cacheados": cached_tokens,
                },
            )
        )
    if prompt_fingerprint:
        # Categorica de proposito: o valor identifica uma combinacao de versoes,
        # nao mede quantidade. Como dimensao `stringValue`, permite cortar as
        # metricas acima por versao de prompt sem cruzar dados na mao.
        metrics.append(
            MetricValue(
                name="prompt_conjunto_versao",
                value=prompt_fingerprint,
                data_type=CATEGORICAL,
                comment=(
                    "Combinacao exata de versoes de bloco que produziu a chamada. "
                    "O sufixo 'codigo' indica prompt vindo do repositorio."
                ),
                metadata=stage_metadata,
            )
        )
    return metrics


def fallback_execution_metrics(
    *,
    scope: str | None,
    candidate_valid: bool,
    revalidation: dict[str, Any] | None,
    revalidation_validation: dict[str, Any] | None,
    publication: dict[str, Any] | None,
    total_llm_attempts: int,
    total_tokens: int = 0,
) -> list[MetricValue]:
    """Metricas do fallback inteiro, incluindo o gate de publicacao."""
    revalidation = _as_dict(revalidation)
    revalidation_validation = _as_dict(revalidation_validation)
    publication = _as_dict(publication)

    approved = bool(revalidation.get("aprovado_para_publicacao"))
    status_info = _as_dict(revalidation_validation.get("status_compatibilidade"))
    rules_total = int(status_info.get("regras_total") or 0)
    rules_approved = int(status_info.get("regras_aprovadas") or 0)
    published = str(publication.get("status") or "") == "publicado"

    metrics = [
        MetricValue(
            name="fallback_escopo",
            value=str(scope or "desconhecido"),
            data_type=CATEGORICAL,
            comment="Escopo escolhido: correcao parcial, regeneracao total ou criacao inicial.",
        ),
        MetricValue(
            name="fallback_tentativas_llm_total",
            value=float(total_llm_attempts),
            comment="Total de chamadas de LLM na execucao de fallback, somando estagios.",
        ),
        MetricValue(
            name="fallback_candidato_valido",
            value=1.0 if candidate_valid else 0.0,
            data_type=BOOLEAN,
            comment="Candidato passou na validacao estrutural antes da revalidacao.",
        ),
        MetricValue(
            name="revalidacao_aprovada",
            value=1.0 if approved else 0.0,
            data_type=BOOLEAN,
            comment="Revalidacao da DAG 2 marcou o candidato como apto a publicar.",
        ),
        MetricValue(
            name="revalidacao_regras_executadas",
            value=float(rules_total),
            comment=(
                "Regras deterministicas executadas na revalidacao do candidato. "
                "Zero significa que o gate aprovou sem evidencia."
            ),
        ),
        MetricValue(
            name="revalidacao_gate_efetivo",
            value=1.0 if (approved and rules_total > 0 and rules_approved == rules_total) else 0.0,
            data_type=BOOLEAN,
            comment=(
                "Aprovacao sustentada por regras realmente executadas. "
                "Separa aprovacao real de aprovacao vazia."
            ),
            metadata={"regras_total": rules_total, "regras_aprovadas": rules_approved},
        ),
        MetricValue(
            name="publicacao_realizada",
            value=1.0 if published else 0.0,
            data_type=BOOLEAN,
            comment="Nova versao de layout signature publicada ao fim do fallback.",
            metadata={"versao": publication.get("versao_publicada")},
        ),
    ]
    if total_tokens:
        metrics.append(
            MetricValue(
                name="fallback_tokens_total",
                value=float(total_tokens),
                comment="Tokens consumidos pela execucao de fallback inteira.",
            )
        )
    return metrics


# ---------------------------------------------------------------------------
# Transicoes entre etapas
# ---------------------------------------------------------------------------


def transition_metrics(
    *,
    origem: str,
    destino: str,
    habilitada: bool,
    motivo: str | None = None,
    perda_de_cobertura: float | None = None,
) -> list[MetricValue]:
    """Metricas do handoff entre duas etapas do fluxo."""
    name = f"transicao_{origem}_para_{destino}"
    metrics = [
        MetricValue(
            name=name,
            value=1.0 if habilitada else 0.0,
            data_type=BOOLEAN,
            comment=f"Handoff de '{origem}' para '{destino}' ocorreu com insumos validos.",
            metadata={"motivo": motivo} if motivo else {},
        )
    ]
    if perda_de_cobertura is not None:
        metrics.append(
            MetricValue(
                name=f"{name}_delta_cobertura",
                value=round(perda_de_cobertura, 6),
                comment=(
                    f"Variacao de cobertura observada entre '{origem}' e '{destino}'. "
                    "Negativo indica regressao introduzida pela etapa."
                ),
            )
        )
    return metrics


# ---------------------------------------------------------------------------
# Ponta a ponta
# ---------------------------------------------------------------------------


def end_to_end_metrics(
    *,
    sucesso: bool,
    exigiu_llm: bool,
    duracao_segundos: float | None = None,
    tokens_totais: int = 0,
    cobertura_final: float | None = None,
    apto_para_bronze: bool = False,
) -> list[MetricValue]:
    """Metricas da execucao de ponta a ponta, do PDF ate a aptidao para bronze."""
    metrics = [
        MetricValue(
            name="e2e_sucesso",
            value=1.0 if sucesso else 0.0,
            data_type=BOOLEAN,
            comment="Execucao chegou ao fim com schema resolvido utilizavel.",
        ),
        MetricValue(
            name="e2e_autonomia_deterministica",
            value=0.0 if exigiu_llm else 1.0,
            data_type=BOOLEAN,
            comment=(
                "Execucao resolvida sem acionar a LLM. "
                "E a metrica-alvo do projeto: fallback deve ser excecao."
            ),
        ),
        MetricValue(
            name="e2e_apto_para_bronze",
            value=1.0 if apto_para_bronze else 0.0,
            data_type=BOOLEAN,
            comment="Validacao permitiu continuidade para a ingestao bronze.",
        ),
    ]
    if duracao_segundos is not None:
        metrics.append(
            MetricValue(
                name="e2e_duracao_segundos",
                value=round(float(duracao_segundos), 3),
                comment="Tempo total da execucao de ponta a ponta.",
            )
        )
    if tokens_totais:
        metrics.append(
            MetricValue(
                name="e2e_tokens_llm",
                value=float(tokens_totais),
                comment="Tokens de LLM gastos pela execucao inteira.",
            )
        )
    if cobertura_final is not None:
        metrics.append(
            MetricValue(
                name="e2e_cobertura_final",
                value=round(float(cobertura_final), 6),
                comment="Cobertura de campos do contrato no artefato final da execucao.",
            )
        )
    return metrics

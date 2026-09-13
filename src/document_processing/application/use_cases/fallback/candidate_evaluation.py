"""Aplica as regras de negocio da producao a um candidato avaliado off-line.

A comparacao de conjuntos de um dataset nao sabe nada sobre contrato, escopo ou
seletor obrigatorio de array: um candidato que a DAG rejeitaria pode tirar F1
alto. Este modulo fecha essa lacuna rodando o mesmo
`FallbackCandidateValidationService` que roda em producao.

O contexto de validacao e reconstruido a partir das mensagens persistidas em
`entrada_llm_layout_signature_candidato.json`, que carregam os blocos JSON
enviados a LLM. Isso permite validar execucoes historicas sem artefato novo.

Duas fronteiras importantes:

- **contexto nao validavel nao e candidato invalido.** Execucoes antigas guardam
  o contrato num formato que o parser atual recusa. Reprovar por isso mediria a
  idade do artefato, nao a qualidade do candidato, entao esse caso e reportado
  como "nao aplicavel" e nao vira metrica.
- **nada aqui levanta excecao.** Avaliacao off-line nunca pode derrubar quem a
  chama, pela mesma razao que a observabilidade nao derruba o pipeline.

`_paths_fixos_do_contrato` nao e reconstruivel a partir das mensagens, mas o
resultado do portao nao muda: `estrutura_schema_saida.paths_permitidos` ja exclui
os paths fixos, entao mapear um deles reprova de qualquer forma na checagem de
"campo fora do schema_saida".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from document_processing.domain.contracts.mapping_requirements import (
    MappingRequirementsError,
    mapping_requirements_from_context,
)
from document_processing.domain.fallback import FallbackCandidateValidationService

CANDIDATE_VALIDATION_SERVICE = FallbackCandidateValidationService()


@dataclass(frozen=True)
class ResultadoValidacao:
    """Veredito das regras de negocio sobre um candidato avaliado off-line."""

    validavel: bool
    valido: bool
    motivo: str | None = None


def blocos_json_das_mensagens(mensagens: Any) -> dict[str, Any]:
    """Recupera os blocos JSON que foram enviados a LLM na conversa.

    As mensagens alternam instrucao em prosa e bloco de dados serializado; so os
    blocos de dados desserializam como objeto JSON.
    """
    blocos: dict[str, Any] = {}
    if not isinstance(mensagens, list):
        return blocos
    for mensagem in mensagens:
        conteudo = mensagem.get("content") if isinstance(mensagem, dict) else None
        if not isinstance(conteudo, str):
            continue
        try:
            payload = json.loads(conteudo)
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict):
            blocos.update(payload)
    return blocos


def contexto_de_validacao(mensagens: Any) -> dict[str, Any]:
    """Reconstroi o `fallback_problem_context` minimo exigido pelo validador.

    `contexto_execucao` carrega a linhagem e o escopo que foram autorizados antes
    da chamada; usa-los aqui reconstroi a condicao de entrada, nao a resposta.
    """
    blocos = blocos_json_das_mensagens(mensagens)
    execucao = blocos.get("contexto_execucao")
    execucao = execucao if isinstance(execucao, dict) else {}
    return {
        "contrato_semantico_relevante": blocos.get("contrato_semantico_relevante", {}),
        "escopo_permitido": execucao.get("escopo_correcao"),
        "fallback_context": {
            "document_id": execucao.get("document_id"),
            "execution_id": execucao.get("execution_id_origem"),
        },
        "layout_signature_base_ref": execucao.get("base_layout_signature"),
    }


def validar_candidato(candidato: Any, *, mensagens: Any) -> ResultadoValidacao:
    """Aplica as regras da producao ao candidato, sem nunca levantar excecao."""
    contexto = contexto_de_validacao(mensagens)
    if not contexto.get("escopo_permitido"):
        return ResultadoValidacao(
            validavel=False,
            valido=False,
            motivo="Mensagens sem contexto_execucao: escopo permitido desconhecido.",
        )

    try:
        mapping_requirements_from_context(contexto["contrato_semantico_relevante"])
    except MappingRequirementsError as exc:
        # Formato de contrato anterior ao parser atual: o candidato nao esta em
        # julgamento aqui.
        return ResultadoValidacao(
            validavel=False, valido=False, motivo=f"Contexto nao validavel: {exc}"
        )
    except Exception as exc:  # noqa: BLE001
        return ResultadoValidacao(
            validavel=False, valido=False, motivo=f"Contexto nao validavel: {exc}"
        )

    try:
        CANDIDATE_VALIDATION_SERVICE.validate_candidate_layout(candidato, contexto)
    except Exception as exc:  # noqa: BLE001
        return ResultadoValidacao(validavel=True, valido=False, motivo=str(exc)[:500])
    return ResultadoValidacao(validavel=True, valido=True)

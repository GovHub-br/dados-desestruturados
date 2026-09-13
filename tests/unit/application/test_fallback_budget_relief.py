"""Testes do retry por alivio de orcamento na geracao de fragmento.

Resposta vazia nao e erro de conteudo: nao ha o que corrigir e repetir identico
so repete o gasto. A unica repeticao que muda alguma coisa e a que devolve
orcamento de conclusao para a resposta.
"""

from __future__ import annotations

from document_processing.application.use_cases.fallback.candidate_composition import (
    CandidateCompositionMixin,
)
from document_processing.infrastructure.llm.client import FallbackLlmClientError

_sem_conteudo = CandidateCompositionMixin._is_response_without_content
_alivio = CandidateCompositionMixin._budget_relief_options


def test_conclusao_esgotada_sem_conteudo_e_reconhecida():
    erro = FallbackLlmClientError(
        "LLM retornou conteudo textual vazio.",
        response_metadata={"finish_reason": "length", "content_presente": False},
    )
    assert _sem_conteudo(erro) is True


def test_conteudo_vazio_sem_metadado_tambem_e_reconhecido():
    """O provedor nem sempre devolve finish_reason; a mensagem ainda informa."""
    assert _sem_conteudo(FallbackLlmClientError("LLM retornou conteudo textual vazio.")) is True


def test_json_malformado_nao_e_tratado_como_resposta_vazia():
    """Ai existe conteudo para corrigir, e o caminho certo e o reparo."""
    erro = FallbackLlmClientError("Conteudo da LLM nao e JSON valido.", raw_content="{")
    assert _sem_conteudo(erro) is False


def test_alivio_desliga_o_raciocinio_preservando_o_resto():
    opcoes = {"max_tokens": 15000, "thinking_mode": "enabled"}
    assert _alivio(opcoes) == {"max_tokens": 15000, "thinking_mode": "disabled"}


def test_sem_raciocinio_ligado_nao_ha_orcamento_a_liberar():
    """Devolver None e o que faz o laco parar em vez de repetir de graca."""
    assert _alivio({"max_tokens": 15000, "thinking_mode": "disabled"}) is None
    assert _alivio({"max_tokens": 15000}) is None

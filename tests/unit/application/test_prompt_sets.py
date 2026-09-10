"""Garante que mover os prompts para o Langfuse nao muda o que a LLM recebe.

O risco desta mudanca nao e o Langfuse ficar fora do ar: e a montagem silenciosa
mudar de ordem, de papel ou de conteudo e ninguem perceber, porque o resultado
continua sendo "uma lista de mensagens". Estes testes fixam a sequencia original.
"""

from __future__ import annotations

import json

import pytest

from document_processing.application.use_cases.fallback import prompt_sets
from document_processing.application.use_cases.fallback.candidate_json_generation import (
    CandidateJsonGenerationMixin,
)
from document_processing.application.use_cases.fallback.fragment_generation import (
    FragmentGenerationMixin,
)
from document_processing.application.use_cases.fallback.prompts import (
    candidate_artifacts_instruction,
    candidate_contract_instruction,
    candidate_final_instruction,
    candidate_scope_instruction,
    candidate_structure_instruction,
    unit_mapping_artifacts_instruction,
    unit_mapping_final_instruction,
    unit_mapping_repair_instruction,
    unit_mapping_scope_instruction,
    unit_mapping_structure_instruction,
)
from document_processing.infrastructure.prompts.langfuse_prompt_registry import (
    ORIGEM_CODIGO,
    ORIGEM_LANGFUSE,
    LangfusePromptRegistry,
)


class _Montador(CandidateJsonGenerationMixin, FragmentGenerationMixin):
    """Expoe so a montagem de mensagens, sem MinIO, LLM nem Airflow."""

    def __init__(self) -> None:
        self.prompts_registrados: list[dict] = []
        self.conjunto_registrado: str | None = None

    def _registrar_prompts(
        self, utilizados: list[dict], *, conjunto: str | None = None
    ) -> None:
        self.prompts_registrados = utilizados
        self.conjunto_registrado = conjunto


@pytest.fixture
def montador() -> _Montador:
    return _Montador()


@pytest.fixture(autouse=True)
def _sem_langfuse(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem a flag ligada, tudo tem de resolver pelo espelho de codigo."""
    monkeypatch.delenv("ATLAS_PROMPTS_LANGFUSE_ENABLED", raising=False)
    prompt_sets.LANGFUSE_PROMPT_REGISTRY.limpar_cache()


CONTEXTO_CANDIDATO = {
    "escopo_permitido": "criacao_inicial_layout",
    "contexto_execucao": {"document_id": "doc-1"},
    "contrato_semantico_relevante": {"campos": ["a"]},
    "alvos_mapeaveis": ["a"],
    "exemplo_estrutura_layout_signature": {"exemplo": True},
    "artefatos_contexto_llm": {"tables/t1.json": {}},
}

PAYLOAD_FRAGMENTO = {
    "contexto_execucao": {"escopo_correcao": "correcao_parcial_mapeamento"},
    "unidade_mapeamento": {"paths": ["a.b"]},
    "contrato_semantico_relevante": {"campos": ["a.b"]},
    "alvos_mapeaveis": ["a.b"],
    "exemplo_estrutura_mapeamento_unidade": {"exemplo": True},
    "artefatos_contexto_llm": {"tables/t1.json": {}},
}


def _bloco(contexto: dict, nome: str) -> str:
    return json.dumps({nome: contexto.get(nome, {})}, ensure_ascii=False, indent=2)


def test_sequencia_do_candidato_e_identica_a_original(montador: _Montador) -> None:
    """A ordem de papeis e conteudos da primeira geracao nao pode mudar."""
    esperado = [
        {"role": "system", "content": candidate_scope_instruction("criacao_inicial_layout")},
        {"role": "user", "content": _bloco(CONTEXTO_CANDIDATO, "contexto_execucao")},
        {"role": "system", "content": candidate_contract_instruction()},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "contrato_semantico_relevante": CONTEXTO_CANDIDATO[
                        "contrato_semantico_relevante"
                    ],
                    "alvos_mapeaveis": CONTEXTO_CANDIDATO["alvos_mapeaveis"],
                },
                ensure_ascii=False,
                indent=2,
            ),
        },
        {"role": "system", "content": candidate_structure_instruction()},
        {
            "role": "user",
            "content": _bloco(CONTEXTO_CANDIDATO, "exemplo_estrutura_layout_signature"),
        },
        {"role": "system", "content": candidate_artifacts_instruction()},
        {"role": "user", "content": _bloco(CONTEXTO_CANDIDATO, "artefatos_contexto_llm")},
        {"role": "system", "content": candidate_final_instruction()},
    ]
    assert montador._initial_candidate_messages(CONTEXTO_CANDIDATO) == esperado


def test_sequencia_do_fragmento_e_identica_a_original(montador: _Montador) -> None:
    """Idem para o mapeamento por unidade, sem payload de correcao."""
    mensagens = montador._fragment_messages(fragment_payload=PAYLOAD_FRAGMENTO)
    assert [m["role"] for m in mensagens] == [
        "system", "user", "system", "user", "system", "user", "system", "user", "system",
    ]
    assert mensagens[0]["content"] == unit_mapping_scope_instruction(
        "correcao_parcial_mapeamento"
    )
    assert mensagens[2]["content"] == candidate_contract_instruction()
    assert mensagens[4]["content"] == unit_mapping_structure_instruction()
    assert mensagens[6]["content"] == unit_mapping_artifacts_instruction()
    assert mensagens[8]["content"] == unit_mapping_final_instruction()


def test_fragmento_com_correcao_insere_o_reparo_antes_da_recapitulacao(
    montador: _Montador,
) -> None:
    """O conjunto de reparo acrescenta duas mensagens, nao troca o system inicial."""
    mensagens = montador._fragment_messages(
        fragment_payload=PAYLOAD_FRAGMENTO,
        repair_payload={"erro_validacao": "path invalido"},
    )
    assert len(mensagens) == 11
    assert mensagens[8]["content"] == unit_mapping_repair_instruction()
    assert json.loads(mensagens[9]["content"]) == {"erro_validacao": "path invalido"}
    assert mensagens[10]["content"] == unit_mapping_final_instruction()


def test_todos_os_blocos_declarados_tem_espelho_em_codigo() -> None:
    """Um bloco sem espelho seria um ponto onde o Langfuse vira dependencia dura."""
    for bloco in prompt_sets.BLOCOS:
        texto = bloco.espelho()
        assert isinstance(texto, str) and texto.strip(), bloco.sufixo


def test_toda_variavel_exigida_por_um_conjunto_falha_explicitamente() -> None:
    """Faltar variavel tem de estourar com o nome dela, nao montar mensagem vazia."""
    with pytest.raises(KeyError, match="contexto_execucao"):
        prompt_sets.montar(
            prompt_sets.CONJUNTO_CANDIDATO,
            variaveis={"instrucao_escopo": "x"},
        )


def test_resolucao_cai_para_o_codigo_quando_o_langfuse_falha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Indisponibilidade nao pode virar excecao nem texto vazio."""
    monkeypatch.setenv("ATLAS_PROMPTS_LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    registro = LangfusePromptRegistry()
    resolvido = registro.resolve("atlas/fallback/blocos/inexistente", espelho="TEXTO ESPELHO")
    assert resolvido.texto == "TEXTO ESPELHO"
    assert resolvido.origem == ORIGEM_CODIGO
    assert resolvido.versao is None


def test_registro_de_prompts_tem_um_item_por_bloco(montador: _Montador) -> None:
    """O artefato precisa listar cada bloco usado, com origem, na ordem."""
    montador._initial_candidate_messages(CONTEXTO_CANDIDATO)
    registrados = montador.prompts_registrados
    assert [item["nome"] for item in registrados] == [
        "atlas/fallback/blocos/candidato-escopo-criacao-inicial",
        "atlas/fallback/blocos/comum-contrato",
        "atlas/fallback/blocos/candidato-estrutura",
        "atlas/fallback/blocos/candidato-artefatos",
        "atlas/fallback/blocos/candidato-final",
    ]
    assert all(item["origem"] == ORIGEM_CODIGO for item in registrados)
    assert montador.conjunto_registrado == prompt_sets.CONJUNTO_CANDIDATO


def test_conjunto_de_reparo_do_fragmento_e_registrado_separado(
    montador: _Montador,
) -> None:
    """Reparo e outro conjunto, senao a metrica misturaria duas conversas
    diferentes sob a mesma identidade de prompt."""
    montador._fragment_messages(fragment_payload=PAYLOAD_FRAGMENTO)
    assert montador.conjunto_registrado == prompt_sets.CONJUNTO_UNIDADE
    montador._fragment_messages(
        fragment_payload=PAYLOAD_FRAGMENTO, repair_payload={"erro_validacao": "x"}
    )
    assert montador.conjunto_registrado == prompt_sets.CONJUNTO_UNIDADE_REPARO


def test_impressao_digital_separa_codigo_de_versao_publicada() -> None:
    """Sem esta distincao, execucoes com prompt do repositorio e do Langfuse
    cairiam no mesmo balde na comparacao entre releases."""
    so_codigo = [{"nome": "a", "versao": None, "origem": ORIGEM_CODIGO}]
    assert prompt_sets.impressao_digital("layout-candidato", so_codigo) == (
        "layout-candidato@codigo"
    )
    publicados = [
        {"nome": "a", "versao": 2, "origem": ORIGEM_LANGFUSE},
        {"nome": "b", "versao": 3, "origem": ORIGEM_LANGFUSE},
    ]
    assert prompt_sets.impressao_digital("layout-candidato", publicados) == (
        "layout-candidato@2.3"
    )

"""Conjuntos de prompt do fallback: quais blocos, em que ordem, por etapa.

A divisao de responsabilidade e deliberada:

- o **conteudo** de cada bloco vive no Langfuse, versionado e editavel pela
  interface, com o espelho em `prompts.py` servindo de queda quando o Langfuse
  nao responde;
- a **estrutura** da conversa vive aqui, no repositorio, porque a ordem das
  mensagens e onde os dados da execucao entram sao decisoes de codigo, nao de
  conteudo.

Por isso a montagem resolve bloco a bloco em vez de baixar o conjunto ja composto
do Langfuse: assim as versoes registradas no artefato sao exatamente as que
produziram a chamada, sem janela entre o que foi lido e o que foi usado.

Os conjuntos tambem existem como chat prompts no Langfuse. La eles servem para
ver a etapa inteira em uma tela e para ligar a generation ao prompt; quem executa
e esta declaracao.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from document_processing.domain.observability.metrics import prompt_set_fingerprint
from document_processing.infrastructure.prompts.langfuse_prompt_registry import (
    LANGFUSE_PROMPT_REGISTRY,
    LangfusePromptRegistry,
    ResolvedPrompt,
)

from .candidate_prompts import (
    CANDIDATE_SCOPE_PADRAO,
    CANDIDATE_SCOPE_PROMPTS,
    artifact_selection_repair_system_prompt,
    artifact_selection_system_prompt,
    candidate_artifacts_instruction,
    candidate_contract_instruction,
    candidate_final_instruction,
    candidate_layout_repair_system_prompt,
    candidate_structure_instruction,
)
from .unit_mapping_prompts import (
    UNIT_MAPPING_SCOPE_PADRAO,
    UNIT_MAPPING_SCOPE_SENTENCES,
    UNIT_MAPPING_SCOPE_TEMPLATE,
    unit_mapping_artifacts_instruction,
    unit_mapping_final_instruction,
    unit_mapping_repair_instruction,
    unit_mapping_structure_instruction,
)

NAMESPACE = "atlas/fallback"


def nome_bloco(sufixo: str) -> str:
    """Nome completo de um bloco no Langfuse."""
    return f"{NAMESPACE}/blocos/{sufixo}"


def nome_conjunto(sufixo: str) -> str:
    """Nome completo de um conjunto no Langfuse."""
    return f"{NAMESPACE}/conjuntos/{sufixo}"


@dataclass(frozen=True)
class Bloco:
    """Um trecho de instrucao versionavel isoladamente."""

    sufixo: str
    espelho: Callable[[], str]
    etapa: str
    descricao: str

    @property
    def nome(self) -> str:
        """Nome do bloco no Langfuse."""
        return nome_bloco(self.sufixo)


def _escopo_candidato(chave: str) -> Callable[[], str]:
    """Fecha sobre um escopo do candidato para servir de espelho."""
    return lambda: CANDIDATE_SCOPE_PROMPTS[chave]


def _escopo_unidade(chave: str) -> Callable[[], str]:
    """Fecha sobre uma frase de escopo do mapeamento por unidade."""
    return lambda: UNIT_MAPPING_SCOPE_SENTENCES[chave]


BLOCOS: tuple[Bloco, ...] = (
    Bloco(
        "selecao-artefatos-system",
        artifact_selection_system_prompt,
        "selecao_artefatos",
        "Escolhe quais artefatos da extracao a DAG 3 deve abrir.",
    ),
    Bloco(
        "selecao-artefatos-repair",
        artifact_selection_repair_system_prompt,
        "selecao_artefatos",
        "Corrige uma selecao reprovada pela validacao deterministica.",
    ),
    Bloco(
        "comum-contrato",
        candidate_contract_instruction,
        "comum",
        "Como ler contrato, paths e arrays. Usado pelo candidato e pelo mapeamento por unidade.",
    ),
    Bloco(
        "candidato-escopo-criacao-inicial",
        _escopo_candidato("criacao_inicial_layout"),
        "layout_signature_candidato",
        "Responsabilidade da LLM quando nao existe layout ativo.",
    ),
    Bloco(
        "candidato-escopo-correcao-parcial",
        _escopo_candidato("correcao_parcial_mapeamento"),
        "layout_signature_candidato",
        "Responsabilidade da LLM quando so os mapeamentos quebrados podem mudar.",
    ),
    Bloco(
        "candidato-escopo-regeneracao-total",
        _escopo_candidato("regeneracao_total_mapeamento"),
        "layout_signature_candidato",
        "Responsabilidade da LLM quando o layout anterior deixou de ser confiavel.",
    ),
    Bloco(
        "candidato-estrutura",
        candidate_structure_instruction,
        "layout_signature_candidato",
        "Papel do exemplo de layout e sintaxe dos seletores.",
    ),
    Bloco(
        "candidato-artefatos",
        candidate_artifacts_instruction,
        "layout_signature_candidato",
        "Como usar exclusivamente as evidencias carregadas pela DAG.",
    ),
    Bloco(
        "candidato-final",
        candidate_final_instruction,
        "layout_signature_candidato",
        "Recapitulacao da tarefa imediatamente antes da resposta JSON.",
    ),
    Bloco(
        "candidato-repair",
        candidate_layout_repair_system_prompt,
        "layout_signature_candidato",
        "Corrige um candidato rejeitado por validacao estrutural ou de dominio.",
    ),
    Bloco(
        "unit-mapping-escopo",
        lambda: UNIT_MAPPING_SCOPE_TEMPLATE,
        "unit_mapping",
        "Gabarito da tarefa por unidade. Recebe a frase de escopo em {{instrucao_escopo}}.",
    ),
    Bloco(
        "unit-mapping-escopo-criacao-inicial",
        _escopo_unidade("criacao_inicial_layout"),
        "unit_mapping",
        "Frase de escopo para criacao inicial.",
    ),
    Bloco(
        "unit-mapping-escopo-correcao-parcial",
        _escopo_unidade("correcao_parcial_mapeamento"),
        "unit_mapping",
        "Frase de escopo para correcao parcial.",
    ),
    Bloco(
        "unit-mapping-escopo-regeneracao-total",
        _escopo_unidade("regeneracao_total_mapeamento"),
        "unit_mapping",
        "Frase de escopo para regeneracao total.",
    ),
    Bloco(
        "unit-mapping-estrutura",
        unit_mapping_structure_instruction,
        "unit_mapping",
        "Forma esperada do fragmento de mapeamento por unidade.",
    ),
    Bloco(
        "unit-mapping-artefatos",
        unit_mapping_artifacts_instruction,
        "unit_mapping",
        "Uso das evidencias no mapeamento por unidade.",
    ),
    Bloco(
        "unit-mapping-final",
        unit_mapping_final_instruction,
        "unit_mapping",
        "Recapitulacao antes da resposta do fragmento.",
    ),
    Bloco(
        "unit-mapping-repair",
        unit_mapping_repair_instruction,
        "unit_mapping",
        "Corrige um fragmento de mapeamento reprovado.",
    ),
)

BLOCOS_POR_SUFIXO: dict[str, Bloco] = {bloco.sufixo: bloco for bloco in BLOCOS}

CONJUNTO_SELECAO = "selecao-artefatos"
CONJUNTO_SELECAO_REPARO = "selecao-artefatos-repair"
CONJUNTO_CANDIDATO = "layout-candidato"
CONJUNTO_CANDIDATO_REPARO = "layout-candidato-repair"
CONJUNTO_UNIDADE = "unit-mapping"
CONJUNTO_UNIDADE_REPARO = "unit-mapping-repair"


class _Dado(str):
    """Marca uma posicao preenchida por dados da execucao, nao por prompt."""


def _dado(variavel: str) -> _Dado:
    """Placeholder de um bloco `user` na sequencia de um conjunto."""
    return _Dado(variavel)


# Sequencia de cada conjunto: str simples e sufixo de bloco (mensagem `system`),
# _Dado e uma variavel preenchida na execucao (mensagem `user`). E esta declaracao
# que o script de sincronizacao publica como chat prompt no Langfuse.
SEQUENCIAS: dict[str, tuple[Any, ...]] = {
    CONJUNTO_SELECAO: ("selecao-artefatos-system", _dado("payload_selecao")),
    CONJUNTO_SELECAO_REPARO: ("selecao-artefatos-repair", _dado("payload_correcao")),
    CONJUNTO_CANDIDATO: (
        _dado("instrucao_escopo"),
        _dado("contexto_execucao"),
        "comum-contrato",
        _dado("contrato_e_alvos"),
        "candidato-estrutura",
        _dado("exemplo_estrutura"),
        "candidato-artefatos",
        _dado("artefatos_contexto_llm"),
        "candidato-final",
    ),
    CONJUNTO_CANDIDATO_REPARO: ("candidato-repair", _dado("payload_correcao")),
    CONJUNTO_UNIDADE: (
        _dado("instrucao_escopo"),
        _dado("contexto_execucao"),
        "comum-contrato",
        _dado("unidade_e_contrato"),
        "unit-mapping-estrutura",
        _dado("exemplo_estrutura"),
        "unit-mapping-artefatos",
        _dado("artefatos_contexto_llm"),
        "unit-mapping-final",
    ),
    CONJUNTO_UNIDADE_REPARO: (
        _dado("instrucao_escopo"),
        _dado("contexto_execucao"),
        "comum-contrato",
        _dado("unidade_e_contrato"),
        "unit-mapping-estrutura",
        _dado("exemplo_estrutura"),
        "unit-mapping-artefatos",
        _dado("artefatos_contexto_llm"),
        "unit-mapping-repair",
        _dado("payload_correcao"),
        "unit-mapping-final",
    ),
}

# Blocos que um conjunto usa sem que a sequencia os cite, porque entram por
# variavel. Sem isto eles ficariam sem etiqueta de agrupamento no Langfuse.
BLOCOS_POR_VARIAVEL: dict[str, tuple[str, ...]] = {
    CONJUNTO_CANDIDATO: (
        "candidato-escopo-criacao-inicial",
        "candidato-escopo-correcao-parcial",
        "candidato-escopo-regeneracao-total",
    ),
    CONJUNTO_UNIDADE: (
        "unit-mapping-escopo",
        "unit-mapping-escopo-criacao-inicial",
        "unit-mapping-escopo-correcao-parcial",
        "unit-mapping-escopo-regeneracao-total",
    ),
    CONJUNTO_UNIDADE_REPARO: (
        "unit-mapping-escopo",
        "unit-mapping-escopo-criacao-inicial",
        "unit-mapping-escopo-correcao-parcial",
        "unit-mapping-escopo-regeneracao-total",
    ),
}


def resolver(sufixo: str, *, registry: LangfusePromptRegistry | None = None) -> ResolvedPrompt:
    """Resolve um bloco pelo sufixo, caindo para o espelho de codigo."""
    bloco = BLOCOS_POR_SUFIXO[sufixo]
    alvo = registry or LANGFUSE_PROMPT_REGISTRY
    return alvo.resolve(bloco.nome, espelho=bloco.espelho())


def escopo_candidato(
    escopo: str, *, registry: LangfusePromptRegistry | None = None
) -> ResolvedPrompt:
    """Bloco de escopo do candidato, com a mesma queda para regeneracao total."""
    chave = escopo if escopo in CANDIDATE_SCOPE_PROMPTS else CANDIDATE_SCOPE_PADRAO
    return resolver(f"candidato-escopo-{_sufixo_escopo(chave)}", registry=registry)


def escopo_unidade(
    escopo: str, *, registry: LangfusePromptRegistry | None = None
) -> tuple[str, list[ResolvedPrompt]]:
    """Gabarito de escopo por unidade ja com a frase substituida."""
    chave = escopo if escopo in UNIT_MAPPING_SCOPE_SENTENCES else UNIT_MAPPING_SCOPE_PADRAO
    gabarito = resolver("unit-mapping-escopo", registry=registry)
    frase = resolver(f"unit-mapping-escopo-{_sufixo_escopo(chave)}", registry=registry)
    return gabarito.texto.replace("{{instrucao_escopo}}", frase.texto), [gabarito, frase]


def _sufixo_escopo(chave: str) -> str:
    """Traduz a chave de escopo do dominio para o sufixo usado no nome do bloco."""
    return {
        "criacao_inicial_layout": "criacao-inicial",
        "correcao_parcial_mapeamento": "correcao-parcial",
        "regeneracao_total_mapeamento": "regeneracao-total",
    }[chave]


def versao_do_conjunto(
    conjunto: str, *, registry: LangfusePromptRegistry | None = None
) -> int | None:
    """Versao publicada do chat prompt que agrupa a etapa, se houver."""
    alvo = registry or LANGFUSE_PROMPT_REGISTRY
    return alvo.versao_publicada(nome_conjunto(conjunto))


def montar(
    conjunto: str,
    *,
    variaveis: dict[str, str],
    resolvidos: dict[str, ResolvedPrompt] | None = None,
    registry: LangfusePromptRegistry | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """Monta as mensagens de um conjunto e devolve o que foi usado em cada bloco.

    `resolvidos` permite injetar blocos ja resolvidos fora da sequencia — o caso
    do escopo, que entra por variavel mas continua sendo prompt versionado e
    precisa aparecer no registro.
    """
    mensagens: list[dict[str, str]] = []
    utilizados: list[ResolvedPrompt] = list((resolvidos or {}).values())
    for passo in SEQUENCIAS[conjunto]:
        if isinstance(passo, _Dado):
            conteudo = variaveis.get(str(passo))
            if conteudo is None:
                raise KeyError(
                    f"Conjunto '{conjunto}' exige a variavel '{passo}', que nao foi informada."
                )
            papel = "system" if str(passo) == "instrucao_escopo" else "user"
            mensagens.append({"role": papel, "content": conteudo})
            continue
        resolvido = resolver(passo, registry=registry)
        utilizados.append(resolvido)
        mensagens.append({"role": "system", "content": resolvido.texto})
    return mensagens, [item.como_registro() for item in utilizados]


def impressao_digital(conjunto: str, utilizados: list[dict[str, Any]]) -> str:
    """Digital da combinacao de versoes usada na chamada.

    A composicao no Langfuse resolve os blocos por rotulo, entao a versao do
    conjunto nao se move quando um bloco muda. Esta digital e o que discrimina
    duas execucoes cujo conjunto tem o mesmo numero mas o conteudo diferente.
    """
    return prompt_set_fingerprint(conjunto, utilizados)

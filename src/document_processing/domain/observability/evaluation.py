"""Avaliacao off-line de uma etapa contra a referencia guardada no dataset.

Este modulo e puro, como `metrics.py`: recebe a saida da etapa e a referencia e
devolve `MetricValue`. Nao conhece Langfuse, dataset nem LLM.

O mapeamento canonico e avaliado em degraus, do mais frouxo para o mais estrito,
porque um numero unico nao distingue "mapeou o campo errado" de "mapeou o campo
certo pela instrucao errada" — e sao problemas diferentes, com correcoes
diferentes. Os degraus compartilham o denominador (os campos presentes nos dois
lados), entao a queda de um degrau para o outro localiza a falha:

    cobertura   -> achou os campos certos?
    tipo_origem -> escolheu a estrategia de extracao certa?
    instrucao   -> reproduziu a instrucao inteira, seletor incluido?

`arquivo_origem` e a excecao: so entra no denominador quem de fato le arquivo.
`valor_fixo` e `campo_derivado` nao tem `arquivo_origem`, e conta-los como
acerto trivial inflaria a metrica.
"""

from __future__ import annotations

from typing import Any

from document_processing.domain.fallback.models import CanonicalMappingEntry

from .metrics import BOOLEAN, NUMERIC, MetricValue

_SEM_ARQUIVO_DE_ORIGEM = ("valor_fixo", "campo_derivado")


def _taxa(numerador: int, denominador: int) -> float:
    """Taxa segura em 0..1; denominador zero vira 0.0."""
    if denominador <= 0:
        return 0.0
    return round(numerador / denominador, 6)


def _como_dicionario(valor: Any) -> dict[str, Any]:
    """Normaliza entradas ausentes ou malformadas em dicionario vazio."""
    return valor if isinstance(valor, dict) else {}


def _normalizar_instrucao(entrada: Any) -> dict[str, Any]:
    """Uniformiza uma instrucao de origem antes de comparar dois lados.

    Passa pelo proprio modelo do dominio para que defaults omitidos de um lado e
    escritos do outro (`obrigatorio: false`, `arquivo_origem: null`) nao virem
    diferenca falsa. Instrucao que o modelo recusa e comparada como veio.
    """
    bruta = _como_dicionario(entrada)
    try:
        return CanonicalMappingEntry.model_validate(bruta).model_dump(
            mode="json", exclude_none=True
        )
    except Exception:  # noqa: BLE001
        return {chave: valor for chave, valor in bruta.items() if valor is not None}


def metricas_de_conjunto(
    obtido: set[str], esperado: set[str], *, sobre: str
) -> list[MetricValue]:
    """Precisao, revocacao, F1 e igualdade exata entre dois conjuntos.

    Precisao e revocacao ficam separadas porque escolher 8 itens certos entre 10
    e escolher os mesmos 8 entre 20 sao resultados diferentes; a media harmonica
    so faz sentido depois que os dois lados estao visiveis.
    """
    if not esperado:
        return []
    acertos = len(obtido & esperado)
    precisao = _taxa(acertos, len(obtido))
    revocacao = _taxa(acertos, len(esperado))
    soma = precisao + revocacao
    f1 = round(2 * precisao * revocacao / soma, 6) if soma else 0.0
    contagem = f"{acertos} de {len(esperado)} {sobre}; {len(obtido)} propostos."
    return [
        MetricValue(
            name="avaliacao_precisao",
            value=precisao,
            data_type=NUMERIC,
            comment=f"Quanto do que foi proposto estava certo. {contagem}",
        ),
        MetricValue(
            name="avaliacao_revocacao",
            value=revocacao,
            data_type=NUMERIC,
            comment=f"Quanto do esperado foi encontrado. {contagem}",
        ),
        MetricValue(
            name="avaliacao_f1",
            value=f1,
            data_type=NUMERIC,
            comment=f"Media harmonica de precisao e revocacao. {contagem}",
        ),
        MetricValue(
            name="avaliacao_igualdade_exata",
            value=1.0 if obtido == esperado else 0.0,
            data_type=BOOLEAN,
            comment=f"Conjunto identico ao esperado. {contagem}",
        ),
    ]


def avaliar_selecao_artefatos(
    obtido: set[str], esperado: set[str]
) -> list[MetricValue]:
    """Compara os artefatos escolhidos como evidencia contra a referencia."""
    return metricas_de_conjunto(obtido, esperado, sobre="artefatos")


def avaliar_mapeamento_canonico(
    obtido: Any, esperado: Any
) -> list[MetricValue]:
    """Avalia um mapeamento canonico em degraus, do campo ate o seletor.

    Os degraus alem da cobertura sao condicionados aos campos presentes nos dois
    lados. Errar o campo ja e penalizado pela cobertura; conta-lo de novo aqui
    misturaria duas causas no mesmo numero.
    """
    mapeamento_obtido = _como_dicionario(obtido)
    mapeamento_esperado = _como_dicionario(esperado)
    caminhos_obtidos = set(mapeamento_obtido)
    caminhos_esperados = set(mapeamento_esperado)

    metricas = metricas_de_conjunto(
        caminhos_obtidos, caminhos_esperados, sobre="campos mapeados"
    )
    if not metricas:
        return metricas

    comuns = sorted(caminhos_obtidos & caminhos_esperados)
    if not comuns:
        # Sem campo em comum nao ha o que comparar instrucao a instrucao. Emitir
        # zero aqui diria "errou tudo" quando o certo e "nao se aplica".
        return metricas

    instrucoes = [
        (
            _normalizar_instrucao(mapeamento_obtido[caminho]),
            _normalizar_instrucao(mapeamento_esperado[caminho]),
        )
        for caminho in comuns
    ]

    tipos_certos = sum(
        1
        for atual, referencia in instrucoes
        if atual.get("tipo_origem") == referencia.get("tipo_origem")
    )
    metricas.append(
        MetricValue(
            name="avaliacao_acerto_tipo_origem",
            value=_taxa(tipos_certos, len(comuns)),
            data_type=NUMERIC,
            comment=(
                "Estrategia de extracao correta entre os campos mapeados nos dois "
                f"lados. {tipos_certos} de {len(comuns)} campos."
            ),
        )
    )

    com_arquivo = [
        (atual, referencia)
        for atual, referencia in instrucoes
        if referencia.get("tipo_origem") not in _SEM_ARQUIVO_DE_ORIGEM
        and referencia.get("arquivo_origem")
    ]
    if com_arquivo:
        arquivos_certos = sum(
            1
            for atual, referencia in com_arquivo
            if atual.get("arquivo_origem") == referencia.get("arquivo_origem")
        )
        metricas.append(
            MetricValue(
                name="avaliacao_acerto_arquivo_origem",
                value=_taxa(arquivos_certos, len(com_arquivo)),
                data_type=NUMERIC,
                comment=(
                    "Arquivo de evidencia correto entre os campos que leem arquivo. "
                    f"{arquivos_certos} de {len(com_arquivo)} campos."
                ),
            )
        )

    instrucoes_certas = sum(
        1 for atual, referencia in instrucoes if atual == referencia
    )
    metricas.append(
        MetricValue(
            name="avaliacao_acerto_instrucao_origem",
            value=_taxa(instrucoes_certas, len(comuns)),
            data_type=NUMERIC,
            comment=(
                "Instrucao de origem identica a referencia, seletor de linha e "
                f"coluna incluidos. {instrucoes_certas} de {len(comuns)} campos."
            ),
        )
    )
    return metricas


def metrica_de_validade(
    *, valido: bool, motivo: str | None = None
) -> MetricValue:
    """Registra se o candidato passaria pelas regras de negocio da producao.

    Sem isso, uma resposta que a DAG rejeitaria pode tirar F1 alto no dataset: a
    comparacao de conjuntos nao sabe nada sobre contrato, escopo ou seletor
    obrigatorio de array.
    """
    return MetricValue(
        name="avaliacao_candidato_valido",
        value=1.0 if valido else 0.0,
        data_type=BOOLEAN,
        comment=motivo or "Candidato aceito pelas mesmas regras aplicadas na DAG.",
    )

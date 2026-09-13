"""Testes da avaliacao off-line por etapa.

Uma metrica sem teste e uma metrica em que nao se pode confiar para reprovar o
trabalho de alguem, entao cada degrau tem um caso que so ele detecta.
"""

from __future__ import annotations

from document_processing.domain.observability import (
    avaliar_mapeamento_canonico,
    avaliar_selecao_artefatos,
    metrica_de_validade,
)


def _por_nome(metricas):
    return {metrica.name: metrica.value for metrica in metricas}


def _celula(arquivo: str, linha: str, coluna: int) -> dict:
    return {
        "tipo_origem": "celula_de_tabela",
        "arquivo_origem": arquivo,
        "obrigatorio": True,
        "seletor_linha": {"valor_aceito": linha, "coluna_rotulo": 0},
        "seletor_coluna": {"indice_coluna_esperado": coluna},
    }


def test_selecao_sem_referencia_nao_emite_metrica():
    """Sem `expectedOutput` nao ha o que comparar; zero seria mentira."""
    assert avaliar_selecao_artefatos({"tables/t1.json"}, set()) == []


def test_precisao_e_revocacao_separam_erros_diferentes():
    """Escolher 1 certo entre 2 nao e o mesmo que achar 1 de 2 esperados."""
    valores = _por_nome(
        avaliar_selecao_artefatos({"a", "x"}, {"a", "b"})
    )
    assert valores["avaliacao_precisao"] == 0.5
    assert valores["avaliacao_revocacao"] == 0.5
    assert valores["avaliacao_f1"] == 0.5
    assert valores["avaliacao_igualdade_exata"] == 0.0


def test_cobertura_perfeita_com_estrategia_errada_e_detectada():
    """O degrau de cobertura nao ve `tipo_origem`; o degrau seguinte ve."""
    esperado = {"campo.a": _celula("tables/table002.json", "Unidades", 1)}
    obtido = {
        "campo.a": {
            "tipo_origem": "campo_json",
            "arquivo_origem": "tables/table002.json",
            "obrigatorio": True,
            "caminho_json": "dados.valor",
        }
    }
    valores = _por_nome(avaliar_mapeamento_canonico(obtido, esperado))
    assert valores["avaliacao_f1"] == 1.0
    assert valores["avaliacao_igualdade_exata"] == 1.0
    assert valores["avaliacao_acerto_tipo_origem"] == 0.0
    assert valores["avaliacao_acerto_instrucao_origem"] == 0.0


def test_seletor_errado_e_invisivel_ate_o_degrau_da_instrucao():
    """Campo, estrategia e arquivo certos, celula errada: o dado sai errado."""
    esperado = {"campo.a": _celula("tables/table002.json", "Unidades", 1)}
    obtido = {"campo.a": _celula("tables/table002.json", "Unidades", 3)}
    valores = _por_nome(avaliar_mapeamento_canonico(obtido, esperado))
    assert valores["avaliacao_f1"] == 1.0
    assert valores["avaliacao_acerto_tipo_origem"] == 1.0
    assert valores["avaliacao_acerto_arquivo_origem"] == 1.0
    assert valores["avaliacao_acerto_instrucao_origem"] == 0.0


def test_instrucao_identica_pontua_todos_os_degraus():
    esperado = {"campo.a": _celula("tables/table002.json", "Unidades", 1)}
    valores = _por_nome(avaliar_mapeamento_canonico(dict(esperado), esperado))
    assert valores["avaliacao_acerto_tipo_origem"] == 1.0
    assert valores["avaliacao_acerto_arquivo_origem"] == 1.0
    assert valores["avaliacao_acerto_instrucao_origem"] == 1.0


def test_valor_fixo_nao_entra_no_denominador_do_arquivo_de_origem():
    """`valor_fixo` nao le arquivo; conta-lo como acerto inflaria a metrica."""
    esperado = {
        "campo.fixo": {
            "tipo_origem": "valor_fixo",
            "valor_fixo": "Cury",
            "obrigatorio": True,
        }
    }
    metricas = avaliar_mapeamento_canonico(dict(esperado), esperado)
    valores = _por_nome(metricas)
    assert "avaliacao_acerto_arquivo_origem" not in valores
    assert valores["avaliacao_acerto_tipo_origem"] == 1.0


def test_arquivo_errado_entre_tabelas_parecidas():
    esperado = {
        "campo.a": _celula("tables/table003.json", "Unidades", 1),
        "campo.b": _celula("tables/table003.json", "Valor", 1),
    }
    obtido = {
        "campo.a": _celula("tables/table002.json", "Unidades", 1),
        "campo.b": _celula("tables/table003.json", "Valor", 1),
    }
    valores = _por_nome(avaliar_mapeamento_canonico(obtido, esperado))
    assert valores["avaliacao_acerto_arquivo_origem"] == 0.5
    assert valores["avaliacao_acerto_tipo_origem"] == 1.0


def test_default_omitido_nao_vira_diferenca_falsa():
    """`obrigatorio` ausente de um lado e `false` do outro sao a mesma coisa."""
    esperado = {"campo.a": {"tipo_origem": "valor_fixo", "valor_fixo": "X"}}
    obtido = {
        "campo.a": {
            "tipo_origem": "valor_fixo",
            "valor_fixo": "X",
            "obrigatorio": False,
            "arquivo_origem": None,
        }
    }
    valores = _por_nome(avaliar_mapeamento_canonico(obtido, esperado))
    assert valores["avaliacao_acerto_instrucao_origem"] == 1.0


def test_sem_campo_em_comum_nao_emite_degraus_condicionados():
    """Sem intersecao nao ha instrucao a comparar: ausente, nao zero."""
    esperado = {"campo.a": _celula("tables/t.json", "Unidades", 1)}
    obtido = {"campo.z": _celula("tables/t.json", "Unidades", 1)}
    valores = _por_nome(avaliar_mapeamento_canonico(obtido, esperado))
    assert valores["avaliacao_f1"] == 0.0
    assert "avaliacao_acerto_tipo_origem" not in valores
    assert "avaliacao_acerto_instrucao_origem" not in valores


def test_metrica_de_validade_carrega_o_motivo_da_reprovacao():
    metrica = metrica_de_validade(valido=False, motivo="campo fora do schema_saida")
    assert metrica.value == 0.0
    assert metrica.data_type == "BOOLEAN"
    assert "schema_saida" in metrica.comment

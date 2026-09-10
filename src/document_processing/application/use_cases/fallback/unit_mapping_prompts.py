from __future__ import annotations

from typing import Any

# Aqui o escopo e uma frase dentro de um texto maior, e nao um texto inteiro como
# no candidato. Entao o bloco versionado e o gabarito, com a frase entrando por
# variavel: cada frase tambem e versionada, sem duplicar o texto que as cerca.
UNIT_MAPPING_SCOPE_TEMPLATE = (
    "Nesta chamada, os paths e o subesquema recebidos delimitam toda a tarefa de "
    "mapeamento. Produza instrucoes deterministicas para todos e somente esses "
    "paths. Quando um path representar uma colecao tabular, use uma unica "
    "instrucao linhas_de_tabela no path da colecao, nunca uma entrada por linha "
    "ou por campo interno. "
    "{{instrucao_escopo}} Nao crie valores finais, identidade do documento, versao, "
    "publicacao, contrato ou regras operacionais; esses elementos sao preenchidos "
    "deterministicamente fora desta chamada."
)

UNIT_MAPPING_SCOPE_SENTENCES: dict[str, str] = {
    "correcao_parcial_mapeamento": (
        "Corrija exclusivamente os paths recebidos e preserve a semantica definida "
        "pelo subcontrato."
    ),
    "regeneracao_total_mapeamento": (
        "Reconstrua os mapeamentos recebidos exclusivamente a partir das evidencias "
        "atuais."
    ),
    "criacao_inicial_layout": (
        "Crie os mapeamentos recebidos exclusivamente a partir das evidencias atuais."
    ),
}

# Escopo desconhecido sempre caiu na frase de criacao; preservado explicitamente.
UNIT_MAPPING_SCOPE_PADRAO = "criacao_inicial_layout"


def unit_mapping_scope_sentence(scope: str) -> str:
    """Frase que particulariza o gabarito de escopo por tipo de correcao."""
    return UNIT_MAPPING_SCOPE_SENTENCES.get(
        scope, UNIT_MAPPING_SCOPE_SENTENCES[UNIT_MAPPING_SCOPE_PADRAO]
    )


def unit_mapping_scope_instruction(scope: str) -> str:
    """Abre uma chamada por unidade como uma tarefa completa de mapeamento."""
    return UNIT_MAPPING_SCOPE_TEMPLATE.replace(
        "{{instrucao_escopo}}", unit_mapping_scope_sentence(scope)
    )


def unit_mapping_structure_instruction() -> str:
    """Explica a estrutura executavel de uma resposta de unidade."""
    return (
        "O proximo objeto e um exemplo da estrutura obrigatoria da resposta. Trate-o "
        "como modelo de forma, nunca como evidencia do documento. Cada valor de "
        "mapeamento_canonico deve ser uma instrucao executavel e conter tipo_origem; "
        "nao use descricoes como tipo_estrutura, fonte, tabela, coluna ou celula no "
        "lugar de tipo_origem. Os unicos tipos aceitos estao listados no exemplo. "
        "Para celula_de_tabela, use seletor_linha.indice_linha_esperado e "
        "seletor_coluna.indice_coluna_esperado. Para cabecalho_de_tabela, use "
        "seletor_coluna.indice_coluna_esperado. Para linhas_de_tabela que preenche "
        "uma colecao inteira, mapeie o path da colecao sem filtro e declare segmentos "
        "ou faixas_linhas, mais campos que relacionem cada indice_coluna ao campo do "
        "item. Cada campo deve ter somente caminho_saida, indice_coluna e, opcionalmente, "
        "tipo texto ou numero. Nao use nome, derivacao, valor_constante ou tipo derivado "
        "dentro de campos. Valores repetidos pertencem a valores_por_segmento ou valores_fixos "
        "da instrucao. Para tabelas, "
        "nao use regex nem padrao_cabecalho_aceito; o resolvedor le as posicoes "
        "indicadas. Regex e reservado a bloco_textual."
    )


def unit_mapping_artifacts_instruction() -> str:
    """Instrui o uso dos artefatos como evidencia completa da chamada."""
    return (
        "Os proximos artefatos sao toda a evidencia disponivel para esta chamada. "
        "Use somente arquivos presentes nesse bloco e escolha indices, rotulos e "
        "faixas que estejam realmente observados neles. Uma instrucao de tabela deve "
        "referenciar arquivo_origem e os indices necessarios para o resolvedor. Nao "
        "invente arquivos, campos ou valores. Se uma colecao inteira for preenchida "
        "por linhas_de_tabela, use diretamente o path da colecao. Se o mapeamento "
        "atingir somente um item de um array, use seletor explicito entre colchetes. Se um "
        "requisito obrigatorio nao estiver comprovado, registre-o em campos_nao_mapeados com path, "
        "seletores, motivo e artefatos_verificados; nao invente mapeamento para ele. A ausencia "
        "de uma observacao com obrigatorio=false nao deve ser registrada como erro."
    )


def unit_mapping_final_instruction() -> str:
    """Fecha a chamada com o envelope tecnico minimo exigido pelo consolidado."""
    return (
        "Agora responda somente com um objeto JSON valido. No nivel raiz inclua "
        "exatamente tipo_artefato com o valor fragmento_layout_signature, "
        "unidade_mapeamento com o identificador recebido, campos_nao_mapeados, mapeamento_canonico, "
        "fontes_relevantes e metadados_estruturais_evidencia. Mapeie todos e somente "
        "os paths permitidos desta chamada. campos_nao_mapeados deve ser uma lista; cada "
        "item precisa de path, seletores, motivo e artefatos_verificados. Nao inclua markdown, explicacoes, valores "
        "finais, versao, publicacao, contrato ou outros envelopes."
    )


def unit_mapping_repair_instruction() -> str:
    """Instrui uma correcao localizada sem perder o contrato completo de forma."""
    return (
        "A resposta anterior foi rejeitada pela validacao deterministica. Leia "
        "correcao_mapeamento.erro_validacao e correcao_mapeamento.resposta_invalida. "
        "Corrija somente o necessario, preserve instrucoes validas e responda de novo "
        "com o objeto JSON completo exigido nesta chamada. O erro nao autoriza criar "
        "paths fora do subesquema, inventar tipos de origem ou omitir tipo_origem."
    )


def unit_mapping_structure_example(*, unit_id: str) -> dict[str, Any]:
    """Modelo neutro de resposta, sem dados nem terminologia de um dominio real."""
    return {
        "tipos_origem_permitidos": [
            "valor_fixo",
            "campo_derivado",
            "campo_json",
            "bloco_textual",
            "cabecalho_de_tabela",
            "celula_de_tabela",
            "linhas_de_tabela",
            "juncao_de_registros_json",
        ],
        "formatos_de_origem": {
            "celula_de_tabela": {
                "tipo_origem": "celula_de_tabela",
                "arquivo_origem": "tables/table001.json",
                "seletor_linha": {"indice_linha_esperado": 2},
                "seletor_coluna": {"indice_coluna_esperado": 4},
                "obrigatorio": True,
            },
            "linhas_de_tabela": {
                "tipo_origem": "linhas_de_tabela",
                "arquivo_origem": "tables/table001.json",
                "segmentos": [
                    {
                        "linha_inicial": 1,
                        "linha_final": 12,
                        "valores_por_segmento": {"categoria": "observada"},
                    }
                ],
                "campos": [
                    {"caminho_saida": "identificador", "indice_coluna": 0},
                    {"caminho_saida": "valor", "indice_coluna": 3, "tipo": "numero"},
                ],
                "obrigatorio": True,
            },
            "cabecalho_de_tabela": {
                "tipo_origem": "cabecalho_de_tabela",
                "arquivo_origem": "tables/table001.json",
                "seletor_coluna": {"indice_coluna_esperado": 1},
                "obrigatorio": True,
            },
            "valor_fixo": {
                "tipo_origem": "valor_fixo",
                "valor_fixo": "valor declarado pelo contrato ou pela evidencia",
                "obrigatorio": True,
            },
            "bloco_textual": {
                "tipo_origem": "bloco_textual",
                "arquivo_origem": "blocks/blocks.jsonl",
                "padrao": "expressao regular para extrair um valor textual",
                "obrigatorio": True,
            },
            "campo_json": {
                "tipo_origem": "campo_json",
                "arquivo_origem": "arquivo.json",
                "caminho_json": "campo.publicado",
                "obrigatorio": True,
            },
        },
        "formato_campos_nao_mapeados": {
            "path": "colecao.itens.valor",
            "seletores": {"papel_periodo": "referencia"},
            "motivo": "A evidencia recebida nao contem a observacao exigida.",
            "artefatos_verificados": ["tables/table001.json"],
        },
        "modelo_resposta": {
            "tipo_artefato": "fragmento_layout_signature",
            "unidade_mapeamento": unit_id,
            "campos_nao_mapeados": [],
            "mapeamento_canonico": {
                "colecao.itens": {
                    "tipo_origem": "linhas_de_tabela",
                    "arquivo_origem": "tables/table001.json",
                    "faixas_linhas": [{"linha_inicial": 1, "linha_final": 12}],
                    "campos": [
                        {"caminho_saida": "codigo", "indice_coluna": 0},
                        {"caminho_saida": "valor", "indice_coluna": 4, "tipo": "numero"},
                    ],
                    "obrigatorio": True,
                }
            },
            "fontes_relevantes": {},
            "metadados_estruturais_evidencia": {},
        },
    }

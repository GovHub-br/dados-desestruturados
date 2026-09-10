"""Gera assinaturas determinísticas por competência para a série ABECIP carregada.

O script não infere conteúdo de PDF. As diferenças físicas foram revisadas nos
artefatos Docling e ficam explícitas nas assinaturas produzidas: arquivo de
tabela, intervalo de linhas, anos e blocos de modalidade.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE_LAYOUT = ROOT / "resultados_construtoras/abecip/layout_signature_abecip_deterministico.json"
OUTPUT_DIR = ROOT / "resultados_construtoras/abecip/assinaturas_layout_por_periodo"

DOCUMENTS = {
    "2025-10": ("data-abecip-2025-10.pdf", "333bfce55e489da938d9949e1755e926"),
    "2025-11": ("data-abecip-2025-11.pdf", "daab4b8eb20d79db7644701c8c790039"),
    "2025-12": ("data-abecip-2025-12-novo.pdf", "bd7691242d479c60e280bfe02f3a8462"),
    "2026-01": ("data-abecip-2026-01.pdf", "a42218bf285b49a68a18ee76de458bd4"),
    "2026-02": ("data-abecip-2026-02.pdf", "b6337c4c1ee886998ff8a013f188a7b3"),
    "2026-03": ("data-abecip-2026-03.pdf", "03df95a8421f04f9f14fbcb2b1805517"),
    "2026-04": ("data-abecip-2026-04.pdf", "d05f95fea34bf842341ec3b8b8543224"),
    "2026-05": ("data-abecip-2026-05.pdf", "654f34190fc89bf63e34012b0122c3c8"),
    "2026-06": ("abecip_28_07.pdf", "d34c60cc3db2e7f20846932e2790c130"),
    "2026-07": ("data-abecip-2026-07.pdf", "06e9e55b568c14511ece52810d48c859"),
}

MONTHS = ("Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez")
MONTH_OCR_REPAIRS = {
    "1no": "Out",
    "imr": "Jul",
    "Imr": "Jul",
    "Im": "Jul",
    "im": "Jul",
    "m": "Jul",
}


def _month_field(*, output_path: str | None = None) -> dict[str, object]:
    field: dict[str, object] = {"indice_coluna": 0, "substituicoes": MONTH_OCR_REPAIRS}
    if output_path:
        field["caminho_saida"] = output_path
    else:
        field["nome"] = "mes"
    return field


def _fields_monthly(units_column: int, volume_column: int) -> list[dict[str, object]]:
    return [
        _month_field(),
        {"nome": "unidades_financiadas", "indice_coluna": units_column, "tipo": "numero"},
        {"nome": "volume_financiado_milhoes", "indice_coluna": volume_column, "tipo": "numero"},
    ]


def _fields_savings(saldo_column: int, captacao_column: int) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    common = [_month_field()]
    return (
        [*common, {"nome": "saldo_milhoes", "indice_coluna": saldo_column, "tipo": "numero"}],
        [*common, {"nome": "captacao_liquida_milhoes", "indice_coluna": captacao_column, "tipo": "numero"}],
    )


def _monthly_mapping(
    source: str,
    prior_year: int,
    current_year: int,
    current_last_row: int,
    *,
    kind: str,
) -> tuple[dict[str, object], dict[str, object], dict[str, object] | None]:
    if kind == "financiamentos":
        first_fields = _fields_monthly(1, 4)
        second_fields = _fields_monthly(7, 10)
        observed_fields = [
            _month_field(),
            _month_field(output_path="periodo.rotulo_publicado"),
            {"nome": "unidades_financiadas", "indice_coluna": 8, "tipo": "numero"},
            {"nome": "volume_financiado_milhoes", "indice_coluna": 11, "tipo": "numero"},
        ]
    else:
        first_fields, _ = _fields_savings(1, 5)
        second_fields, _ = _fields_savings(7, 11)
        _, first_capture = _fields_savings(1, 5)
        _, second_capture = _fields_savings(7, 11)
        observed_fields = [
            _month_field(),
            _month_field(output_path="periodo.rotulo_publicado"),
            {"nome": "captacao_liquida_milhoes", "indice_coluna": 13, "tipo": "numero"},
        ]
        saldo = {
            "tipo_origem": "linhas_de_tabela",
            "arquivo_origem": source,
            "segmentos": [
                {"linha_inicial": 0, "linha_final": 11, "valores_por_segmento": {"ano": prior_year}, "campos": first_fields},
                {"linha_inicial": 0, "linha_final": current_last_row, "valores_por_segmento": {"ano": current_year}, "campos": second_fields},
            ],
        }
        capture = copy.deepcopy(saldo)
        capture["segmentos"][0]["campos"] = first_capture
        capture["segmentos"][1]["campos"] = second_capture
        observed = {
            "tipo_origem": "linhas_de_tabela",
            "arquivo_origem": source,
            "linha_inicial": 0,
            "linha_final": current_last_row,
            "valores_por_segmento": {"ano": current_year, "periodo": {"tipo_periodo": "acumulado_ano"}},
            "campos": observed_fields,
        }
        return saldo, capture, observed

    monthly = {
        "tipo_origem": "linhas_de_tabela",
        "arquivo_origem": source,
        "segmentos": [
            {"linha_inicial": 0, "linha_final": 11, "valores_por_segmento": {"ano": prior_year}, "campos": first_fields},
            {"linha_inicial": 0, "linha_final": current_last_row, "valores_por_segmento": {"ano": current_year}, "campos": second_fields},
        ],
    }
    observed = {
        "tipo_origem": "linhas_de_tabela",
        "arquivo_origem": source,
        "linha_inicial": 0,
        "linha_final": current_last_row,
        "valores_por_segmento": {"ano": current_year, "periodo": {"tipo_periodo": "acumulado_ano"}},
        "campos": observed_fields,
    }
    return monthly, observed, None


def _institution_fields() -> list[dict[str, object]]:
    return [
        {"nome": "instituicao_financeira", "indice_coluna": 0},
        {"nome": "volume_mensal_milhoes", "indice_coluna": 1, "tipo": "numero"},
        {"nome": "unidades_mensais", "indice_coluna": 2, "tipo": "numero"},
        {"nome": "volume_acumulado_ano_milhoes", "indice_coluna": 3, "tipo": "numero"},
        {"nome": "unidades_acumuladas_ano", "indice_coluna": 4, "tipo": "numero"},
    ]


def _institution_source(source: str, start: int, end: int, modality: str, period: str) -> dict[str, object]:
    return {
        "arquivo_origem": source,
        "linha_inicial": start,
        "linha_final": end,
        "valores_por_segmento": {"modalidade": modality, "periodo": {"rotulo_publicado": period, "tipo_periodo": "mensal"}},
        "campos": _institution_fields(),
    }


def _layout_for(period: str) -> dict[str, object]:
    layout = json.loads(BASE_LAYOUT.read_text(encoding="utf-8"))
    year, month = period.split("-")
    month_index = int(month) - 1
    filename, document_id = DOCUMENTS[period]
    layout["versao_artefato"] = "2.4.0"
    layout["referencia_contrato_semantico"] = {"arquivo": "contrato_semantico_abecip.json", "versao": "2.3.0"}
    layout["documento_origem"] = {"arquivo_pdf": f"abecip/pdfs_para_resolução/{filename}", "document_id": document_id, "competencia_referencia": period}
    mappings = layout["mapeamento_canonico"]
    mappings.pop("recursos_livres.observacoes", None)
    for key in ("metadados_origem.data_publicacao", "metadados_origem.aviso_revisao"):
        mappings[key].pop("block_id", None)

    if year == "2025":
        savings_source, financing_source, historical_source = "tables/table003.json", "tables/table004.json", "tables/table005.json"
        saldo, captacao, obs_savings = _monthly_mapping(savings_source, 2024, 2025, month_index, kind="poupanca")
        monthly, obs_financing, _ = _monthly_mapping(financing_source, 2024, 2025, month_index, kind="financiamentos")
        institution_sources = [
            _institution_source("tables/table006.json", 0, {"2025-10": 9, "2025-11": 9, "2025-12": 9}[period], "construcao", period),
            _institution_source("tables/table007.json", 0, {"2025-10": 10, "2025-11": 10, "2025-12": 10}[period], "aquisicao", period),
            _institution_source("tables/table008.json", 0, {"2025-10": 11, "2025-11": 11, "2025-12": 11}[period], "total_aquisicao_construcao", period),
        ]
        historical_columns = (2, 4)
    elif period in {"2026-05", "2026-06"}:
        savings_source, financing_source, historical_source = "tables/table002.json", "tables/table003.json", "tables/table004.json"
        saldo, captacao, obs_savings = _monthly_mapping(savings_source, 2025, 2026, month_index, kind="poupanca")
        monthly, obs_financing, _ = _monthly_mapping(financing_source, 2025, 2026, month_index, kind="financiamentos")
        institution_sources = [
            _institution_source("tables/table005.json", *bound, modality, period)
            for bound, modality in zip(
                ((1, 10), (12, 22), (24, 35)),
                ("construcao", "aquisicao", "total_aquisicao_construcao"),
                strict=True,
            )
        ]
        historical_columns = (1, 3)
    elif period == "2026-07":
        savings_source, financing_source, historical_source = "tables/table003.json", "tables/table003.json", "tables/table004.json"
        saldo, captacao, obs_savings = _monthly_mapping(savings_source, 2025, 2026, month_index, kind="poupanca")
        monthly, obs_financing, _ = _monthly_mapping(financing_source, 2025, 2026, month_index, kind="financiamentos")
        for segment in monthly["segmentos"]:
            segment["linha_inicial"] += 13
            segment["linha_final"] += 13
        obs_financing["linha_inicial"] += 13
        obs_financing["linha_final"] += 13
        institution_sources = [
            _institution_source("tables/table005.json", 1, 12, "construcao", period),
            _institution_source("tables/table005.json", 14, 26, "aquisicao", period),
            _institution_source("tables/table005.json", 28, 41, "total_aquisicao_construcao", period),
        ]
        historical_columns = (1, 3)
    else:
        savings_source, financing_source, historical_source = "tables/table003.json", "tables/table004.json", "tables/table005.json"
        saldo, captacao, obs_savings = _monthly_mapping(savings_source, 2025, 2026, month_index, kind="poupanca")
        monthly, obs_financing, _ = _monthly_mapping(financing_source, 2025, 2026, month_index, kind="financiamentos")
        if period == "2026-03":
            institution_sources = [
                _institution_source("tables/table006.json", 0, 6, "construcao", period),
                _institution_source("tables/table007.json", 0, 10, "aquisicao", period),
                _institution_source("tables/table008.json", 0, 10, "total_aquisicao_construcao", period),
            ]
        else:
            bounds = {
                "2026-01": ((1, 7), (9, 19), (21, 31)),
                "2026-02": ((1, 7), (9, 19), (21, 31)),
                "2026-04": ((1, 9), (11, 21), (23, 34)),
            }[period]
            institution_sources = [
                _institution_source("tables/table006.json", *bound, modality, period)
                for bound, modality in zip(bounds, ("construcao", "aquisicao", "total_aquisicao_construcao"), strict=True)
            ]
        historical_columns = (1, 3)

    mappings["poupanca_sbpe.saldos_mensais"] = saldo
    mappings["poupanca_sbpe.captacoes_liquidas_mensais"] = captacao
    mappings["poupanca_sbpe.observacoes_publicadas"] = obs_savings
    mappings["financiamentos_imobiliarios.serie_mensal_sbpe"] = monthly
    mappings["financiamentos_imobiliarios.observacoes_publicadas_sbpe"] = obs_financing
    mappings["financiamentos_imobiliarios.serie_historica_anual"] = {
        "tipo_origem": "linhas_de_tabela",
        "arquivo_origem": historical_source,
        "linha_inicial": 0,
        "linha_final": 15,
        "campos": [
            {"nome": "ano", "indice_coluna": 0, "tipo": "numero"},
            {"nome": "unidades_financiadas", "indice_coluna": historical_columns[0], "tipo": "numero"},
            {"nome": "volume_financiado_milhoes", "indice_coluna": historical_columns[1], "tipo": "numero"},
        ],
    }
    mappings["financiamentos_imobiliarios.por_modalidade_e_instituicao"] = {
        "tipo_origem": "linhas_de_tabelas",
        "fontes": institution_sources,
    }
    reference_row_label = "1no" if period == "2025-10" else MONTHS[month_index]
    layout["regras_deteccao_mudanca"] = [
        {"id_regra": f"ARQ_{index}", "tipo_teste": "arquivo_existe", "arquivo_origem": source, "codigo_falha": "FALHA_TABELA_CRITICA_AUSENTE"}
        for index, source in enumerate(sorted({s for s in (savings_source, financing_source, historical_source, *(item["arquivo_origem"] for item in institution_sources))}), start=1)
    ] + [{"id_regra": "ROW_MES_REFERENCIA", "tipo_teste": "linha_existe_em_tabela", "arquivo_origem": financing_source, "coluna_rotulo": 0, "valores_aceitos": [reference_row_label], "codigo_falha": "FALHA_LINHA_CRITICA_AUSENTE"}]
    layout["fontes_relevantes"] = {"tabelas_primarias": [{"arquivo": source} for source in sorted({s for s in (savings_source, financing_source, historical_source, *(item["arquivo_origem"] for item in institution_sources))})]}
    return layout


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for period in DOCUMENTS:
        target = OUTPUT_DIR / f"layout_signature_abecip_{period}.json"
        target.write_text(json.dumps(_layout_for(period), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(target)


if __name__ == "__main__":
    main()

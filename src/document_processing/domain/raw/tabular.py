"""Linhas tabulares compativeis com os arquivos raw existentes."""

from __future__ import annotations

import math
import re
from typing import Any


def list_at(payload: dict, *path: str) -> list[dict]:
    value: Any = payload
    for key in path:
        if not isinstance(value, dict):
            raise ValueError(f"Estrutura invalida em {'.'.join(path)}.")
        if key not in value or value[key] is None:
            return []
        value = value[key]
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError(f"Esperada lista de registros em {'.'.join(path)}.")
    return value


def numeric_value(value: Any) -> int | float | None:
    if isinstance(value, dict):
        value = value.get("valor")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"Valor numerico invalido na saida resolvida: {value!r}")
    return value


def normalize_quarter(value: Any) -> str:
    label = str(value or "").strip()
    match = re.match(r"^([1-4]T\d{2})\b", label)
    if not match:
        raise ValueError(f"Periodo trimestral invalido: {label!r}")
    return match.group(1)


def abecip_competence(schema: dict, manifest: dict) -> str:
    root = schema.get("competencia_referencia") or {}
    label = root.get("rotulo_publicado") or manifest.get("candidate", {}).get("period_label")
    if not isinstance(label, str) or not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", label):
        raise ValueError("Competencia mensal ausente no schema e no manifesto de extracao.")
    return label


def _period(item: dict) -> dict:
    value = item.get("periodo") or {}
    if not isinstance(value, dict):
        raise ValueError("Periodo da observacao deve ser um objeto.")
    return value


def _year_month(item: dict, competence: str) -> dict:
    label = str(_period(item).get("rotulo_publicado") or "")
    iso = re.fullmatch(r"(20\d{2})-(0[1-9]|1[0-2])", label)
    year = item.get("ano")
    if year is None:
        year = int(iso.group(1)) if iso else int(competence[:4])
    month = item.get("mes") or label
    if not month:
        raise ValueError("Observacao mensal sem rotulo de mes.")
    return {"ano": year, "mes": month}


def abecip_rows(schema: dict, base: dict) -> dict[str, list[dict]]:
    """Mantem as seis tabelas existentes e aceita schemas antigos e atuais."""
    competence = base["competencia_referencia"]
    for collection in ("serie_mensal_sbpe", "serie_historica_anual", "por_modalidade_e_instituicao"):
        if not list_at(schema, "financiamentos_imobiliarios", collection):
            raise ValueError(f"Schema ABECIP sem a colecao obrigatoria {collection}.")
    tables = {}
    for table, path, columns in (
        ("financiamentos_sbpe_mensal", ("financiamentos_imobiliarios", "serie_mensal_sbpe"),
         ("unidades_financiadas", "volume_financiado_milhoes")),
        ("poupanca_saldos_mensais", ("poupanca_sbpe", "saldos_mensais"), ("saldo_milhoes",)),
        ("poupanca_captacoes_mensais", ("poupanca_sbpe", "captacoes_liquidas_mensais"), ("captacao_liquida_milhoes",)),
    ):
        tables[table] = [
            {**base, **_year_month(item, competence), **{column: numeric_value(item.get(column)) for column in columns}}
            for item in list_at(schema, *path)
        ]
    annual = []
    for item in list_at(schema, "financiamentos_imobiliarios", "serie_historica_anual"):
        year = item.get("ano")
        if year is None:
            label = str(_period(item).get("rotulo_publicado") or "")
            if not re.fullmatch(r"20\d{2}|19\d{2}", label):
                raise ValueError(f"Ano da serie anual invalido: {label!r}")
            year = int(label)
        annual.append({
            **base, "ano": year,
            "unidades_financiadas": numeric_value(item.get("unidades_financiadas")),
            "volume_financiado_milhoes": numeric_value(item.get("volume_financiado_milhoes")),
        })
    tables["financiamentos_historico_anual"] = annual
    tables["financiamentos_por_instituicao"] = [
        {
            **base,
            "periodo_rotulo": _period(item).get("rotulo_publicado"),
            "tipo_periodo": _period(item).get("tipo_periodo"),
            "modalidade": item.get("modalidade"),
            "instituicao_financeira": item.get("instituicao_financeira"),
            **{column: numeric_value(item.get(column)) for column in (
                "volume_mensal_milhoes", "unidades_mensais",
                "volume_acumulado_ano_milhoes", "unidades_acumuladas_ano",
            )},
        }
        for item in list_at(schema, "financiamentos_imobiliarios", "por_modalidade_e_instituicao")
    ]
    resources = schema.get("recursos_livres") or {}
    tables["recursos_livres"] = [
        {
            **base,
            "periodo_rotulo": _period(item).get("rotulo_publicado"),
            "tipo_periodo": _period(item).get("tipo_periodo"),
            "volume_financiado_bilhoes": numeric_value(item.get("volume_financiado_bilhoes")),
            "unidades_financiadas_mil": numeric_value(item.get("unidades_financiadas_mil")),
        }
        for item in list_at(resources, "observacoes")
    ]
    return tables


def resolved_metric_rows(schema: dict, operation: str) -> list[dict]:
    section = schema.get("balancos_das_empresas", {}).get(operation, {})
    return [
        {"empresa": item.get("empresa"), **value}
        for item in list_at(section, "dados")
        for value in list_at(item, "valores")
    ]


def role_for_period(period: Any, periods: dict) -> str | None:
    return next((role for role, label in periods.items() if label is not None and label == period), None)


def construtoras_rows(schema: dict, base: dict) -> dict[str, list[dict]]:
    tables = {}
    periods = schema.get("periodos_disponiveis") or {}
    for operation in ("lancamentos", "vendas"):
        section = schema.get("balancos_das_empresas", {}).get(operation, {})
        if (section.get("tipo") != "valor_bruto"
                or section.get("indicador") != "numero_de_unidades"
                or section.get("unidade") != "unidades"
                or section.get("tipo_operacao") != {"lancamentos": "lancamento", "vendas": "venda"}[operation]):
            raise ValueError(f"Metadados de {operation} fora do contrato de valores brutos em unidades.")
        rows = []
        for item in resolved_metric_rows(schema, operation):
            period = item.get("periodo")
            if not isinstance(period, str) or not period:
                raise ValueError(f"Observacao de {operation} sem periodo.")
            rows.append({
                "fonte": schema.get("fonte"),
                "periodo_referencia": base["periodo_referencia"],
                "indicador": section.get("indicador"),
                "unidade": section.get("unidade"),
                "tipo": section.get("tipo"),
                "tipo_operacao": section.get("tipo_operacao"),
                **{field: base[field] for field in (
                    "document_id", "execution_id", "source_pdf_uri", "source_schema_object_key", "exportado_em",
                )},
                "empresa": item.get("empresa"),
                "periodo": period,
                "papel_periodo": item.get("papel_periodo") or role_for_period(period, periods),
                "escopo_periodo": item.get("escopo_periodo"),
                "valor": numeric_value(item.get("valor")),
            })
        if not rows:
            raise ValueError(f"Schema de construtora sem observacoes de {operation}.")
        tables[operation] = rows
    return tables


def merge_company_rows(existing: list[dict], incoming: list[dict]) -> list[dict]:
    """Substitui as competencias recebidas e preserva o restante do historico."""
    replaced = {normalize_quarter(row["periodo_referencia"]) for row in incoming}
    preserved = [
        row for row in existing if normalize_quarter(row.get("periodo_referencia")) not in replaced
    ]
    return preserved + incoming

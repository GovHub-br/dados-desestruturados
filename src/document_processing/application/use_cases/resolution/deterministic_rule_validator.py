"""Execução das regras determinísticas de validação de layout."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from document_processing.domain.resolution.numbers import parse_flexible_number


class DeterministicRuleValidatorMixin:
    def _execute_rule(
        self,
        rule: dict[str, Any],
        extraction_root: Path,
        contrato: dict[str, Any],
    ) -> dict[str, Any]:
        rule_id = str(rule.get("id_regra", "regra_sem_id"))
        rule_type = str(rule.get("tipo_teste", "desconhecido"))
        origin_file = str(rule.get("arquivo_origem", ""))
        origin_path = extraction_root / origin_file if origin_file else extraction_root
        base = {"id_regra": rule_id, "tipo_teste": rule_type}

        if rule_type == "arquivo_existe":
            exists = origin_path.exists()
            return {
                **base,
                "status": "aprovada" if exists else "reprovada",
                "evidencia": {"arquivo_origem": origin_file, "existe": exists},
            }

        if rule_type == "secao_existe":
            sections = self._read_jsonl(origin_path)
            field = str(rule.get("campo_comparado", "title_canonical"))
            accepted = {str(item) for item in rule.get("valores_aceitos", [])}
            pages = {int(item) for item in rule.get("paginas_aceitas", [])}
            evidences = [
                item
                for item in sections
                if str(item.get(field, "")) in accepted and (not pages or int(item.get("page_number", -1)) in pages)
            ]
            return {
                **base,
                "status": "aprovada" if evidences else "reprovada",
                "evidencias": [
                    {
                        "section_id": item.get("section_id"),
                        "title_canonical": item.get("title_canonical"),
                        "page_number": item.get("page_number"),
                    }
                    for item in evidences
                ],
            }

        if rule_type in {"linha_existe_em_tabela", "perfil_colunas_periodo_existe_em_tabela", "valor_normalizavel"}:
            if not origin_path.exists():
                return {
                    **base,
                    "status": "reprovada",
                    "evidencia": {
                        "arquivo_origem": origin_file,
                        "erro": "arquivo_origem_ausente",
                    },
                }
            table = self._read_json(origin_path)
            if rule_type == "linha_existe_em_tabela":
                label_col = int(rule.get("coluna_rotulo", 0))
                accepted = self._expand_accepted_labels_from_contract(
                    contrato=contrato,
                    values=[str(item) for item in rule.get("valores_aceitos", [])],
                )
                row_index = self._find_row_index(
                    table,
                    accepted,
                    label_col,
                    preferred_row_index=self._optional_int(
                        rule.get("indice_linha_esperado")
                    ),
                )
                return {
                    **base,
                    "status": "aprovada" if row_index is not None else "reprovada",
                    "evidencia": {"arquivo_origem": origin_file, "row_index": row_index},
                }

            if rule_type == "perfil_colunas_periodo_existe_em_tabela":
                schema = list(table.get("schema", []))
                col_results: list[dict[str, Any]] = []
                all_ok = True
                for expected in rule.get("colunas_esperadas", []):
                    idx = int(expected.get("indice_coluna_esperado", -1))
                    header = schema[idx] if idx >= 0 and idx < len(schema) else ""
                    pattern = str(expected.get("padrao_cabecalho_aceito", ".*"))
                    ok = bool(header) and re.search(pattern, header) is not None
                    col_results.append(
                        {
                            "papel_periodo": expected.get("papel_periodo"),
                            "indice_coluna": idx,
                            "cabecalho_encontrado": header or None,
                            "ok": ok,
                        }
                    )
                    all_ok = all_ok and ok
                return {
                    **base,
                    "status": "aprovada" if all_ok else "reprovada",
                    "evidencia": {"arquivo_origem": origin_file, "papeis_periodo_resolvidos": col_results},
                }

            if rule_type == "valor_normalizavel":
                label_col = 0
                accepted = self._expand_accepted_labels_from_contract(
                    contrato=contrato,
                    values=[str(rule.get("linha_rotulo", ""))],
                )
                row_index = self._find_row_index(
                    table,
                    accepted,
                    label_col,
                    preferred_row_index=self._optional_int(
                        rule.get("indice_linha_esperado")
                    ),
                )
                idx = int(rule.get("indice_coluna_esperado", -1))
                raw_value = None
                normalized = None
                if row_index is not None:
                    rows = list(table.get("rows", []))
                    row = rows[row_index] if row_index < len(rows) else []
                    if idx >= 0 and idx < len(row):
                        raw_value = row[idx]
                        normalized = parse_flexible_number(raw_value)
                ok = normalized is not None
                return {
                    **base,
                    "status": "aprovada" if ok else "reprovada",
                    "evidencia": {
                        "arquivo_origem": origin_file,
                        "row_index": row_index,
                        "column_index": idx,
                        "valor_bruto": raw_value,
                        "valor_normalizado": normalized,
                    },
                }

        return {
            **base,
            "status": "reprovada",
            "evidencia": {"erro": f"tipo_teste nao suportado: {rule_type}"},
        }

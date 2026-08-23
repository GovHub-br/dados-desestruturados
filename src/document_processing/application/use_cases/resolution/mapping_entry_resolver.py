"""Despacho de mapeamentos canônicos por ``tipo_origem``.

Este componente não conhece Airflow nem MinIO: recebe a raiz materializada e
delega a leitura concreta aos resolvedores especializados da composição.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any


class MappingEntryResolverMixin:
    """Converte uma entrada de mapeamento em valor e evidência auditável."""

    def _resolve_mapping_entry(
        self,
        *,
        contrato: dict[str, Any],
        mapping_path: str,
        mapping_entry: dict[str, Any],
        extraction_root: Path,
        resolved_by_path: dict[str, Any],
    ) -> dict[str, Any]:
        tipo_origem = str(mapping_entry.get("tipo_origem", "")).strip()
        base = {
            "campo_saida": mapping_path,
            "tipo_origem": tipo_origem,
            "arquivo_origem": mapping_entry.get("arquivo_origem"),
            "obrigatorio": bool(mapping_entry.get("obrigatorio", False)),
        }

        try:
            if tipo_origem == "valor_fixo":
                value = mapping_entry.get("valor_fixo")
                return {
                    **base,
                    "status_resolucao": "resolvido",
                    "valor_resolvido": value,
                    "evidencia": {"valor_fixo": value},
                }

            if tipo_origem == "campo_derivado":
                source_path = str(mapping_entry.get("campo_origem", "")).strip()
                value = resolved_by_path.get(source_path)
                return {
                    **base,
                    "status_resolucao": "resolvido" if value is not None else "nao_resolvido",
                    "valor_resolvido": value,
                    "evidencia": {"campo_origem": source_path},
                }

            if tipo_origem == "campo_json":
                value, evidence = self._resolve_json_field_mapping(extraction_root, mapping_entry)
                return self._mapping_result(base, value, evidence)

            if tipo_origem == "bloco_textual":
                value, evidence = self._resolve_text_block_mapping(extraction_root, mapping_entry)
                return self._mapping_result(base, value, evidence)

            if tipo_origem == "cabecalho_de_tabela":
                value, evidence = self._resolve_table_header_mapping(extraction_root, mapping_entry)
                return self._mapping_result(base, value, evidence)

            if tipo_origem == "celula_de_tabela":
                value, evidence = self._resolve_table_cell_mapping(
                    contrato=contrato,
                    mapping_path=mapping_path,
                    extraction_root=extraction_root,
                    mapping_entry=mapping_entry,
                    resolved_by_path=resolved_by_path,
                )
                output_value = self._project_table_cell_value(
                    mapping_path=mapping_path,
                    resolved_cell=value,
                    raw_value=evidence.get("valor_bruto"),
                )
                return self._mapping_result(
                    base,
                    output_value,
                    evidence,
                    resolved=self._mapping_value_is_resolved(output_value),
                )

            if tipo_origem == "linhas_de_tabela":
                value, evidence = self._resolve_table_rows_mapping(extraction_root, mapping_entry)
                return self._mapping_result(base, value, evidence, resolved=bool(value))

            if tipo_origem == "juncao_de_registros_json":
                value, evidence = self._resolve_json_records_join_mapping(
                    extraction_root,
                    mapping_entry,
                )
                return self._mapping_result(base, value, evidence, resolved=bool(value))
        except Exception as exc:
            logging.exception("Falha ao resolver mapeamento canonico %s", mapping_path)
            return {
                **base,
                "status_resolucao": "erro",
                "valor_resolvido": None,
                "evidencia": {"erro": str(exc)},
            }

        return {
            **base,
            "status_resolucao": "nao_suportado",
            "valor_resolvido": None,
            "evidencia": {"erro": f"tipo_origem nao suportado: {tipo_origem}"},
        }

    @staticmethod
    def _mapping_result(
        base: dict[str, Any],
        value: Any,
        evidence: dict[str, Any],
        *,
        resolved: bool | None = None,
    ) -> dict[str, Any]:
        is_resolved = value is not None if resolved is None else resolved
        return {
            **base,
            "status_resolucao": "resolvido" if is_resolved else "nao_resolvido",
            "valor_resolvido": value,
            "evidencia": evidence,
        }

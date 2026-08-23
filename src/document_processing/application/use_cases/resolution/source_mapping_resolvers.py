from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from document_processing.domain.layouts.paths import parse_mapping_path, set_nested_value
from document_processing.domain.resolution.numbers import parse_flexible_number


class SourceMappingResolversMixin:
    def _resolve_text_block_mapping(
        self,
        extraction_root: Path,
        mapping_entry: dict[str, Any],
    ) -> tuple[str | None, dict[str, Any]]:
        block_file = str(mapping_entry.get("arquivo_origem", "blocks/blocks.jsonl"))
        block_id = str(mapping_entry.get("block_id", "")).strip()
        pattern = str(mapping_entry.get("padrao", r"[1-4]T[0-9]{2}"))
        blocks = self._read_jsonl(extraction_root / block_file)

        for block in blocks:
            if block_id and str(block.get("block_id")) != block_id:
                continue
            text = str(block.get("text", ""))
            match = re.search(pattern, text)
            if match:
                return match.group(0), {
                    "arquivo_origem": block_file,
                    "block_id": block.get("block_id"),
                    "document_id": block.get("document_id"),
                    "page_number": block.get("page_number"),
                    "section_id": block.get("section_id"),
                    "section_title": block.get("section_title"),
                    "bbox": block.get("bbox"),
                    "order_index": block.get("order_index"),
                    "role_hint": block.get("role_hint"),
                    "padrao": pattern,
                    "texto": text,
                }
        return None, {"arquivo_origem": block_file, "block_id": block_id or None, "padrao": pattern}

    def _resolve_json_field_mapping(
        self,
        extraction_root: Path,
        mapping_entry: dict[str, Any],
    ) -> tuple[Any, dict[str, Any]]:
        """Lê um campo de um artefato JSON pelo caminho declarado no layout."""
        origin_file = str(mapping_entry.get("arquivo_origem", "")).strip()
        json_path = str(mapping_entry.get("caminho_json", "")).strip()
        payload = self._read_json(extraction_root / origin_file)
        value: Any = payload
        for key in json_path.split("."):
            if not key or not isinstance(value, dict) or key not in value:
                return None, {"arquivo_origem": origin_file, "caminho_json": json_path}
            value = value[key]

        return value, {
            "arquivo_origem": origin_file,
            "caminho_json": json_path,
        }

    def _resolve_table_header_mapping(
        self,
        extraction_root: Path,
        mapping_entry: dict[str, Any],
    ) -> tuple[str | None, dict[str, Any]]:
        origin_file = str(mapping_entry.get("arquivo_origem", ""))
        table = self._read_json(extraction_root / origin_file)
        table_metadata = self._load_table_metadata(extraction_root, origin_file, table)
        schema = list(table.get("schema", []))
        selector = dict(mapping_entry.get("seletor_coluna", {}))
        idx = int(selector.get("indice_coluna_esperado", -1))
        header = schema[idx] if idx >= 0 and idx < len(schema) else None
        return (str(header) if header is not None else None), {
            "arquivo_origem": origin_file,
            **self._table_structural_evidence(table_metadata),
            "indice_coluna": idx,
            "cabecalho_encontrado": header,
            "papel_periodo": mapping_entry.get("papel_periodo"),
        }

    def _resolve_table_cell_mapping(
        self,
        *,
        contrato: dict[str, Any],
        mapping_path: str,
        extraction_root: Path,
        mapping_entry: dict[str, Any],
        resolved_by_path: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        origin_file = str(mapping_entry.get("arquivo_origem", ""))
        table = self._read_json(extraction_root / origin_file)
        table_metadata = self._load_table_metadata(extraction_root, origin_file, table)
        schema = list(table.get("schema", []))
        rows = list(table.get("rows", []))

        row_selector = dict(mapping_entry.get("seletor_linha", {}))
        column_selector = dict(mapping_entry.get("seletor_coluna", {}))
        label_col = int(row_selector.get("coluna_rotulo", 0))
        accepted = self._expand_accepted_labels_from_contract(
            contrato=contrato,
            values=[str(row_selector.get("valor_aceito", ""))],
            mapping_path=mapping_path,
            resolved_by_path=resolved_by_path,
        )
        row_index = self._find_row_index(
            table,
            accepted,
            label_col,
            preferred_row_index=self._optional_int(
                row_selector.get("indice_linha_esperado")
            ),
        )
        col_idx = int(column_selector.get("indice_coluna_esperado", -1))
        header = schema[col_idx] if col_idx >= 0 and col_idx < len(schema) else None

        raw_value = None
        normalized_value = None
        if row_index is not None and row_index < len(rows):
            row = list(rows[row_index])
            if col_idx >= 0 and col_idx < len(row):
                raw_value = row[col_idx]
                normalized_value = parse_flexible_number(raw_value)

        value = {
            "periodo": str(header) if header is not None else None,
            "escopo_periodo": mapping_entry.get("escopo_periodo") or column_selector.get("escopo_periodo"),
            "valor": normalized_value,
        }
        evidence = {
            "arquivo_origem": origin_file,
            **self._table_structural_evidence(table_metadata),
            "row_index": row_index,
            "column_index": col_idx,
            "linha_rotulo_aceita": row_selector.get("valor_aceito"),
            "linha_rotulo_sinonimos_aceitos": sorted(accepted),
            "cabecalho_encontrado": header,
            "papel_periodo": mapping_entry.get("papel_periodo"),
            "valor_bruto": raw_value,
            "valor_normalizado": normalized_value,
        }
        return value, evidence

    @staticmethod
    def _project_table_cell_value(
        *,
        mapping_path: str,
        resolved_cell: dict[str, Any],
        raw_value: Any,
    ) -> Any:
        """Compatibiliza celulas mapeadas como registro ou como campo terminal.

        Um mapeamento que termina em ``valores[papel=...]`` representa toda a
        observacao e recebe o registro ``periodo``, ``escopo_periodo`` e ``valor``.
        Quando o contrato pede explicitamente um campo terminal, como
        ``...valores[papel=...].valor``, o resolvedor insere apenas esse campo.
        Outros campos de tabela, como ``empresa``, recebem o texto bruto da celula.
        """
        tokens = parse_mapping_path(mapping_path)
        if not tokens:
            return resolved_cell
        terminal_field = str(tokens[-1]["field"])
        if terminal_field == "valores":
            return resolved_cell
        if terminal_field in resolved_cell:
            return resolved_cell[terminal_field]
        return raw_value

    @staticmethod
    def _mapping_value_is_resolved(value: Any) -> bool:
        """Evita considerar uma observacao de tabela vazia como resolvida."""
        if isinstance(value, dict) and "valor" in value:
            return value.get("valor") is not None
        return value is not None

    def _resolve_table_rows_mapping(
        self,
        extraction_root: Path,
        mapping_entry: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Extrai linhas por seletores estruturais ou pelo formato legado com campos nomeados."""
        origin_file = str(mapping_entry.get("arquivo_origem", ""))
        table = self._read_json(extraction_root / origin_file)
        rows = list(table.get("rows", []))
        fields = list(mapping_entry.get("campos", []))
        selectors = self._table_row_selectors(mapping_entry, len(rows))
        result: list[dict[str, Any]] = []
        for selector in selectors:
            start = selector["linha_inicial"]
            end = selector["linha_final"]
            indices_colunas = selector["indices_colunas"]
            selector_fields = selector["campos"] or fields
            for row_index, row in enumerate(rows[start : end + 1], start=start):
                if selector_fields:
                    item = self._table_row_with_named_fields(row, row_index, start, selector_fields)
                else:
                    item = {
                        "indice_linha": row_index,
                        "valores": [
                            {
                                "indice_coluna": column_index,
                                "valor": row[column_index] if column_index < len(row) else None,
                            }
                            for column_index in indices_colunas
                        ],
                    }
                fixed_values = mapping_entry.get("valores_fixos", {})
                if selector_fields and isinstance(fixed_values, dict):
                    item.update(fixed_values)
                segment_values = selector.get("valores_por_segmento", {})
                if selector_fields and isinstance(segment_values, dict):
                    item.update(segment_values)
                result.append(item)
        return result, {
            "arquivo_origem": origin_file,
            "seletores": selectors,
            "linhas_resolvidas": len(result),
        }

    def _resolve_json_records_join_mapping(
        self,
        extraction_root: Path,
        mapping_entry: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Une registros de listas JSON pela chave e campos declarados no layout.

        O resolvedor nao conhece o significado dos campos nem interpreta datas. Cada
        fonte informa onde esta sua chave e quais valores expor no registro final.
        """
        sources = mapping_entry.get("fontes")
        if not isinstance(sources, list) or len(sources) < 2:
            raise ValueError("juncao_de_registros_json requer ao menos duas fontes")

        records_by_source: list[dict[str, dict[str, Any]]] = []
        evidence_sources: list[dict[str, Any]] = []
        for source in sources:
            if not isinstance(source, dict):
                raise ValueError("Fonte de juncao JSON invalida")
            origin_file = str(source.get("arquivo_origem", "")).strip()
            key_path = str(source.get("caminho_chave", "")).strip()
            fields = source.get("campos")
            if not origin_file or not key_path or not isinstance(fields, list):
                raise ValueError("Fonte de juncao JSON exige arquivo_origem, caminho_chave e campos")

            payload = self._read_json_array(extraction_root / origin_file)
            records: dict[str, dict[str, Any]] = {}
            for row_index, source_record in enumerate(payload):
                key_value = self._json_value_at_path(source_record, key_path)
                if key_value is None:
                    continue
                key = str(key_value)
                if key in records:
                    raise ValueError(f"Chave duplicada na juncao JSON: {key} ({origin_file})")

                item: dict[str, Any] = {}
                for field in fields:
                    if not isinstance(field, dict):
                        continue
                    output_path = str(field.get("campo_saida", "")).strip()
                    value_path = str(field.get("caminho_json", "")).strip()
                    if not output_path or not value_path:
                        continue
                    value = self._json_value_at_path(source_record, value_path)
                    if str(field.get("tipo", "texto")) == "numero" and value is not None:
                        value = parse_flexible_number(value)
                    self._set_nested_value(item, output_path, value)
                records[key] = {"item": item, "indice_linha": row_index}

            records_by_source.append(records)
            evidence_sources.append({
                "arquivo_origem": origin_file,
                "caminho_chave": key_path,
                "registros_lidos": len(payload),
                "chaves_validas": len(records),
            })

        common_keys = set(records_by_source[0])
        for records in records_by_source[1:]:
            common_keys.intersection_update(records)

        result: list[dict[str, Any]] = []
        for key in sorted(common_keys):
            item: dict[str, Any] = {}
            for records in records_by_source:
                self._merge_nested_values(item, records[key]["item"])
            for output_path, value in dict(mapping_entry.get("valores_fixos", {})).items():
                self._set_nested_value(item, str(output_path), value)
            for rule in mapping_entry.get("valores_por_chave", []):
                if not isinstance(rule, dict):
                    continue
                pattern = str(rule.get("padrao_chave", ""))
                if pattern and re.search(pattern, key):
                    for output_path, value in dict(rule.get("valores_fixos", {})).items():
                        self._set_nested_value(item, str(output_path), value)
            result.append(item)

        return result, {
            "tipo_juncao": "interna",
            "fontes": evidence_sources,
            "chaves_juntas": sorted(common_keys),
            "registros_resolvidos": len(result),
        }

    @staticmethod
    def _json_value_at_path(value: Any, path: str) -> Any:
        current = value
        for key in path.split("."):
            if not key or not isinstance(current, dict) or key not in current:
                return None
            current = current[key]
        return current

    @staticmethod
    def _set_nested_value(target: dict[str, Any], path: str, value: Any) -> None:
        current = target
        parts = [part for part in path.split(".") if part]
        if not parts:
            return
        for part in parts[:-1]:
            if not isinstance(current.get(part), dict):
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value

    @classmethod
    def _merge_nested_values(cls, target: dict[str, Any], source: dict[str, Any]) -> None:
        for key, value in source.items():
            if isinstance(value, dict):
                if not isinstance(target.get(key), dict):
                    target[key] = {}
                cls._merge_nested_values(target[key], value)
            else:
                target[key] = value

    @staticmethod
    def _table_row_selectors(mapping_entry: dict[str, Any], row_count: int) -> list[dict[str, Any]]:
        """Normaliza seletores de linhas/colunas sem associá-los a campos de domínio."""
        raw_selectors = mapping_entry.get("segmentos") or mapping_entry.get("faixas_linhas")
        if not isinstance(raw_selectors, list):
            raw_selectors = [mapping_entry]

        selectors: list[dict[str, Any]] = []
        for raw_selector in raw_selectors:
            if isinstance(raw_selector, (list, tuple)) and len(raw_selector) == 2:
                raw_selector = {
                    "linha_inicial": raw_selector[0],
                    "linha_final": raw_selector[1],
                }
            if not isinstance(raw_selector, dict):
                continue
            try:
                start = int(raw_selector.get("linha_inicial", 0))
                end = int(raw_selector.get("linha_final", row_count - 1))
            except (TypeError, ValueError):
                continue
            if row_count == 0 or start < 0 or end < start or end >= row_count:
                continue
            raw_columns = raw_selector.get(
                "indices_colunas",
                mapping_entry.get("indices_colunas", []),
            )
            indices_colunas = [
                int(column)
                for column in raw_columns
                if isinstance(column, int) and column >= 0
            ] if isinstance(raw_columns, list) else []
            selectors.append(
                {
                    "linha_inicial": start,
                    "linha_final": end,
                    "indices_colunas": indices_colunas,
                    "valores_por_segmento": raw_selector.get("valores_por_segmento", {}),
                    "campos": list(raw_selector.get("campos", [])),
                }
            )
        return selectors

    @staticmethod
    def _table_row_with_named_fields(
        row: list[Any],
        row_index: int,
        start: int,
        fields: list[dict[str, Any]],
    ) -> dict[str, Any]:
        item: dict[str, Any] = {}
        for field in fields:
            name = str(field.get("nome", "")).strip()
            output_path = str(field.get("caminho_saida", "")).strip() or name
            if not output_path:
                continue
            field_type = str(field.get("tipo", "texto"))
            if field_type == "posicao":
                set_nested_value(item, output_path, row_index - start + 1)
                continue
            column_index = int(field.get("indice_coluna", -1))
            value = row[column_index] if 0 <= column_index < len(row) else None
            resolved = parse_flexible_number(value) if field_type == "numero" else str(value or "").strip() or None
            set_nested_value(item, output_path, resolved)
        return item

    def _load_table_metadata(
        self,
        extraction_root: Path,
        origin_file: str,
        table: dict[str, Any],
    ) -> dict[str, Any]:
        """Carrega metadados estruturais da tabela, quando a extracao os disponibiliza."""
        metadata_file = str(table.get("files", {}).get("metadata", "")).strip()
        if not metadata_file and origin_file.endswith(".json"):
            metadata_file = origin_file.removesuffix(".json") + "/metadata.json"
        if not metadata_file:
            return {}

        metadata_path = extraction_root / metadata_file
        if not metadata_path.exists():
            return {}
        try:
            return self._read_json(metadata_path)
        except Exception:
            logging.exception("Falha ao carregar metadados da tabela %s", metadata_file)
            return {}

    @staticmethod
    def _table_structural_evidence(metadata: dict[str, Any]) -> dict[str, Any]:
        """Seleciona campos estruturais uteis para auditoria e fallback."""
        if not metadata:
            return {}
        return {
            "table_id": metadata.get("table_id"),
            "document_id": metadata.get("document_id"),
            "page_number": metadata.get("page_number"),
            "section_id": metadata.get("section_id"),
            "section_title": metadata.get("section_title"),
            "title_raw": metadata.get("title_raw"),
            "title_canonical": metadata.get("title_canonical"),
            "bbox": metadata.get("bbox"),
            "row_count": metadata.get("row_count"),
            "column_count": metadata.get("column_count"),
        }

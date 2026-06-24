from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from docling_pipeline.helpers.number_utils import parse_flexible_number
from helpers import PROJECT_PATHS, RUNTIME_CONFIG_LOADER, ProjectPaths, RuntimeConfigLoader
from plugins.clients.minio_storage_client import MinioStorageClient


class SchemaResolutionService:
    """Executa validacao deterministica e resolucao do schema de saida."""

    def __init__(
        self,
        *,
        config_loader: RuntimeConfigLoader | None = None,
        project_paths: ProjectPaths | None = None,
    ) -> None:
        self.config_loader = config_loader or RUNTIME_CONFIG_LOADER
        self.project_paths = project_paths or PROJECT_PATHS
        self._minio_client: MinioStorageClient | None = None

    @property
    def minio_client(self) -> MinioStorageClient:
        if self._minio_client is None:
            config = self.config_loader.load_local_platform_config()
            self._minio_client = MinioStorageClient(config)
        return self._minio_client

    def process_all_extractions(self, runtime: dict[str, Any]) -> dict[str, Any]:
        """Processa todas as extracoes encontradas no MinIO e persiste as resolucoes."""
        manifests = self.discover_extraction_manifests()
        if not manifests:
            logging.warning("Nenhum manifesto de extracao encontrado no MinIO para resolver schema.")
            return {
                "processed_count": 0,
                "layout_changed_count": 0,
                "layout_alterado": False,
                "items": [],
            }

        processed_items: list[dict[str, Any]] = []
        for manifest_key in manifests:
            processed_items.append(self.process_extraction_manifest(runtime, manifest_key=manifest_key))

        layout_changed_count = len([item for item in processed_items if item.get("layout_alterado")])

        return {
            "processed_count": len(processed_items),
            "layout_changed_count": layout_changed_count,
            "layout_alterado": layout_changed_count > 0,
            "items": processed_items,
        }

    def discover_extraction_manifests(self) -> list[str]:
        """Lista manifestos de extracao da DAG1 para resolver em lote."""
        return self._discover_extraction_manifests()

    def process_extraction_manifest(self, runtime: dict[str, Any], *, manifest_key: str) -> dict[str, Any]:
        """Processa um manifesto individual de extracao e persiste saidas da DAG2."""
        loaded = self._load_inputs_from_manifest(runtime, manifest_key=manifest_key)
        validation = self.validate_deterministic_rules(loaded)
        layout_alterado = validation["status_compatibilidade"]["status"] != "compativel"

        resolved = self.resolve_canonical_mapping(loaded, validation)
        execution_log = self.build_execution_log(loaded, validation, resolved)
        persist_uris = self.persist_outputs(loaded, validation, resolved, execution_log)
        return {
            "manifest_key": manifest_key,
            "company_slug": loaded["execution"]["company_slug"],
            "execution_id": loaded["execution"]["execution_id"],
            "document_id": loaded["execution"]["document_id"],
            "layout_alterado": layout_alterado,
            "status_compatibilidade": validation["status_compatibilidade"]["status"],
            "persisted": persist_uris,
        }

    def load_inputs(self, runtime: dict[str, Any]) -> dict[str, Any]:
        """Carrega contrato, layout signature e paths de extracao."""
        contrato = self._load_json_from_uri_or_local(
            str(runtime["inputs"]["contrato_semantico"]),
            local_fallback="resultados_contrutoras/contrato_semantico_construtora.json",
        )
        layout = self._load_json_from_uri_or_local(
            str(runtime["inputs"]["layout_signature"]),
            local_fallback="resultados_contrutoras/layout_signature_cury_deterministico.json",
        )
        extraction_root = self._resolve_extraction_root(layout)
        return {
            "runtime": runtime,
            "contrato_semantico": contrato,
            "layout_signature": layout,
            "extraction_root": str(extraction_root),
        }

    def validate_deterministic_rules(self, loaded: dict[str, Any]) -> dict[str, Any]:
        """Executa regras deterministicas declaradas no layout signature."""
        layout = loaded["layout_signature"]
        extraction_root = Path(loaded["extraction_root"])
        rules = list(layout.get("regras_deteccao_mudanca", []))
        results: list[dict[str, Any]] = []
        fail_codes: list[str] = []

        for rule in rules:
            result = self._execute_rule(rule, extraction_root, loaded["contrato_semantico"])
            results.append(result)
            if result["status"] == "reprovada":
                fail_codes.append(str(rule.get("codigo_falha", "FALHA_DETERMINISTICA")))

        approved = len([item for item in results if item["status"] == "aprovada"])
        rejected = len(results) - approved
        compatible = rejected == 0
        report = {
            "tipo_artefato": "validacao_layout_signature",
            "empresa": layout.get("empresa"),
            "executado_em": datetime.now(UTC).isoformat(),
            "status_compatibilidade": {
                "status": "compativel" if compatible else "incompativel",
                "regras_total": len(results),
                "regras_aprovadas": approved,
                "regras_reprovadas": rejected,
                "codigos_alerta": sorted(set(fail_codes)),
            },
            "regras_executadas": results,
        }
        return report

    def resolve_canonical_mapping(self, loaded: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any]:
        """Resolve o schema de saida usando o contrato semantico e o mapeamento canonico."""
        contrato = loaded["contrato_semantico"]
        layout = loaded["layout_signature"]
        extraction_root = Path(loaded["extraction_root"])
        mapping = layout.get("mapeamento_canonico", {})

        schema_saida = self._build_schema_template(contrato.get("schema_saida", {}))
        resolved_by_path: dict[str, Any] = {}
        audit: list[dict[str, Any]] = []
        for mapping_path, mapping_entry in mapping.items():
            if not isinstance(mapping_entry, dict):
                continue
            result = self._resolve_mapping_entry(
                contrato=contrato,
                mapping_path=str(mapping_path),
                mapping_entry=mapping_entry,
                extraction_root=extraction_root,
                resolved_by_path=resolved_by_path,
            )
            resolved_by_path[str(mapping_path)] = result["valor_resolvido"]
            audit.append(result)
            if result["status_resolucao"] == "resolvido":
                self._set_schema_value(
                    target=schema_saida,
                    contract_template=contrato.get("schema_saida", {}),
                    mapping_path=str(mapping_path),
                    value=result["valor_resolvido"],
                )

        schema_saida = self._strip_internal_schema_metadata(schema_saida)

        return {
            "schema_saida": schema_saida,
            "validation_status": validation["status_compatibilidade"]["status"],
            "auditoria_resolucao": audit,
        }

    def build_execution_log(
        self,
        loaded: dict[str, Any],
        validation: dict[str, Any],
        resolved: dict[str, Any],
    ) -> dict[str, Any]:
        """Monta log de execucao com resumo da resolucao."""
        runtime = loaded["runtime"]
        execution = loaded.get("execution", runtime.get("execution", {}))
        status = "concluida" if validation["status_compatibilidade"]["status"] == "compativel" else "incompleta"
        return {
            "tipo_artefato": "auditoria_resolucao",
            "dag_name": runtime.get("dag_name"),
            "execution_id": execution.get("execution_id"),
            "document_id": execution.get("document_id"),
            "executado_em": datetime.now(UTC).isoformat(),
            "status": status,
            "summary": {
                "validation_status": validation["status_compatibilidade"]["status"],
                "periodo_referencia": resolved["schema_saida"].get("periodo_referencia"),
                "empresa": loaded["layout_signature"].get("empresa"),
                "campos_mapeamento_resolvidos": len(resolved.get("auditoria_resolucao", [])),
                "campos_mapeamento_com_falha": len(
                    [
                        item
                        for item in resolved.get("auditoria_resolucao", [])
                        if item.get("status_resolucao") != "resolvido"
                    ]
                ),
            },
            "auditoria_resolucao": resolved.get("auditoria_resolucao", []),
        }

    def persist_outputs(
        self,
        loaded: dict[str, Any],
        validation: dict[str, Any],
        resolved: dict[str, Any],
        execution_log: dict[str, Any],
    ) -> dict[str, Any]:
        """Persiste os 3 artefatos finais no MinIO."""
        output_keys = loaded.get("output_keys")
        if isinstance(output_keys, dict):
            validation_key = str(output_keys["validacao_layout_signature"])
            resolved_key = str(output_keys["schema_saida_resolvido"])
            log_key = str(output_keys["auditoria_resolucao"])
        else:
            runtime = loaded["runtime"]
            artifacts = list(runtime.get("artifacts", []))
            key_by_type = {str(item.get("tipo_artefato")): str(item.get("object_key")) for item in artifacts}
            validation_key = key_by_type.get("validacao_layout_signature")
            resolved_key = key_by_type.get("schema_saida_resolvido")
            log_key = key_by_type.get("auditoria_resolucao")
            if not validation_key or not resolved_key or not log_key:
                raise RuntimeError("Runtime da DAG 2 sem object_key esperado para persistencia.")

        validation["tipo_artefato"] = "validacao_layout_signature"
        execution_log["tipo_artefato"] = "auditoria_resolucao"

        validation_uri = self.minio_client.put_json(object_key=validation_key, payload=validation)
        schema_uri = self.minio_client.put_json(
            object_key=resolved_key,
            payload=resolved.get("schema_saida", {}),
        )
        audit_uri = self.minio_client.put_json(object_key=log_key, payload=execution_log)
        return {
            "validacao_layout_signature_uri": validation_uri,
            "schema_saida_resolvido_uri": schema_uri,
            "auditoria_resolucao_uri": audit_uri,
        }

    def _discover_extraction_manifests(self) -> list[str]:
        config = self.config_loader.load_local_platform_config()
        manifests = self.minio_client.list_object_keys(
            prefix=f"{config.minio_extract_prefix.rstrip('/')}/",
            suffix="/manifesto_execucao.json",
        )
        # Compatibilidade retroativa com prefixo antigo.
        if not manifests:
            manifests = self.minio_client.list_object_keys(
                prefix="execucoes/construtoras/",
                suffix="/manifesto_execucao.json",
            )
        return manifests

    def _load_inputs_from_manifest(self, runtime: dict[str, Any], *, manifest_key: str) -> dict[str, Any]:
        manifest = self.minio_client.get_json(object_key=manifest_key)
        candidate = manifest.get("candidate") if isinstance(manifest.get("candidate"), dict) else {}
        company_slug = str(candidate.get("company_slug") or "empresa_desconhecida")
        execution_id = str(manifest.get("execution_id") or "execucao_desconhecida")
        document_id = str(manifest.get("document_id") or "documento_desconhecido")

        artifact_uris = manifest.get("artifact_uris")
        if not isinstance(artifact_uris, list) or not artifact_uris:
            raise RuntimeError(f"Manifesto sem artifact_uris: {manifest_key}")

        extraction_root = self._materialize_extraction_artifacts(
            execution_id=execution_id,
            artifact_uris=[str(item) for item in artifact_uris],
        )
        config = self.config_loader.load_local_platform_config()
        contrato = self._load_json_from_uri_or_local(
            f"minio://{config.minio_bucket}/{config.minio_contract_prefix}/v1.2.0/contrato_semantico_construtora.json",
            local_fallback="resultados_contrutoras/contrato_semantico_construtora.json",
        )
        layout_uri = str(
            runtime.get("inputs", {}).get("layout_signature", "")
            if isinstance(runtime.get("inputs"), dict)
            else ""
        ).strip()
        if layout_uri and not layout_uri.startswith("minio://"):
            layout_uri = f"minio://{config.minio_bucket}/{layout_uri}"
        layout = self._load_json_from_uri_or_local(
            layout_uri
            or (
                f"minio://{config.minio_bucket}/{config.minio_layout_prefix}/"
                f"{company_slug}/v4.0.0/layout_signature_deterministico.json"
            ),
            local_fallback="resultados_contrutoras/layout_signature_cury_deterministico.json",
        )
        layout["empresa"] = layout.get("empresa") or company_slug

        revalidation_prefix = str(runtime.get("fallback_revalidation_prefix", "")).strip()
        if revalidation_prefix:
            resolution_prefix = revalidation_prefix.rstrip("/")
        else:
            resolution_prefix = (
                f"{config.minio_resolution_prefix.rstrip('/')}/{company_slug}/"
                f"document_id={document_id}/execution_id={execution_id}/resolution"
            )
        return {
            "runtime": runtime,
            "execution": {
                "company_slug": company_slug,
                "execution_id": execution_id,
                "document_id": document_id,
            },
            "contrato_semantico": contrato,
            "layout_signature": layout,
            "extraction_root": str(extraction_root),
            "output_keys": {
                "validacao_layout_signature": f"{resolution_prefix}/validacao_layout_signature.json",
                "schema_saida_resolvido": f"{resolution_prefix}/schema_saida_resolvido.json",
                "auditoria_resolucao": f"{resolution_prefix}/auditoria_resolucao.json",
            },
            "layout_signature_override": runtime.get("layout_signature_override"),
        }

    def _materialize_extraction_artifacts(self, *, execution_id: str, artifact_uris: list[str]) -> Path:
        target_root = Path(self.project_paths.path("airflow", "state", "resolution_inputs", execution_id, "extraction"))
        target_root.mkdir(parents=True, exist_ok=True)
        for uri in artifact_uris:
            object_key = self._parse_minio_uri(uri)
            relative = object_key.rsplit("/extraction/", maxsplit=1)[-1]
            destination = target_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(self.minio_client.get_bytes(object_key=object_key))
        return target_root

    def _resolve_extraction_root(self, layout: dict[str, Any]) -> Path:
        raw = str(layout.get("documento_origem", {}).get("pasta_de_extracao", "")).strip()
        if raw:
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = Path(self.project_paths.path(raw))
            if candidate.exists():
                return candidate
            fallback = Path(self.project_paths.path(Path(raw).name))
            if fallback.exists():
                return fallback
        default_root = Path(self.project_paths.path("extraction_cury"))
        if default_root.exists():
            return default_root
        raise RuntimeError("Nao foi possivel localizar pasta de extracao para DAG 2.")

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
                row_index = self._find_row_index(table, accepted, label_col)
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
                row_index = self._find_row_index(table, accepted, label_col)
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

            if tipo_origem == "bloco_textual":
                value, evidence = self._resolve_text_block_mapping(extraction_root, mapping_entry)
                return {
                    **base,
                    "status_resolucao": "resolvido" if value is not None else "nao_resolvido",
                    "valor_resolvido": value,
                    "evidencia": evidence,
                }

            if tipo_origem == "cabecalho_de_tabela":
                value, evidence = self._resolve_table_header_mapping(extraction_root, mapping_entry)
                return {
                    **base,
                    "status_resolucao": "resolvido" if value is not None else "nao_resolvido",
                    "valor_resolvido": value,
                    "evidencia": evidence,
                }

            if tipo_origem == "celula_de_tabela":
                value, evidence = self._resolve_table_cell_mapping(
                    contrato=contrato,
                    mapping_path=mapping_path,
                    extraction_root=extraction_root,
                    mapping_entry=mapping_entry,
                    resolved_by_path=resolved_by_path,
                )
                return {
                    **base,
                    "status_resolucao": "resolvido" if value.get("valor") is not None else "nao_resolvido",
                    "valor_resolvido": value,
                    "evidencia": evidence,
                }
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
        pattern = str(selector.get("padrao_cabecalho_aceito", ".*"))
        ok = header is not None and re.search(pattern, str(header)) is not None
        return (str(header) if ok else None), {
            "arquivo_origem": origin_file,
            **self._table_structural_evidence(table_metadata),
            "indice_coluna": idx,
            "cabecalho_encontrado": header,
            "padrao_cabecalho_aceito": pattern,
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
        row_index = self._find_row_index(table, accepted, label_col)
        col_idx = int(column_selector.get("indice_coluna_esperado", -1))
        header = schema[col_idx] if col_idx >= 0 and col_idx < len(schema) else None
        header_pattern = str(column_selector.get("padrao_cabecalho_aceito", ".*"))
        header_ok = header is not None and re.search(header_pattern, str(header)) is not None

        raw_value = None
        normalized_value = None
        if row_index is not None and row_index < len(rows):
            row = list(rows[row_index])
            if col_idx >= 0 and col_idx < len(row) and header_ok:
                raw_value = row[col_idx]
                normalized_value = parse_flexible_number(raw_value)

        value = {
            "periodo": str(header) if header_ok and header is not None else None,
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
            "padrao_cabecalho_aceito": header_pattern,
            "papel_periodo": mapping_entry.get("papel_periodo"),
            "valor_bruto": raw_value,
            "valor_normalizado": normalized_value,
        }
        return value, evidence

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

    @staticmethod
    def _build_schema_template(contract_node: Any) -> Any:
        if isinstance(contract_node, dict):
            return {key: SchemaResolutionService._build_schema_template(value) for key, value in contract_node.items()}
        if isinstance(contract_node, list):
            return []
        return None

    @staticmethod
    def _parse_mapping_path(mapping_path: str) -> list[dict[str, str | tuple[str, str]]]:
        tokens: list[dict[str, str | tuple[str, str]]] = []
        for raw_part in mapping_path.split("."):
            match = re.fullmatch(r"([^\[\]]+)(?:\[([^=\]]+)=([^\]]+)\])?", raw_part)
            if not match:
                raise RuntimeError(f"Caminho de mapeamento canonico invalido: {mapping_path}")
            token: dict[str, str | tuple[str, str]] = {"field": match.group(1)}
            if match.group(2) is not None:
                token["selector"] = (match.group(2), match.group(3))
            tokens.append(token)
        return tokens

    def _set_schema_value(
        self,
        *,
        target: dict[str, Any],
        contract_template: Any,
        mapping_path: str,
        value: Any,
    ) -> None:
        tokens = self._parse_mapping_path(mapping_path)
        current: Any = target
        current_contract: Any = contract_template

        for index, token in enumerate(tokens):
            field = str(token["field"])
            selector = token.get("selector")
            is_last = index == len(tokens) - 1

            if not isinstance(current, dict):
                raise RuntimeError(f"Caminho nao compativel com schema_saida do contrato: {mapping_path}")

            if selector is None:
                if not self._contract_has_field(current_contract, field):
                    return
                if is_last:
                    current[field] = value
                    return
                child_contract = self._contract_child_template(current_contract, field)
                if field not in current or current[field] is None:
                    current[field] = self._build_schema_template(child_contract)
                current = current[field]
                current_contract = child_contract
                continue

            if not self._contract_has_field(current_contract, field):
                return
            array_contract = self._contract_child_template(current_contract, field)
            item_contract = array_contract[0] if isinstance(array_contract, list) and array_contract else {}
            if not isinstance(current.get(field), list):
                current[field] = []
            item = self._find_or_create_schema_array_item(
                items=current[field],
                item_contract=item_contract,
                selector=selector,
            )
            if is_last:
                if isinstance(item, dict) and isinstance(value, dict):
                    item.update(value)
                else:
                    item = value
                return
            current = item
            current_contract = item_contract

    @staticmethod
    def _contract_child_template(contract_node: Any, field: str) -> Any:
        if isinstance(contract_node, dict):
            return contract_node.get(field)
        return None

    @staticmethod
    def _contract_has_field(contract_node: Any, field: str) -> bool:
        return isinstance(contract_node, dict) and field in contract_node

    def _find_or_create_schema_array_item(
        self,
        *,
        items: list[Any],
        item_contract: Any,
        selector: str | tuple[str, str],
    ) -> dict[str, Any]:
        selector_key, selector_value = selector
        for item in items:
            if not isinstance(item, dict):
                continue
            selectors = item.get("__selectors__")
            if isinstance(selectors, dict) and selectors.get(selector_key) == selector_value:
                return item

        item = self._build_schema_template(item_contract)
        if not isinstance(item, dict):
            item = {}
        item["__selectors__"] = {selector_key: selector_value}
        if selector_key in item and item[selector_key] is None:
            item[selector_key] = selector_value
        items.append(item)
        return item

    def _strip_internal_schema_metadata(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: self._strip_internal_schema_metadata(item)
                for key, item in value.items()
                if key != "__selectors__"
            }
        if isinstance(value, list):
            return [self._strip_internal_schema_metadata(item) for item in value]
        return value

    def _expand_accepted_labels_from_contract(
        self,
        *,
        contrato: dict[str, Any],
        values: list[str],
        mapping_path: str | None = None,
        resolved_by_path: dict[str, Any] | None = None,
    ) -> set[str]:
        accepted = {self._normalize_text(value) for value in values if str(value).strip()}
        semantic = dict(contrato.get("contrato_semantico", {}))
        source_values = set(accepted)
        metric_context = self._semantic_metric_context(
            mapping_path=mapping_path,
            resolved_by_path=resolved_by_path or {},
        )

        for entity_name, entity_spec in dict(semantic.get("entidades", {})).items():
            if not isinstance(entity_spec, dict):
                continue
            candidates = self._semantic_candidates(entity_name, entity_spec)
            if source_values.intersection({self._normalize_text(item) for item in candidates}):
                accepted.update(self._normalize_text(item) for item in candidates)

        for metric_name, metric_spec in dict(semantic.get("metricas", {})).items():
            if not isinstance(metric_spec, dict):
                continue
            if str(metric_spec.get("tipo")) == "metrica_calculada":
                continue
            metric_matches_context = self._metric_matches_context(metric_name, metric_spec, metric_context)
            for indicator_name, indicator_spec in dict(metric_spec.get("indicadores", {})).items():
                if not isinstance(indicator_spec, dict):
                    continue
                candidates = self._semantic_candidates(indicator_name, indicator_spec)
                normalized_candidates = {self._normalize_text(item) for item in candidates}
                if metric_matches_context or source_values.intersection(normalized_candidates):
                    accepted.update(normalized_candidates)

        return accepted

    def _semantic_metric_context(
        self,
        *,
        mapping_path: str | None,
        resolved_by_path: dict[str, Any],
    ) -> dict[str, str]:
        if not mapping_path:
            return {}
        prefix = re.split(r"\.dados\[|\.valores\[", mapping_path, maxsplit=1)[0]
        context: dict[str, str] = {}
        for field in ("tipo_operacao", "indicador", "unidade"):
            value = resolved_by_path.get(f"{prefix}.{field}")
            if value is not None:
                context[field] = str(value)
        return context

    @staticmethod
    def _semantic_candidates(name: str, spec: dict[str, Any]) -> list[str]:
        candidates = [name]
        for key in ("dominio", "sinonimos"):
            values = spec.get(key)
            if isinstance(values, list):
                candidates.extend(str(item) for item in values)
        return candidates

    @staticmethod
    def _metric_matches_context(metric_name: str, metric_spec: dict[str, Any], context: dict[str, str]) -> bool:
        if not context:
            return False
        if context.get("tipo_operacao") and str(metric_spec.get("tipo_operacao")) == context["tipo_operacao"]:
            return True
        return metric_name in context.values()

    def _load_json_from_uri_or_local(self, uri: str, *, local_fallback: str) -> dict[str, Any]:
        if uri.startswith("minio://"):
            try:
                object_key = self._parse_minio_uri(uri)
                return self.minio_client.get_json(object_key=object_key)
            except Exception as exc:
                logging.warning("Falha ao carregar %s do MinIO (%s). Usando fallback local.", uri, exc)
        return self._read_json(Path(self.project_paths.path(local_fallback)))

    @staticmethod
    def _parse_minio_uri(uri: str) -> str:
        without_scheme = uri[len("minio://") :]
        _, _, key = without_scheme.partition("/")
        if not key:
            raise RuntimeError(f"URI MinIO invalida: {uri}")
        return key

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise RuntimeError(f"Arquivo JSON nao encontrado: {path}")
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise RuntimeError(f"Esperado JSON objeto em {path}")
        return loaded

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        items: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                stripped = line.strip()
                if not stripped:
                    continue
                loaded = json.loads(stripped)
                if isinstance(loaded, dict):
                    items.append(loaded)
        return items

    @staticmethod
    def _normalize_text(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value)
        ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
        return re.sub(r"\s+", " ", ascii_value).strip().lower()

    def _find_row_index(self, table: dict[str, Any], accepted: set[str], label_col: int) -> int | None:
        rows = list(table.get("rows", []))
        for idx, row in enumerate(rows):
            if label_col >= len(row):
                continue
            normalized = self._normalize_text(str(row[label_col]))
            if normalized in accepted:
                return idx
        return None


SCHEMA_RESOLUTION_SERVICE = SchemaResolutionService()

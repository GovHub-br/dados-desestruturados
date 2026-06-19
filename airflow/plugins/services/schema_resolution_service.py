from __future__ import annotations

import json
import logging
import re
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
        manifests = self._discover_extraction_manifests()
        if not manifests:
            logging.warning("Nenhum manifesto de extracao encontrado no MinIO para resolver schema.")
            return {
                "processed_count": 0,
                "layout_changed_count": 0,
                "layout_alterado": False,
                "items": [],
            }

        processed_items: list[dict[str, Any]] = []
        layout_changed_count = 0
        for manifest_key in manifests:
            loaded = self._load_inputs_from_manifest(runtime, manifest_key=manifest_key)
            validation = self.validate_deterministic_rules(loaded)
            layout_alterado = validation["status_compatibilidade"]["status"] != "compativel"

            if layout_alterado:
                layout_changed_count += 1
                execution_log = self.build_execution_log(
                    loaded,
                    validation,
                    resolved={"schema_saida": {"periodo_referencia": None}},
                )
                persist_uris = self.persist_outputs(
                    loaded,
                    validation,
                    resolved={"schema_saida": {}},
                    execution_log=execution_log,
                )
                processed_items.append(
                    {
                        "manifest_key": manifest_key,
                        "company_slug": loaded["execution"]["company_slug"],
                        "execution_id": loaded["execution"]["execution_id"],
                        "document_id": loaded["execution"]["document_id"],
                        "layout_alterado": True,
                        "status_compatibilidade": validation["status_compatibilidade"]["status"],
                        "persisted": persist_uris,
                    }
                )
                continue

            resolved = self.resolve_canonical_mapping(loaded, validation)
            execution_log = self.build_execution_log(loaded, validation, resolved)
            persist_uris = self.persist_outputs(loaded, validation, resolved, execution_log)
            processed_items.append(
                {
                    "manifest_key": manifest_key,
                    "company_slug": loaded["execution"]["company_slug"],
                    "execution_id": loaded["execution"]["execution_id"],
                    "document_id": loaded["execution"]["document_id"],
                    "layout_alterado": False,
                    "status_compatibilidade": validation["status_compatibilidade"]["status"],
                    "persisted": persist_uris,
                }
            )

        return {
            "processed_count": len(processed_items),
            "layout_changed_count": layout_changed_count,
            "layout_alterado": layout_changed_count > 0,
            "items": processed_items,
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
            result = self._execute_rule(rule, extraction_root)
            results.append(result)
            if result["status"] == "reprovada":
                fail_codes.append(str(rule.get("codigo_falha", "FALHA_DETERMINISTICA")))

        approved = len([item for item in results if item["status"] == "aprovada"])
        rejected = len(results) - approved
        compatible = rejected == 0
        report = {
            "tipo_artefato": "report_validacao",
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
        """Resolve campos canonicos principais a partir de blocos e tabelas."""
        layout = loaded["layout_signature"]
        extraction_root = Path(loaded["extraction_root"])
        mapping = layout.get("mapeamento_canonico", {})

        lanc_table_path = extraction_root / "tables/table001.json"
        vend_table_path = extraction_root / "tables/table002.json"
        lanc_table = self._read_json(lanc_table_path)
        vend_table = self._read_json(vend_table_path)

        periodos = self._resolve_period_headers(lanc_table)
        periodo_referencia = self._resolve_periodo_referencia(
            extraction_root=extraction_root,
            mapping_entry=mapping.get("periodo_referencia", {}),
            fallback=periodos.get("periodo_referencia"),
        )

        if periodos.get("periodo_referencia") is None and periodo_referencia:
            periodos["periodo_referencia"] = periodo_referencia

        schema_saida = {
            "fonte": self._resolve_fonte(mapping.get("fonte", {})),
            "periodo_referencia": periodo_referencia,
            "periodos_disponiveis": {
                "periodo_referencia": periodos.get("periodo_referencia"),
                "periodo_comparativo_anterior": periodos.get("periodo_comparativo_anterior"),
                "mesmo_periodo_ano_anterior": periodos.get("mesmo_periodo_ano_anterior"),
                "periodo_12m_atual": periodos.get("periodo_12m_atual"),
                "periodo_12m_anterior": periodos.get("periodo_12m_anterior"),
            },
            "balancos_das_empresas": {
                "titulo": "Balancos das empresas",
                "lancamentos": self._resolve_operacao(
                    layout=layout,
                    table=lanc_table,
                    tipo_operacao="lancamento",
                    periodos=periodos,
                ),
                "vendas": self._resolve_operacao(
                    layout=layout,
                    table=vend_table,
                    tipo_operacao="venda",
                    periodos=periodos,
                ),
            },
            "metricas_calculadas": {
                "observacao": (
                    "Variacoes percentuais devem ser calculadas em etapa posterior "
                    "usando os valores brutos por periodo."
                ),
                "status": "nao_calculadas_na_extracao",
            },
        }

        return {
            "schema_saida": schema_saida,
            "validation_status": validation["status_compatibilidade"]["status"],
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
            "tipo_artefato": "log_execucao",
            "dag_name": runtime.get("dag_name"),
            "execution_id": execution.get("execution_id"),
            "document_id": execution.get("document_id"),
            "executado_em": datetime.now(UTC).isoformat(),
            "status": status,
            "summary": {
                "validation_status": validation["status_compatibilidade"]["status"],
                "periodo_referencia": resolved["schema_saida"].get("periodo_referencia"),
                "empresa": loaded["layout_signature"].get("empresa"),
            },
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
            validation_key = str(output_keys["report_validacao"])
            resolved_key = str(output_keys["schema_saida_resolvido"])
            log_key = str(output_keys["log_execucao"])
        else:
            runtime = loaded["runtime"]
            artifacts = list(runtime.get("artifacts", []))
            key_by_type = {str(item.get("tipo_artefato")): str(item.get("object_key")) for item in artifacts}
            validation_key = key_by_type.get("validacao_layout_signature")
            resolved_key = key_by_type.get("schema_saida_resolvido")
            log_key = key_by_type.get("auditoria_resolucao")
            if not validation_key or not resolved_key or not log_key:
                raise RuntimeError("Runtime da DAG 2 sem object_key esperado para persistencia.")

        # Nomes pedidos no diagrama.
        validation["tipo_artefato"] = "report_validacao"
        execution_log["tipo_artefato"] = "log_execucao"

        report_uri = self.minio_client.put_json(object_key=validation_key, payload=validation)
        schema_uri = self.minio_client.put_json(
            object_key=resolved_key,
            payload=resolved.get("schema_saida", {}),
        )
        log_uri = self.minio_client.put_json(object_key=log_key, payload=execution_log)
        return {
            "report_validacao_uri": report_uri,
            "schema_saida_resolvido_uri": schema_uri,
            "log_execucao_uri": log_uri,
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
        layout = self._load_json_from_uri_or_local(
            (
                f"minio://{config.minio_bucket}/{config.minio_layout_prefix}/"
                f"{company_slug}/v4.0.0/layout_signature_deterministico.json"
            ),
            local_fallback="resultados_contrutoras/layout_signature_cury_deterministico.json",
        )
        layout["empresa"] = layout.get("empresa") or company_slug

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
                "report_validacao": f"{resolution_prefix}/report_validacao.json",
                "schema_saida_resolvido": f"{resolution_prefix}/schema_saida_resolvido.json",
                "log_execucao": f"{resolution_prefix}/log_execucao.json",
            },
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

    def _execute_rule(self, rule: dict[str, Any], extraction_root: Path) -> dict[str, Any]:
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
                accepted = {self._normalize_text(str(item)) for item in rule.get("valores_aceitos", [])}
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
                row_label = self._normalize_text(str(rule.get("linha_rotulo", "")))
                row_index = self._find_row_index(table, {row_label}, label_col)
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

    def _resolve_fonte(self, mapping_entry: dict[str, Any]) -> str:
        value = str(mapping_entry.get("valor_fixo", "")).strip()
        return value or "Balancos trimestrais das empresas"

    def _resolve_periodo_referencia(
        self,
        *,
        extraction_root: Path,
        mapping_entry: dict[str, Any],
        fallback: str | None,
    ) -> str | None:
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
                return match.group(0)
        return fallback

    def _resolve_period_headers(self, table: dict[str, Any]) -> dict[str, str | None]:
        schema = list(table.get("schema", []))
        pick = lambda idx: schema[idx] if idx < len(schema) else None
        return {
            "periodo_referencia": pick(1),
            "periodo_comparativo_anterior": pick(2),
            "mesmo_periodo_ano_anterior": pick(4),
            "periodo_12m_atual": pick(6),
            "periodo_12m_anterior": pick(7),
        }

    def _resolve_operacao(
        self,
        *,
        layout: dict[str, Any],
        table: dict[str, Any],
        tipo_operacao: str,
        periodos: dict[str, str | None],
    ) -> dict[str, Any]:
        empresa = str(layout.get("empresa", "empresa_desconhecida"))
        row_index = self._find_row_index(table, {self._normalize_text("Numero de Unidades")}, 0)
        values: list[dict[str, Any]] = []
        if row_index is not None:
            row = list(table.get("rows", []))[row_index]
            for key, col_idx, escopo in [
                ("periodo_referencia", 1, "trimestre"),
                ("periodo_comparativo_anterior", 2, "trimestre"),
                ("mesmo_periodo_ano_anterior", 4, "trimestre"),
                ("periodo_12m_atual", 6, "ultimos_12_meses"),
                ("periodo_12m_anterior", 7, "ultimos_12_meses"),
            ]:
                if col_idx >= len(row):
                    continue
                periodo = periodos.get(key)
                values.append(
                    {
                        "periodo": periodo,
                        "escopo_periodo": escopo,
                        "valor": parse_flexible_number(row[col_idx]),
                    }
                )

        return {
            "titulo": "Lancamentos" if tipo_operacao == "lancamento" else "Vendas",
            "tipo": "valor_bruto",
            "tipo_operacao": tipo_operacao,
            "indicador": "numero_de_unidades",
            "unidade": "unidades",
            "dados": [{"empresa": empresa, "valores": values}],
        }

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
        return re.sub(r"\s+", " ", value).strip().lower().replace("ú", "u").replace("ç", "c")

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

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any


class FallbackInventoryService:
    """Carrega inventario e artefatos escolhidos pela LLM."""

    REQUIRED = "obrigatorio"
    RECOMMENDED = "recomendado"
    OPTIONAL = "opcional"
    DISABLED = "nao_usar_automaticamente"

    PARTIAL_SCOPE = "correcao_parcial_mapeamento"
    FULL_REMAP_SCOPE = "regeneracao_total_mapeamento"
    CREATION_SCOPE = "criacao_inicial_layout"
    UNSUPPORTED_SCOPE = "falha_nao_suportada_para_fallback_automatico"

    MAX_FULL_ARTIFACT_CHARS = 60_000
    JSONL_CHUNK_RECORDS = 40
    MAX_CHUNKS_PER_ARTIFACT = 8

    def load_extraction_inventory(
        self,
        *,
        manifest: dict[str, Any],
        load_json_object: Callable[[str, str], dict[str, Any]],
    ) -> tuple[str | None, dict[str, Any]]:
        """Le o `inventory.json` da extracao quando ele estiver listado no manifesto."""
        artifact_uris = manifest.get("artifact_uris", [])
        if not isinstance(artifact_uris, list):
            return None, {}

        inventory_key = self.find_artifact_object_key(
            artifact_uris=[str(uri) for uri in artifact_uris],
            origin_file="inventory.json",
        )
        if not inventory_key:
            return None, {}

        try:
            return inventory_key, load_json_object(inventory_key, "inventario_extracao")
        except RuntimeError:
            return inventory_key, {}

    def inventory_usage_policy(
        self,
        *,
        classification: dict[str, Any],
        rejected_rules: list[dict[str, Any]],
        unresolved_required: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Decide quando o inventario deve ajudar a selecionar artefatos."""
        scope = str(classification.get("fallback_scope", "")).strip()
        reasons: list[str] = []
        usage = self.OPTIONAL

        if scope in {self.FULL_REMAP_SCOPE, self.CREATION_SCOPE}:
            usage = self.REQUIRED
            reasons.append("escopo exige redescoberta ampla de artefatos")
        elif scope == self.PARTIAL_SCOPE:
            for rule in rejected_rules:
                rule_type = str(rule.get("tipo_teste", "")).strip()
                if rule_type in {"linha_existe_em_tabela", "perfil_colunas_periodo_existe_em_tabela"}:
                    usage = self.RECOMMENDED
                    reasons.append(f"falha parcial pode exigir nova origem: {rule_type}")
                elif rule_type == "valor_normalizavel":
                    reasons.append("valor nao normalizavel normalmente nao exige nova origem")
                elif rule_type:
                    usage = self.RECOMMENDED
                    reasons.append(f"falha parcial classificada pode se beneficiar do inventario: {rule_type}")

            if unresolved_required:
                usage = self.RECOMMENDED
                reasons.append("campos obrigatorios nao resolvidos podem exigir busca em origem alternativa")

            if any(str(item.get("status_resolucao", "")) == "erro" for item in unresolved_required):
                usage = self.RECOMMENDED
                reasons.append("erro de seletor pode indicar caminho ou artefato alterado")
        elif scope == self.UNSUPPORTED_SCOPE:
            usage = self.DISABLED
            reasons.append("falha sem classificador automatico nao deve acionar busca por inventario")

        return {
            "uso_inventario": usage,
            "motivos": sorted(set(reasons)),
        }

    def inventory_summary(self, inventory: dict[str, Any], *, full: bool = False) -> dict[str, Any]:
        """Compacta o inventario para o prompt sem perder o mapa dos artefatos."""
        if not isinstance(inventory, dict) or not inventory:
            return {"status": "inventario_ausente"}
        items = inventory.get("items", [])
        if not isinstance(items, list):
            items = []
        selected_items = items if full else items[:40]
        return {
            "kind": inventory.get("kind"),
            "version": inventory.get("version"),
            "source_file": inventory.get("source_file"),
            "summary": inventory.get("summary", {}),
            "collections": inventory.get("collections", {}),
            "modo": "completo" if full else "resumido",
            "total_items": len(items),
            "items_incluidos": len(selected_items),
            "items": [
                {
                    "kind": item.get("kind"),
                    "path": item.get("path"),
                    "name": item.get("name"),
                    "page_number": item.get("page_number"),
                    "section_title": item.get("section_title"),
                    "schema": item.get("schema"),
                    "row_labels_sample": item.get("row_labels_sample"),
                    "record_count": item.get("record_count"),
                }
                for item in selected_items
                if isinstance(item, dict)
            ],
        }

    def load_selected_extraction_artifacts(
        self,
        *,
        manifest: dict[str, Any],
        artifact_paths: list[str],
        get_bytes: Callable[[str], bytes],
    ) -> dict[str, Any]:
        """Carrega artefatos selecionados, com chunks somente quando necessario."""
        artifact_uris = manifest.get("artifact_uris", [])
        if not isinstance(artifact_uris, list):
            return {}

        loaded: dict[str, Any] = {}
        for artifact_path in artifact_paths[:8]:
            object_key = self.find_artifact_object_key(
                artifact_uris=[str(uri) for uri in artifact_uris],
                origin_file=artifact_path,
            )
            if not object_key:
                loaded[artifact_path] = {"status": "nao_encontrado_no_manifesto"}
                continue
            loaded[artifact_path] = self.load_artifact_for_llm(object_key, get_bytes=get_bytes)
        return loaded

    def load_artifact_for_llm(
        self,
        object_key: str,
        *,
        get_bytes: Callable[[str], bytes],
    ) -> dict[str, Any]:
        """Carrega um artefato pequeno inteiro ou o particiona com estado de chunks."""
        try:
            raw = get_bytes(object_key)
        except Exception as exc:
            return {"object_key": object_key, "status": "erro_ao_carregar", "erro": str(exc)}

        text = raw.decode("utf-8", errors="replace")
        if len(text) <= self.MAX_FULL_ARTIFACT_CHARS:
            return self.load_extraction_sample_object(object_key, get_bytes=get_bytes)

        if object_key.endswith(".jsonl"):
            chunks = self._chunk_jsonl_text(text)
            return {
                "object_key": object_key,
                "formato": "jsonl",
                "modo": "chunked",
                "chunking": {
                    "estrategia": "linhas_jsonl",
                    "chunk_records": self.JSONL_CHUNK_RECORDS,
                    "max_chunks": self.MAX_CHUNKS_PER_ARTIFACT,
                    "estado_acumulado_obrigatorio": True,
                },
                "chunks": chunks,
            }

        return {
            "object_key": object_key,
            "formato": "texto",
            "modo": "truncated",
            "sample": text[: self.MAX_FULL_ARTIFACT_CHARS],
            "chunking": {"estado_acumulado_obrigatorio": True},
        }

    def load_extraction_sample_object(
        self,
        object_key: str,
        *,
        get_bytes: Callable[[str], bytes],
    ) -> dict[str, Any]:
        """Le um artefato de extracao e devolve somente uma amostra truncada."""
        try:
            raw = get_bytes(object_key)
        except Exception as exc:
            return {"object_key": object_key, "status": "erro_ao_carregar", "erro": str(exc)}

        text = raw.decode("utf-8", errors="replace")
        if object_key.endswith(".json"):
            try:
                return {
                    "object_key": object_key,
                    "formato": "json",
                    "sample": self.truncate_json(json.loads(text)),
                }
            except Exception:
                return {
                    "object_key": object_key,
                    "formato": "texto",
                    "sample": text[:2000],
                }

        if object_key.endswith(".jsonl"):
            rows: list[Any] = []
            for line in text.splitlines():
                if len(rows) >= 5:
                    break
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    rows.append(self.truncate_json(json.loads(stripped)))
                except Exception:
                    rows.append(stripped[:500])
            return {"object_key": object_key, "formato": "jsonl", "sample": rows}

        return {"object_key": object_key, "formato": "texto", "sample": text[:2000]}

    @staticmethod
    def initial_chunk_state(
        *,
        broken_fields: list[str],
        artifact_paths: list[str],
    ) -> dict[str, Any]:
        """Cria estado acumulado inicial para chamadas por chunk."""
        return {
            "estado_acumulado_pela_dag": True,
            "campos": [
                {
                    "campo_saida": field,
                    "evidencias_candidatas": [],
                    "chunks_analisados": [],
                    "conflitos": [],
                }
                for field in broken_fields
            ],
            "artefatos_selecionados": artifact_paths,
        }

    @staticmethod
    def find_artifact_object_key(*, artifact_uris: list[str], origin_file: str) -> str | None:
        """Localiza no manifesto o object key de um arquivo de extracao relativo."""
        normalized_origin = origin_file.strip("/")
        for uri in artifact_uris:
            object_key = FallbackInventoryService.object_key_from_minio_uri(uri)
            if object_key.endswith(f"/extraction/{normalized_origin}") or object_key.endswith(normalized_origin):
                return object_key
        return None

    @staticmethod
    def object_key_from_minio_uri(uri: str) -> str:
        """Extrai object key de uma URI minio://bucket/key ou retorna a propria string."""
        if not uri.startswith("minio://"):
            return uri
        without_scheme = uri.removeprefix("minio://")
        parts = without_scheme.split("/", maxsplit=1)
        return parts[1] if len(parts) == 2 else ""

    def _chunk_jsonl_text(self, text: str) -> list[dict[str, Any]]:
        """Divide JSONL grande em chunks pequenos para chamadas incrementais."""
        chunks: list[dict[str, Any]] = []
        current: list[Any] = []
        start_line = 1
        line_number = 0
        for line in text.splitlines():
            line_number += 1
            stripped = line.strip()
            if not stripped:
                continue
            try:
                current.append(self.truncate_json(json.loads(stripped), max_depth=4))
            except Exception:
                current.append(stripped[:800])

            if len(current) >= self.JSONL_CHUNK_RECORDS:
                chunks.append(
                    {
                        "chunk_id": f"chunk_{len(chunks) + 1:03d}",
                        "linha_inicio": start_line,
                        "linha_fim": line_number,
                        "records": current,
                    }
                )
                if len(chunks) >= self.MAX_CHUNKS_PER_ARTIFACT:
                    break
                current = []
                start_line = line_number + 1

        if current and len(chunks) < self.MAX_CHUNKS_PER_ARTIFACT:
            chunks.append(
                {
                    "chunk_id": f"chunk_{len(chunks) + 1:03d}",
                    "linha_inicio": start_line,
                    "linha_fim": line_number,
                    "records": current,
                }
            )
        return chunks

    def truncate_json(self, value: Any, *, max_depth: int = 5) -> Any:
        """Reduz estruturas grandes para caberem no contexto da LLM."""
        if max_depth <= 0:
            return "<truncado>"
        if isinstance(value, dict):
            return {
                str(key): self.truncate_json(item, max_depth=max_depth - 1)
                for key, item in list(value.items())[:20]
            }
        if isinstance(value, list):
            return [
                self.truncate_json(item, max_depth=max_depth - 1)
                for item in value[:8]
            ]
        if isinstance(value, str) and len(value) > 800:
            return f"{value[:800]}..."
        return value


FALLBACK_INVENTORY_SERVICE = FallbackInventoryService()

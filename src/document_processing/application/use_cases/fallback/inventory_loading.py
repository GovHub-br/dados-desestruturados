from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any


class FallbackInventoryLoadingMixin:
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

    def enrich_selected_jsonl_anchor_evidence(
        self,
        *,
        manifest: dict[str, Any],
        artifact_selection: Any,
        loaded_artifacts: dict[str, Any],
        get_bytes: Callable[[str], bytes],
    ) -> dict[str, Any]:
        """Inclui somente registros JSONL que comprovem ancoras ja declaradas.

        A selecao LLM continua baseada em amostras pequenas. Depois dela, esta
        etapa percorre deterministicamente o JSONL completo para evitar falsos
        negativos quando a evidencia esta fora dos primeiros registros.
        """
        artifact_uris = manifest.get("artifact_uris", [])
        if not isinstance(artifact_uris, list):
            return loaded_artifacts

        items = getattr(artifact_selection, "artifact_paths", [])
        if not isinstance(items, list):
            return loaded_artifacts

        for item in items:
            path = str(getattr(item, "path", "")).strip("/")
            artifact = loaded_artifacts.get(path)
            if not path or not isinstance(artifact, dict) or artifact.get("status"):
                continue

            anchors = [
                str(anchor).strip()
                for coverage in getattr(item, "coberturas", [])
                for anchor in getattr(coverage, "ancoras", [])
                if str(anchor).strip()
            ]
            if not anchors:
                continue

            object_key = str(artifact.get("object_key", "")).strip()
            if not object_key:
                object_key = self.find_artifact_object_key(
                    artifact_uris=[str(uri) for uri in artifact_uris],
                    origin_file=path,
                ) or ""
            if not object_key.endswith(".jsonl"):
                continue

            evidences = self._find_jsonl_anchor_evidence(
                object_key=object_key,
                anchors=anchors,
                get_bytes=get_bytes,
            )
            if evidences:
                artifact["evidencias_ancoras"] = evidences
        return loaded_artifacts

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
                parsed = json.loads(text)
                if self._is_table_artifact(parsed):
                    return {
                        "object_key": object_key,
                        "formato": "json",
                        "sample": self._table_evidence(parsed),
                    }
                return {
                    "object_key": object_key,
                    "formato": "json",
                    "sample": self.truncate_json(parsed),
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

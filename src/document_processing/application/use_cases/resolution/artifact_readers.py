from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path
from typing import Any

class ArtifactReaderMixin:
    def _load_json_from_uri_or_local(self, uri: str, *, local_fallback: str) -> dict[str, Any]:
        if uri.startswith("minio://"):
            try:
                object_key = self._parse_minio_uri(uri)
                return self.minio_client.get_json(object_key=object_key)
            except Exception as exc:
                logging.warning("Falha ao carregar %s do MinIO (%s). Usando fallback local.", uri, exc)
        return self._read_json(Path(self.project_paths.path(local_fallback)))

    def _load_json_from_minio_required(self, uri: str, *, artifact_name: str) -> dict[str, Any]:
        """Carrega JSON do MinIO sem fallback local para fluxos reais de DAG."""
        if not uri.startswith("minio://"):
            uri = self._minio_uri(uri)
        try:
            object_key = self._parse_minio_uri(uri)
            return self.minio_client.get_json(object_key=object_key)
        except Exception as exc:
            raise RuntimeError(
                f"Nao foi possivel carregar {artifact_name} obrigatorio no MinIO: {uri}"
            ) from exc

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
    def _read_json_array(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            raise RuntimeError(f"Arquivo JSON nao encontrado: {path}")
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, list) or any(not isinstance(item, dict) for item in loaded):
            raise RuntimeError(f"Esperado JSON lista de objetos em {path}")
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

    def _find_row_index(
        self,
        table: dict[str, Any],
        accepted: set[str],
        label_col: int,
        *,
        preferred_row_index: int | None = None,
    ) -> int | None:
        rows = list(table.get("rows", []))
        if preferred_row_index is not None and 0 <= preferred_row_index < len(rows):
            row = rows[preferred_row_index]
            if label_col < len(row):
                normalized = self._normalize_text(str(row[label_col]))
                if normalized in accepted:
                    return preferred_row_index

        for idx, row in enumerate(rows):
            if label_col >= len(row):
                continue
            normalized = self._normalize_text(str(row[label_col]))
            if normalized in accepted:
                return idx
        return None

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

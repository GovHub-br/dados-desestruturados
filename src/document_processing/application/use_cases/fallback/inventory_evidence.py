from __future__ import annotations

import json
import unicodedata
from collections.abc import Callable
from typing import Any


class FallbackInventoryEvidenceMixin:
    def _table_evidence(self, table: dict[str, Any]) -> dict[str, Any]:
        """Preserva tabelas pequenas e distribui janelas de tabelas grandes."""
        rows = table.get("rows", [])
        if not isinstance(rows, list):
            return self.truncate_json(table)
        base = {
            key: value
            for key, value in table.items()
            if key != "rows"
        }
        base["quantidade_linhas"] = len(rows)
        base["quantidade_colunas"] = max((len(row) for row in rows if isinstance(row, list)), default=0)
        compact_rows = json.dumps(rows, ensure_ascii=False)
        if len(rows) <= self.MAX_FULL_TABLE_ROWS and len(compact_rows) <= self.MAX_FULL_TABLE_CHARS:
            base["modo_linhas"] = "completo"
            base["rows"] = rows
            return base

        base["modo_linhas"] = "janelas_deterministicas"
        base["janelas"] = self._table_windows(rows)
        return base

    def _table_windows(self, rows: list[Any]) -> list[dict[str, Any]]:
        """Amostra inicio, meio e fim mantendo indices absolutos de linha."""
        if not rows:
            return []
        starts = {0, max(0, (len(rows) - self.TABLE_WINDOW_ROWS) // 2), max(0, len(rows) - self.TABLE_WINDOW_ROWS)}
        windows: list[dict[str, Any]] = []
        for start in sorted(starts):
            end = min(len(rows), start + self.TABLE_WINDOW_ROWS)
            windows.append({"linha_inicial": start, "linha_final": end - 1, "rows": rows[start:end]})
        return windows

    @staticmethod
    def _is_table_artifact(value: Any) -> bool:
        return isinstance(value, dict) and isinstance(value.get("schema"), list) and isinstance(value.get("rows"), list)

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
            object_key = FallbackInventoryEvidenceMixin.object_key_from_minio_uri(uri)
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

    def _find_jsonl_anchor_evidence(
        self,
        *,
        object_key: str,
        anchors: list[str],
        get_bytes: Callable[[str], bytes],
    ) -> list[dict[str, Any]]:
        """Busca uma ocorrencia literal normalizada por ancora no JSONL inteiro."""
        try:
            text = get_bytes(object_key).decode("utf-8", errors="replace")
        except Exception:
            return []

        pending = {
            self._normalized_text(anchor): anchor
            for anchor in anchors
            if self._normalized_text(anchor)
        }
        evidences: list[dict[str, Any]] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not pending or len(evidences) >= self.MAX_ANCHOR_EVIDENCES_PER_ARTIFACT:
                break
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record: Any = json.loads(stripped)
            except json.JSONDecodeError:
                record = stripped[:800]
            record_text = self._normalized_text(record)
            matched = [
                (normalized_anchor, original_anchor)
                for normalized_anchor, original_anchor in pending.items()
                if normalized_anchor in record_text
            ]
            for normalized_anchor, original_anchor in matched:
                evidences.append(
                    {
                        "ancora": original_anchor,
                        "linha": line_number,
                        "registro": self.truncate_json(record),
                    }
                )
                pending.pop(normalized_anchor, None)
        return evidences

    @staticmethod
    def _normalized_text(value: Any) -> str:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        return "".join(
            character
            for character in unicodedata.normalize("NFKD", text).casefold()
            if not unicodedata.combining(character)
        )

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

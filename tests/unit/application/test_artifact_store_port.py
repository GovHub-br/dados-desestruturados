from __future__ import annotations

import unittest
from typing import Any

from document_intelligence.application.ports import JsonArtifactStore


class InMemoryJsonArtifactStore:
    """Fake de teste para futuros casos de uso, sem MinIO."""

    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}

    def read_json(self, key: str) -> dict[str, Any]:
        return self._items[key]

    def write_json(self, key: str, payload: dict[str, Any]) -> None:
        self._items[key] = payload


class ArtifactStorePortTest(unittest.TestCase):
    def test_in_memory_fake_satisfies_json_artifact_store_contract(self) -> None:
        store: JsonArtifactStore = InMemoryJsonArtifactStore()

        store.write_json("teste/artefato.json", {"status": "ok"})

        self.assertEqual(store.read_json("teste/artefato.json"), {"status": "ok"})


if __name__ == "__main__":
    unittest.main()

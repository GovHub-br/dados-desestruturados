from __future__ import annotations

import re

from document_intelligence.infrastructure.storage.minio_artifact_repository import MinioStorageClient
from document_intelligence.shared.config.runtime import LocalPlatformConfig


class SemanticContractRegistry:
    """Resolve o contrato semanticamente ativo de uma familia documental."""

    _VERSION_PATTERN = re.compile(r"^v(\d+)\.(\d+)\.(\d+)/(?:[^/]+\.json)$")

    def __init__(self, *, config: LocalPlatformConfig, minio_client: MinioStorageClient) -> None:
        self.config = config
        self.minio_client = minio_client

    def latest_contract(self, domain: str) -> tuple[str, str]:
        """Retorna o unico contrato da maior versao semantica do dominio."""
        normalized_domain = str(domain).strip().strip("/")
        if not normalized_domain:
            raise RuntimeError("Dominio documental ausente para resolver contrato semantico.")

        prefix = f"contratos/{normalized_domain}/"
        candidates: list[tuple[tuple[int, int, int], str]] = []
        for key in self.minio_client.list_object_keys(prefix=prefix, suffix=".json"):
            relative = key.removeprefix(prefix)
            match = self._VERSION_PATTERN.fullmatch(relative)
            if match:
                candidates.append((tuple(int(part) for part in match.groups()), key))

        if not candidates:
            raise RuntimeError(
                f"Nenhum contrato semantico versionado encontrado para dominio={normalized_domain}."
            )

        latest_version = max(version for version, _key in candidates)
        latest_keys = [key for version, key in candidates if version == latest_version]
        if len(latest_keys) != 1:
            raise RuntimeError(
                "Mais de um contrato encontrado para a maior versao do dominio "
                f"{normalized_domain}: {sorted(latest_keys)}."
            )
        return latest_keys[0], ".".join(str(part) for part in latest_version)

    def latest_contract_uri(self, domain: str) -> tuple[str, str]:
        """Retorna URI MinIO e versao do contrato ativo do dominio."""
        key, version = self.latest_contract(domain)
        return f"minio://{self.config.minio_bucket}/{key}", version

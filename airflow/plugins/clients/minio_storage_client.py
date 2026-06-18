from __future__ import annotations

import io
import json
from pathlib import Path

from helpers import LocalPlatformConfig


class MinioStorageClient:
    """Cliente de persistencia dos documentos e artefatos no MinIO."""

    def __init__(self, config: LocalPlatformConfig) -> None:
        self.config = config

    def _client(self):
        """Cria o client MinIO a partir das variaveis centralizadas de runtime."""
        try:
            from minio import Minio
        except ImportError as exc:
            raise RuntimeError(
                "O pacote 'minio' nao esta instalado na imagem do Airflow. "
                "Recrie a imagem usando infra/airflow/Dockerfile."
            ) from exc

        return Minio(
            self.config.minio_endpoint,
            access_key=self.config.minio_access_key,
            secret_key=self.config.minio_secret_key,
            secure=self.config.minio_secure,
        )

    def ensure_bucket(self) -> None:
        """Garante que o bucket de data lake exista antes de gravar artefatos."""
        client = self._client()
        if not client.bucket_exists(self.config.minio_bucket):
            client.make_bucket(self.config.minio_bucket)

    def object_exists(self, object_key: str) -> bool:
        """Verifica se um objeto ja existe no bucket para evitar reprocessamento."""
        client = self._client()
        try:
            client.stat_object(self.config.minio_bucket, object_key)
            return True
        except Exception:
            return False

    def put_bytes(
        self,
        *,
        object_key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Persiste bytes no MinIO e retorna a URI minio:// correspondente."""
        self.ensure_bucket()
        client = self._client()
        client.put_object(
            self.config.minio_bucket,
            object_key,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        return f"minio://{self.config.minio_bucket}/{object_key}"

    def put_json(
        self,
        *,
        object_key: str,
        payload: dict[str, object],
    ) -> str:
        """Serializa um payload JSON e o grava no MinIO."""
        data = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        return self.put_bytes(object_key=object_key, data=data, content_type="application/json")

    def get_bytes(self, *, object_key: str) -> bytes:
        """Le bytes de um objeto no MinIO."""
        client = self._client()
        response = client.get_object(self.config.minio_bucket, object_key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def get_json(self, *, object_key: str) -> dict[str, object]:
        """Le e desserializa um JSON armazenado no MinIO."""
        payload = self.get_bytes(object_key=object_key)
        loaded = json.loads(payload.decode("utf-8"))
        if not isinstance(loaded, dict):
            raise RuntimeError(f"Objeto JSON esperado como dict em {object_key}.")
        return loaded

    def upload_directory(
        self,
        *,
        directory: str | Path,
        object_prefix: str,
    ) -> list[str]:
        """Envia recursivamente uma pasta local para um prefixo do MinIO."""
        self.ensure_bucket()
        client = self._client()
        root = Path(directory)
        uploaded: list[str] = []

        if not root.exists():
            raise RuntimeError(f"Diretorio de extracao nao encontrado: {root}")

        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            object_key = f"{object_prefix.rstrip('/')}/{relative}"
            client.fput_object(self.config.minio_bucket, object_key, str(path))
            uploaded.append(f"minio://{self.config.minio_bucket}/{object_key}")

        return uploaded

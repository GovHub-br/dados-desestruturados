"""Funções comuns aos scripts de lote da comparação de extrações do Docling.

Os scripts de lote rodam dentro do contêiner do Airflow (`ocr_airflow_scheduler`), que
já tem o cliente do MinIO, o `PYTHONPATH` do projeto e a rota até o runner. A pasta do
repositório é montada no contêiner, então o que for gravado em `extracoes/` aparece no
repositório local.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from minio import Minio

PREFIXO_ORIGEM = "documentos-origem/"
PREFIXO_EXECUCOES = "execucoes/"
RAIZ_SAIDA = Path(__file__).resolve().parents[1] / "extracoes"


def cliente_minio() -> tuple[Minio, str]:
    """Cliente do MinIO e bucket, a partir das variáveis do contêiner. Só se usa leitura."""
    cliente = Minio(
        os.environ["MINIO_ENDPOINT"],
        access_key=os.environ["MINIO_ROOT_USER"],
        secret_key=os.environ["MINIO_ROOT_PASSWORD"],
        secure=os.environ.get("MINIO_SECURE", "false").strip().lower() == "true",
    )
    return cliente, os.environ["MINIO_BUCKET_DATA_LAKE"]


def slug_do_pdf(object_name: str) -> str:
    """Nome curto e único da pasta de um PDF: `<entidade>__<nome-sem-prefixo-hash>`."""
    partes = object_name.removeprefix(PREFIXO_ORIGEM).split("/")
    entidade = partes[1] if len(partes) > 2 else partes[0]
    nome = partes[-1].removesuffix(".pdf").removesuffix(".PDF")
    nome = re.sub(r"^[0-9a-f]{16}_", "", nome)
    return f"{entidade}__{nome}"


def listar_pdfs(cliente: Minio, bucket: str) -> list[tuple[str, int]]:
    """Todos os PDFs de `documentos-origem/`, como (object_name, tamanho), em ordem estável."""
    objetos = cliente.list_objects(bucket, prefix=PREFIXO_ORIGEM, recursive=True)
    pdfs = [(o.object_name, o.size or 0) for o in objetos if o.object_name.lower().endswith(".pdf")]
    pdfs.sort()
    slugs: dict[str, str] = {}
    for nome, _ in pdfs:
        slug = slug_do_pdf(nome)
        if slug in slugs:
            raise SystemExit(f"slug repetido {slug!r}: {slugs[slug]} e {nome}")
        slugs[slug] = nome
    return pdfs

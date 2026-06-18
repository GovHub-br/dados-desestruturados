FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/opt/project/dados-desestruturados

WORKDIR /opt/project/dados-desestruturados

COPY requirements.txt /tmp/project-requirements.txt
COPY infra/airflow/scripts/apply_docling_vlm_patches.py /tmp/apply_docling_vlm_patches.py
COPY infra/docling-runner/entrypoint.sh /usr/local/bin/docling-runner-entrypoint.sh

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        libglib2.0-0 \
        libgl1 \
        libsm6 \
        libxext6 \
        libxrender1 \
        libxcb1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    -r /tmp/project-requirements.txt \
    && python /tmp/apply_docling_vlm_patches.py \
    && chmod +x /usr/local/bin/docling-runner-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/docling-runner-entrypoint.sh"]

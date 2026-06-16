ARG AIRFLOW_VERSION=3.0.2-python3.11
FROM apache/airflow:${AIRFLOW_VERSION}

COPY requirements.txt /tmp/project-requirements.txt
COPY infra/airflow/requirements-airflow.txt /tmp/requirements-airflow.txt
COPY infra/airflow/scripts/apply_docling_vlm_patches.py /tmp/apply_docling_vlm_patches.py

RUN pip install --no-cache-dir \
    -r /tmp/requirements-airflow.txt \
    -r /tmp/project-requirements.txt \
    && python /tmp/apply_docling_vlm_patches.py

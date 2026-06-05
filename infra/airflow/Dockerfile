ARG AIRFLOW_VERSION=3.0.2-python3.11
FROM apache/airflow:${AIRFLOW_VERSION}

COPY requirements.txt /tmp/project-requirements.txt
COPY infra/airflow/requirements-airflow.txt /tmp/requirements-airflow.txt

RUN pip install --no-cache-dir \
    -r /tmp/requirements-airflow.txt \
    -r /tmp/project-requirements.txt

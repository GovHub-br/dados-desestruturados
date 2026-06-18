ARG AIRFLOW_VERSION=3.0.2-python3.11
FROM apache/airflow:${AIRFLOW_VERSION}

COPY infra/airflow/requirements-airflow.txt /tmp/requirements-airflow.txt

USER airflow

RUN pip install --no-cache-dir \
    -r /tmp/requirements-airflow.txt

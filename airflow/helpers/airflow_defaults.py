"""Compatibilidade temporária; defaults de DAG vivem em ``dags._shared``."""

from dags._shared.airflow_defaults import *  # noqa: F401,F403

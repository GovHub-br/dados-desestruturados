"""Compatibilidade temporária; runtime de DAG vive em ``dags._shared``."""

from dags._shared.runtime import *  # noqa: F401,F403

from __future__ import annotations

import os
from datetime import date


class ReferenceDateResolver:
    """Resolve uma data de referencia opcional para simular a janela da DAG."""

    def __init__(self, env_var_names: tuple[str, ...] | None = None) -> None:
        self.env_var_names = env_var_names or ("REFERENCE_DATE", "PIPELINE_REFERENCE_DATE")

    def resolve(self, explicit_value: str | None = None) -> date | None:
        """Prioriza valor explicito e cai para variaveis de ambiente quando necessario."""
        raw_value = (explicit_value or "").strip() or self._env_value()
        if not raw_value:
            return None

        try:
            return date.fromisoformat(raw_value)
        except ValueError as exc:
            raise ValueError(
                "A reference_date informada deve estar no formato YYYY-MM-DD."
            ) from exc

    def _env_value(self) -> str:
        """Retorna a primeira variavel de ambiente preenchida para data de referencia."""
        for env_var_name in self.env_var_names:
            value = os.getenv(env_var_name, "").strip()
            if value:
                return value
        return ""


REFERENCE_DATE_RESOLVER = ReferenceDateResolver()

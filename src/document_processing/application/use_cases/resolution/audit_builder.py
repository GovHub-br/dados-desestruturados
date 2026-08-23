"""Construção do artefato de auditoria da resolução determinística."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


class ResolutionAuditBuilder:
    """Cria uma auditoria estável sem acessar armazenamento ou artefatos."""

    def build(
        self,
        *,
        loaded: dict[str, Any],
        validation: dict[str, Any],
        resolved: dict[str, Any],
    ) -> dict[str, Any]:
        runtime = loaded["runtime"]
        execution = loaded.get("execution", runtime.get("execution", {}))
        validation_status = validation["status_compatibilidade"]["status"]
        audit_items = list(resolved.get("auditoria_resolucao", []))
        resolved_count = sum(
            item.get("status_resolucao") == "resolvido" for item in audit_items
        )
        return {
            "tipo_artefato": "auditoria_resolucao",
            "dag_name": runtime.get("dag_name"),
            "execution_id": execution.get("execution_id"),
            "document_id": execution.get("document_id"),
            "executado_em": datetime.now(UTC).isoformat(),
            "status": "concluida" if validation_status == "compativel" else "incompleta",
            "summary": {
                "validation_status": validation_status,
                "periodo_referencia": resolved.get("schema_saida", {}).get("periodo_referencia"),
                "entidade": (
                    loaded["layout_signature"].get("entidade")
                    or loaded["layout_signature"].get("empresa")
                ),
                "campos_mapeamento_resolvidos": resolved_count,
                "campos_mapeamento_com_falha": len(audit_items) - resolved_count,
            },
            "auditoria_resolucao": audit_items,
        }

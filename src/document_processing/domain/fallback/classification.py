from __future__ import annotations

from typing import Any


class FallbackClassificationService:
    """Classifica a falha da DAG 2 antes de qualquer chamada LLM."""

    PARTIAL_SCOPE = "correcao_parcial_mapeamento"
    FULL_REMAP_SCOPE = "regeneracao_total_mapeamento"
    CREATION_SCOPE = "criacao_inicial_layout"
    UNSUPPORTED_SCOPE = "falha_nao_suportada_para_fallback_automatico"

    def classify_fallback_scope(
        self,
        validation: dict[str, Any],
        audit: dict[str, Any],
    ) -> dict[str, Any]:
        """Classifica deterministicamente o escopo permitido para a futura LLM."""
        status_info = validation.get("status_compatibilidade")
        if not isinstance(status_info, dict):
            raise RuntimeError("Nao foi possivel classificar fallback: validacao malformada.")

        status = str(status_info.get("status", "")).strip()
        if status == "compativel":
            raise RuntimeError("Fallback recusado: validacao compativel nao aciona DAG 3.")
        if status != "incompativel":
            return self._classification(
                scope=self.UNSUPPORTED_SCOPE,
                reasons=[f"status_compatibilidade desconhecido: {status or '<vazio>'}"],
                rejected_rules=[],
                unresolved_required=[],
                failure_codes=status_info.get("codigos_alerta", []),
            )

        rejected_rules = self.rejected_rules(validation)
        unresolved_required = self.unresolved_required_audit_items(audit)
        failure_codes = status_info.get("codigos_alerta", [])

        total_reasons: list[str] = []
        partial_reasons: list[str] = []
        unsupported_reasons: list[str] = []

        for rule in rejected_rules:
            rule_type = str(rule.get("tipo_teste", "")).strip()
            rule_id = str(rule.get("id_regra", "regra_sem_id")).strip()
            if rule_type == "arquivo_existe":
                total_reasons.append(f"tabela ou artefato critico ausente em {rule_id}")
            elif rule_type == "secao_existe":
                total_reasons.append(f"secao critica ausente em {rule_id}")
            elif rule_type == "perfil_colunas_periodo_existe_em_tabela":
                if self._has_unresolved_layout_profile(rule):
                    total_reasons.append(f"perfil critico declarado no layout nao resolvido em {rule_id}")
                else:
                    partial_reasons.append(f"coluna critica ausente em {rule_id}")
            elif rule_type == "linha_existe_em_tabela":
                partial_reasons.append(f"linha critica ausente em {rule_id}")
            elif rule_type == "valor_normalizavel":
                partial_reasons.append(f"valor nao normalizavel em {rule_id}")
            else:
                unsupported_reasons.append(
                    f"tipo de regra reprovada sem classificador automatico: {rule_type or '<vazio>'}"
                )

        if len(rejected_rules) >= 3:
            total_reasons.append("multiplas regras deterministicas criticas reprovadas")

        if unresolved_required:
            if len(unresolved_required) <= 2:
                partial_reasons.append("poucos campos obrigatorios nao resolvidos")
            else:
                total_reasons.append("multiplos campos obrigatorios nao resolvidos")

            if any(str(item.get("status_resolucao", "")) == "erro" for item in unresolved_required):
                partial_reasons.append("campo obrigatorio com seletor quebrado")

        if total_reasons:
            return self._classification(
                scope=self.FULL_REMAP_SCOPE,
                reasons=total_reasons,
                rejected_rules=rejected_rules,
                unresolved_required=unresolved_required,
                failure_codes=failure_codes,
            )

        if partial_reasons:
            return self._classification(
                scope=self.PARTIAL_SCOPE,
                reasons=partial_reasons,
                rejected_rules=rejected_rules,
                unresolved_required=unresolved_required,
                failure_codes=failure_codes,
            )

        if unsupported_reasons:
            return self._classification(
                scope=self.UNSUPPORTED_SCOPE,
                reasons=unsupported_reasons,
                rejected_rules=rejected_rules,
                unresolved_required=unresolved_required,
                failure_codes=failure_codes,
            )

        return self._classification(
            scope=self.UNSUPPORTED_SCOPE,
            reasons=["validacao incompativel sem falhas classificaveis para fallback automatico"],
            rejected_rules=rejected_rules,
            unresolved_required=unresolved_required,
            failure_codes=failure_codes,
        )

    def _classification(
        self,
        *,
        scope: str,
        reasons: list[str],
        rejected_rules: list[dict[str, Any]],
        unresolved_required: list[dict[str, Any]],
        failure_codes: Any,
    ) -> dict[str, Any]:
        """Monta a resposta padronizada da classificacao deterministica."""
        return {
            "fallback_scope": scope,
            "llm_permitida": scope != self.UNSUPPORTED_SCOPE,
            "motivos": sorted(set(reasons)),
            "codigos_falha": self._as_text_list(failure_codes),
            "metricas": {
                "regras_reprovadas": len(rejected_rules),
                "campos_obrigatorios_nao_resolvidos": len(unresolved_required),
            },
            "evidencias": {
                "regras_reprovadas": [
                    self._compact_rule_evidence(rule)
                    for rule in rejected_rules
                ],
                "campos_obrigatorios_nao_resolvidos": [
                    self._compact_audit_evidence(item)
                    for item in unresolved_required
                ],
            },
        }

    @staticmethod
    def rejected_rules(validation: dict[str, Any]) -> list[dict[str, Any]]:
        """Filtra regras deterministicas reprovadas na validacao da DAG 2."""
        rules = validation.get("regras_executadas", [])
        if not isinstance(rules, list):
            return []
        return [
            rule
            for rule in rules
            if isinstance(rule, dict) and str(rule.get("status", "")).strip() == "reprovada"
        ]

    @staticmethod
    def unresolved_required_audit_items(audit: dict[str, Any]) -> list[dict[str, Any]]:
        """Extrai campos obrigatorios nao resolvidos da auditoria da resolucao."""
        audit_items = audit.get("auditoria_resolucao", [])
        if isinstance(audit_items, list):
            return [
                item
                for item in audit_items
                if isinstance(item, dict)
                and bool(item.get("obrigatorio", False))
                and str(item.get("status_resolucao", "")).strip() != "resolvido"
            ]

        resolutions = audit.get("resolucoes", {})
        if not isinstance(resolutions, dict):
            return []

        unresolved: list[dict[str, Any]] = []
        for field, item in resolutions.items():
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or item.get("status_resolucao") or "").strip()
            if status and status != "resolvido":
                unresolved.append(
                    {
                        "campo_saida": str(field),
                        "status_resolucao": status,
                        "tipo_origem": item.get("tipo_origem"),
                        "arquivo_origem": item.get("arquivo_origem"),
                        "evidencia": item,
                    }
                )
        return unresolved

    @staticmethod
    def _has_unresolved_layout_profile(rule: dict[str, Any]) -> bool:
        """Identifica itens incompletos em um perfil critico declarado pelo layout."""
        evidence = rule.get("evidencia", {})
        if not isinstance(evidence, dict):
            return False
        profile_items = (
            evidence.get("itens_perfil_resolvidos")
            or evidence.get("itens_resolvidos")
            or evidence.get("papeis_periodo_resolvidos", [])
        )
        if not isinstance(profile_items, list):
            return False
        for item in profile_items:
            if not isinstance(item, dict):
                continue
            observed_value = str(
                item.get("valor_encontrado")
                or item.get("cabecalho_encontrado")
                or item.get("valor_observado")
                or ""
            ).strip()
            if item.get("ok") is False or not observed_value:
                return True
        return False

    @staticmethod
    def _compact_rule_evidence(rule: dict[str, Any]) -> dict[str, Any]:
        """Reduz uma regra reprovada aos campos uteis para logs e prompt futuro."""
        evidence = rule.get("evidencia", {})
        return {
            "id_regra": rule.get("id_regra"),
            "tipo_teste": rule.get("tipo_teste"),
            "codigo_falha": rule.get("codigo_falha"),
            "arquivo_origem": evidence.get("arquivo_origem") if isinstance(evidence, dict) else None,
        }

    @staticmethod
    def _compact_audit_evidence(item: dict[str, Any]) -> dict[str, Any]:
        """Reduz uma falha de campo obrigatorio aos campos uteis para fallback."""
        return {
            "campo_saida": item.get("campo_saida"),
            "tipo_origem": item.get("tipo_origem"),
            "arquivo_origem": item.get("arquivo_origem"),
            "status_resolucao": item.get("status_resolucao"),
        }

    @staticmethod
    def _as_text_list(value: Any) -> list[str]:
        """Normaliza codigos de falha para lista textual."""
        if isinstance(value, list):
            return [str(item) for item in value]
        if value is None:
            return []
        return [str(value)]


FALLBACK_CLASSIFICATION_SERVICE = FallbackClassificationService()

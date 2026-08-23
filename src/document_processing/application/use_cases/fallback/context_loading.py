"""Componente especializado do caso de uso de fallback LLM."""

from __future__ import annotations

from ._common import *  # noqa: F401,F403


class FallbackContextLoadingMixin:
    def load_fallback_context(self, conf: dict[str, object]) -> dict[str, Any]:
        """Carrega e valida o pacote minimo de artefatos da execucao com falha."""
        entity_slug = str(conf.get("entity_slug") or conf.get("company_slug") or "").strip()
        if not entity_slug:
            raise RuntimeError("Contexto de fallback sem entity_slug.")
        fallback_context = {
            "domain": str(conf.get("domain") or self.config_loader.load_local_platform_config().dominio).strip(),
            "entity_slug": entity_slug,
            "document_id": self._required_text(conf, "document_id"),
            "execution_id": self._required_text(conf, "execution_id"),
            "manifest_key": self._required_text(conf, "manifest_key"),
            "trigger_origin_dag": self._required_text(conf, "trigger_origin_dag"),
        }
        entity_name = str(conf.get("entity_name") or conf.get("company_name") or "").strip()
        if entity_name:
            fallback_context["entity_name"] = entity_name
        legacy_company_slug = str(conf.get("company_slug", "")).strip()
        if legacy_company_slug:
            fallback_context["company_slug"] = legacy_company_slug
        for optional_field in (
            "fallback_mode",
            "motivo",
            "source_execution_id",
            "fallback_execution_id",
            "contrato_semantico_uri",
        ):
            value = str(conf.get(optional_field, "")).strip()
            if value:
                fallback_context[optional_field] = value

        if self._is_initial_layout_creation_context(fallback_context):
            return self._load_initial_layout_creation_context(fallback_context)

        validation_key, validation = self.load_validation_artifact(fallback_context)
        self._assert_validation_requires_fallback(validation, validation_key)
        audit_key, audit = self.load_audit_artifact(fallback_context)
        layout_key, layout = self.load_base_layout_signature(fallback_context)
        contract_key, contract = self.load_semantic_contract(fallback_context)
        manifest_key, manifest = self.load_extraction_manifest(fallback_context)
        fallback_classification = self.classify_fallback_scope(validation, audit)
        inventory_key, inventory = self.inventory_service.load_extraction_inventory(
            manifest=manifest,
            load_json_object=self._load_json_object,
        )

        artifact_uris = manifest.get("artifact_uris")
        if not isinstance(artifact_uris, list) or not artifact_uris:
            raise RuntimeError(f"Manifesto de extracao sem artifact_uris: {manifest_key}")

        fallback_problem_context = self.build_fallback_problem_context(
            validation=validation,
            audit=audit,
            layout=layout,
            contract=contract,
            manifest=manifest,
            classification=fallback_classification,
            inventory=inventory,
            inventory_key=inventory_key,
        )
        fallback_problem_context["fallback_context"] = fallback_context
        fallback_problem_context["layout_signature_base_ref"] = {
            "versao": layout.get("versao_artefato"),
            "object_key": layout_key,
        }
        fallback_problem_context["layout_signature_base_editable_sections"] = {
            "fontes_relevantes": layout.get("fontes_relevantes", {}),
            "regras_deteccao_mudanca": layout.get("regras_deteccao_mudanca", []),
            "mapeamento_canonico": layout.get("mapeamento_canonico", {}),
        }
        fallback_problem_context["layout_signature_base_validation_context"] = {
            "mapeamento_canonico_paths": sorted(
                layout.get("mapeamento_canonico", {}).keys()
                if isinstance(layout.get("mapeamento_canonico"), dict)
                else []
            ),
            "regras_deteccao_mudanca_ids": [
                str(rule.get("id_regra"))
                for rule in layout.get("regras_deteccao_mudanca", [])
                if isinstance(rule, dict) and rule.get("id_regra")
            ],
        }
        fallback_problem_context["llm_payloads"] = self.context_builder.build_llm_payloads(
            fallback_problem_context
        )

        return {
            "fallback_context": fallback_context,
            "validation_status": validation["status_compatibilidade"]["status"],
            "failure_codes": validation["status_compatibilidade"].get("codigos_alerta", []),
            "fallback_scope": fallback_classification["fallback_scope"],
            "fallback_classification": fallback_classification,
            "fallback_problem_context": fallback_problem_context,
            "llm_constraints": {
                "fallback_scope": fallback_classification["fallback_scope"],
                "chamar_llm": fallback_classification["llm_permitida"],
                "permitir_correcao_parcial": (
                    fallback_classification["fallback_scope"] == self.PARTIAL_SCOPE
                ),
                "permitir_regeneracao_total": (
                    fallback_classification["fallback_scope"] == self.FULL_REMAP_SCOPE
                ),
            },
            "object_keys": {
                "validacao_layout_signature": validation_key,
                "auditoria_resolucao": audit_key,
                "layout_signature_base": layout_key,
                "contrato_semantico": contract_key,
                "manifesto_extracao": manifest_key,
                "inventario_extracao": inventory_key,
            },
            "artifact_counts": {
                "regras_executadas": len(validation.get("regras_executadas", [])),
                "auditoria_resolucao": len(audit.get("auditoria_resolucao", [])),
                "mapeamento_canonico": len(layout.get("mapeamento_canonico", {})),
                "schema_saida_campos_raiz": len(contract.get("schema_saida", {})),
                "artefatos_extracao": len(artifact_uris),
                "itens_inventario": len(inventory.get("items", [])) if isinstance(inventory, dict) else 0,
            },
        }


    def _load_initial_layout_creation_context(
        self,
        fallback_context: dict[str, str],
    ) -> dict[str, Any]:
        """Carrega contexto da DAG 3 quando ainda nao existe layout signature base."""
        contract_key, contract = self.load_semantic_contract(fallback_context)
        manifest_key, manifest = self.load_extraction_manifest(fallback_context)
        fallback_classification = self._initial_layout_creation_classification()
        inventory_key, inventory = self.inventory_service.load_extraction_inventory(
            manifest=manifest,
            load_json_object=self._load_json_object,
        )

        artifact_uris = manifest.get("artifact_uris")
        if not isinstance(artifact_uris, list) or not artifact_uris:
            raise RuntimeError(f"Manifesto de extracao sem artifact_uris: {manifest_key}")

        validation = {
            "tipo_artefato": "evento_criacao_inicial_layout",
            "status_compatibilidade": {
                "status": "layout_signature_ausente",
                "codigos_alerta": ["LAYOUT_SIGNATURE_AUSENTE"],
            },
            "regras_executadas": [],
        }
        audit = {"tipo_artefato": "auditoria_resolucao_ausente", "auditoria_resolucao": []}
        layout: dict[str, Any] = {}

        fallback_problem_context = self.build_fallback_problem_context(
            validation=validation,
            audit=audit,
            layout=layout,
            contract=contract,
            manifest=manifest,
            classification=fallback_classification,
            inventory=inventory,
            inventory_key=inventory_key,
        )
        fallback_problem_context["fallback_context"] = fallback_context
        fallback_problem_context["layout_signature_base_ref"] = None
        fallback_problem_context["layout_signature_base_editable_sections"] = {}
        fallback_problem_context["layout_signature_base_validation_context"] = {
            "mapeamento_canonico_paths": [],
            "regras_deteccao_mudanca_ids": [],
        }
        initial_layout_skeleton = self._build_initial_layout_skeleton(
            contract_key=contract_key,
            contract=contract,
            manifest_key=manifest_key,
            manifest=manifest,
            fallback_context=fallback_context,
        )
        fallback_problem_context["debug_metadata"]["modo_criacao_inicial_layout"] = True
        fallback_problem_context["llm_payloads"] = self.context_builder.build_llm_payloads(
            fallback_problem_context
        )

        return {
            "fallback_context": fallback_context,
            "validation_status": "layout_signature_ausente",
            "failure_codes": ["LAYOUT_SIGNATURE_AUSENTE"],
            "fallback_scope": fallback_classification["fallback_scope"],
            "fallback_classification": fallback_classification,
            "fallback_problem_context": fallback_problem_context,
            "initial_layout_skeleton": initial_layout_skeleton,
            "llm_constraints": {
                "fallback_scope": fallback_classification["fallback_scope"],
                "chamar_llm": fallback_classification["llm_permitida"],
                "permitir_correcao_parcial": False,
                "permitir_regeneracao_total": False,
                "permitir_criacao_inicial_layout": True,
            },
            "object_keys": {
                "validacao_layout_signature": None,
                "auditoria_resolucao": None,
                "layout_signature_base": None,
                "contrato_semantico": contract_key,
                "manifesto_extracao": manifest_key,
                "inventario_extracao": inventory_key,
            },
            "artifact_counts": {
                "regras_executadas": 0,
                "auditoria_resolucao": 0,
                "mapeamento_canonico": 0,
                "schema_saida_campos_raiz": len(contract.get("schema_saida", {})),
                "artefatos_extracao": len(artifact_uris),
                "itens_inventario": len(inventory.get("items", [])) if isinstance(inventory, dict) else 0,
            },
        }


    @staticmethod
    def _is_initial_layout_creation_context(fallback_context: dict[str, str]) -> bool:
        """Identifica o modo em que nao existe layout signature base."""
        return (
            str(fallback_context.get("fallback_mode", "")).strip() == "criacao_inicial_layout"
            or str(fallback_context.get("motivo", "")).strip() == "layout_signature_ausente"
        )


    def _initial_layout_creation_classification(self) -> dict[str, Any]:
        """Classificacao deterministica para criacao inicial de layout."""
        return {
            "fallback_scope": self.CREATION_SCOPE,
            "llm_permitida": True,
            "motivos": ["layout_signature_ausente"],
            "codigos_falha": ["LAYOUT_SIGNATURE_AUSENTE"],
            "metricas": {
                "regras_reprovadas": 0,
                "campos_obrigatorios_nao_resolvidos": 0,
            },
            "evidencias": {
                "regras_reprovadas": [],
                "campos_obrigatorios_nao_resolvidos": [],
            },
        }


    def classify_fallback_scope(
        self,
        validation: dict[str, Any],
        audit: dict[str, Any],
    ) -> dict[str, Any]:
        """Encaminha a classificacao para o servico dedicado."""
        return self.classification_service.classify_fallback_scope(validation, audit)


    def build_fallback_problem_context(
        self,
        *,
        validation: dict[str, Any],
        audit: dict[str, Any],
        layout: dict[str, Any],
        contract: dict[str, Any],
        manifest: dict[str, Any],
        classification: dict[str, Any],
        inventory: dict[str, Any],
        inventory_key: str | None,
    ) -> dict[str, Any]:
        """Encaminha a montagem de contexto para o builder dedicado."""
        return self.context_builder.build_fallback_problem_context(
            validation=validation,
            audit=audit,
            layout=layout,
            contract=contract,
            manifest=manifest,
            classification=classification,
            inventory=inventory,
            inventory_key=inventory_key,
        )

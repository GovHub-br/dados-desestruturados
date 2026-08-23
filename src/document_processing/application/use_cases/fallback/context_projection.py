"""Componente especializado da projeção de contexto do fallback."""

from __future__ import annotations

from ._context_support import *  # noqa: F401,F403


class FallbackContextProjectionMixin:
    @staticmethod
    def _candidate_execution_context(context: dict[str, Any]) -> dict[str, Any]:
        """Monta somente os identificadores que o candidato precisa devolver."""
        fallback_context = context.get("fallback_context", {})
        if not isinstance(fallback_context, dict):
            fallback_context = {}
        scope = context.get("escopo_permitido")
        base_ref = context.get("layout_signature_base_ref")
        return {
            "document_id": fallback_context.get("document_id"),
            "execution_id_origem": fallback_context.get("execution_id"),
            "escopo_correcao": scope,
            "base_layout_signature": (
                None if scope == "criacao_inicial_layout" else base_ref
            ),
        }


    @staticmethod
    def _failure_summary(context: dict[str, Any]) -> dict[str, Any]:
        """Resumo de falha para fluxos de redescoberta ampla."""
        failure = context.get("falha", {})
        if not isinstance(failure, dict):
            return {}
        return {
            "codigos_falha": failure.get("codigos_falha", []),
            "motivos": failure.get("motivos", []),
        }


    @staticmethod
    def _weak_layout_reference(context: dict[str, Any]) -> dict[str, Any]:
        """Referencia fraca ao layout anterior, usada apenas como pista."""
        layout_context = context.get("layout_signature_relevante", {})
        if not isinstance(layout_context, dict) or not layout_context:
            return {}
        identification = layout_context.get("identificacao", {})
        return {
            "entidade": (
                identification.get("entidade") or identification.get("empresa")
                if isinstance(identification, dict)
                else None
            ),
            "tipo_documento": (
                identification.get("tipo_documento")
                if isinstance(identification, dict)
                else None
            ),
            "fontes_relevantes_antigas": layout_context.get("fontes_relevantes", []),
            "observacao": (
                "usar apenas como pista; redescobrir fontes pelo inventario atual"
            ),
        }


    @staticmethod
    def _broken_output_fields(unresolved_required: list[dict[str, Any]]) -> list[str]:
        """Lista campos de saida afetados por falhas de resolucao."""
        fields = {
            str(item.get("campo_saida", "")).strip()
            for item in unresolved_required
            if str(item.get("campo_saida", "")).strip()
        }
        return sorted(fields)


    def _collect_origin_files(
        self,
        *,
        rejected_rules: list[dict[str, Any]],
        unresolved_required: list[dict[str, Any]],
        layout: dict[str, Any],
        broken_fields: list[str],
    ) -> list[str]:
        """Coleta arquivos de extracao que explicam as falhas classificadas."""
        origin_files: set[str] = set()

        for rule in rejected_rules:
            evidence = rule.get("evidencia", {})
            if isinstance(evidence, dict):
                origin = str(evidence.get("arquivo_origem", "")).strip()
                if origin:
                    origin_files.add(origin)

        for item in unresolved_required:
            origin = str(item.get("arquivo_origem", "")).strip()
            if origin:
                origin_files.add(origin)

        mapping = layout.get("mapeamento_canonico", {})
        if isinstance(mapping, dict):
            for field in broken_fields:
                entry = mapping.get(field)
                if isinstance(entry, dict):
                    origin = str(entry.get("arquivo_origem", "")).strip()
                    if origin:
                        origin_files.add(origin)

        return sorted(origin_files)


    def _relevant_layout_context(
        self,
        *,
        layout: dict[str, Any],
        broken_fields: list[str],
        origin_files: list[str],
    ) -> dict[str, Any]:
        """Recorta o layout signature para os trechos ligados a falha."""
        mapping = layout.get("mapeamento_canonico", {})
        relevant_mapping: dict[str, Any] = {}
        if isinstance(mapping, dict):
            for path, entry in mapping.items():
                if not isinstance(entry, dict):
                    continue
                origin = str(entry.get("arquivo_origem", "")).strip()
                path_text = str(path)
                if path_text in broken_fields or origin in origin_files:
                    relevant_mapping[path_text] = self._truncate_json(entry)

        rules = layout.get("regras_deteccao_mudanca", [])
        relevant_rules: list[Any] = []
        if isinstance(rules, list):
            for rule in rules:
                if not isinstance(rule, dict):
                    continue
                origin = str(rule.get("arquivo_origem", "")).strip()
                if origin and origin in origin_files:
                    relevant_rules.append(self._truncate_json(rule))

        return {
            "identificacao": {
                "entidade": layout.get("entidade") or layout.get("empresa"),
                "tipo_documento": layout.get("tipo_documento"),
                "versao_artefato": layout.get("versao_artefato"),
                "contrato_semantico_ref": layout.get("contrato_semantico_ref"),
            },
            "mapeamento_canonico_relevante": relevant_mapping,
            "regras_deteccao_mudanca_relevantes": relevant_rules,
            "fontes_relevantes": origin_files,
        }


    def _relevant_contract_context(
        self,
        *,
        contract: dict[str, Any],
        broken_fields: list[str],
    ) -> dict[str, Any]:
        """Recorta o contrato semantico sem incluir conteudo desnecessario."""
        semantic = contract.get("contrato_semantico", {})
        if not isinstance(semantic, dict):
            semantic = {}
        schema_saida = contract.get("schema_saida", {})
        fixed_paths = contract_literal_paths(schema_saida)
        relevant_requirements = self._dynamic_mapping_requirements(
            semantic.get("requisitos_mapeamento", {})
            if isinstance(semantic, dict)
            else {},
            fixed_paths=set(fixed_paths),
        )
        structure = {
            "campos_raiz": sorted(
                schema_saida.keys()
                if isinstance(schema_saida, dict)
                else []
            ),
            "paths_permitidos": sorted(schema_paths(schema_saida) - set(fixed_paths)),
            "arrays_que_exigem_seletor": sorted(schema_array_paths(schema_saida)),
        }
        return {
            "identificacao": {
                "nome": contract.get("nome"),
                "versao": contract.get("versao"),
                "dominio": contract.get("dominio"),
            },
            "contrato_semantico": {
                "entidades": semantic.get("entidades", {}),
                "metricas": semantic.get("metricas", {}),
                "requisitos_mapeamento": relevant_requirements,
            },
            "estrutura_schema_saida": structure,
        }


    @staticmethod
    def _dynamic_mapping_requirements(
        requirements: Any,
        *,
        fixed_paths: set[str],
    ) -> dict[str, Any]:
        """Remove do payload os contextos ja resolvidos por literais do contrato."""
        if not isinstance(requirements, dict):
            return {}
        projected = deepcopy(requirements)
        fields = projected.get("campos_obrigatorios", [])
        if not isinstance(fields, list):
            return projected

        for requirement in fields:
            if not isinstance(requirement, dict):
                continue
            path = str(requirement.get("path", "")).strip()
            parent_path, separator, _leaf = path.rpartition(".")
            if not separator:
                continue
            observations = requirement.get("observacoes_obrigatorias", [])
            if not isinstance(observations, list):
                continue
            for observation in observations:
                if not isinstance(observation, dict):
                    continue
                context_fields = observation.get("campos_contexto_obrigatorios", [])
                if not isinstance(context_fields, list):
                    continue
                observation["campos_contexto_obrigatorios"] = [
                    field
                    for field in context_fields
                    if f"{parent_path}.{str(field).strip()}" not in fixed_paths
                ]
        return projected


    @staticmethod
    def _mappable_targets(contract_context: Any) -> list[dict[str, Any]]:
        """Deriva alvos explicitamente declarados pelo contrato para a LLM."""
        requirements = mapping_requirements_from_context(
            contract_context
        )
        structure = contract_context.get("estrutura_schema_saida", {})
        array_paths = (
            structure.get("arrays_que_exigem_seletor", [])
            if isinstance(structure, dict)
            else []
        )
        if not isinstance(array_paths, list):
            array_paths = []
        return mappable_targets_payload(requirements, array_paths=array_paths)


    def _schema_fragments_for_fields(
        self,
        schema_saida: Any,
        broken_fields: list[str],
    ) -> dict[str, Any]:
        """Extrai fragmentos do schema_saida relacionados aos campos quebrados."""
        if not isinstance(schema_saida, dict):
            return {}
        if not broken_fields:
            return self._truncate_json(schema_saida, max_depth=2)

        fragments: dict[str, Any] = {}
        for field in broken_fields:
            root = field.split(".", maxsplit=1)[0]
            if root in schema_saida:
                fragments[root] = self._truncate_json(schema_saida[root], max_depth=4)
        return fragments


    def _truncate_json(self, value: Any, *, max_depth: int = 5) -> Any:
        """Reduz estruturas grandes para caberem no contexto de problema."""
        if max_depth <= 0:
            return "<truncado>"
        if isinstance(value, dict):
            return {
                str(key): self._truncate_json(item, max_depth=max_depth - 1)
                for key, item in list(value.items())[:20]
            }
        if isinstance(value, list):
            return [
                self._truncate_json(item, max_depth=max_depth - 1)
                for item in value[:8]
            ]
        if isinstance(value, str) and len(value) > 800:
            return f"{value[:800]}..."
        return value

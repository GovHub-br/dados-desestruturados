from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from .models import LayoutSignatureCandidate


class FallbackCandidateValidationService:
    """Valida candidatos de layout signature gerados pela LLM."""

    PARTIAL_SCOPE = "correcao_parcial_mapeamento"
    FULL_REMAP_SCOPE = "regeneracao_total_mapeamento"
    CREATION_SCOPE = "criacao_inicial_layout"

    def validate_candidate_layout(
        self,
        candidate: dict[str, Any],
        fallback_problem_context: dict[str, Any],
    ) -> LayoutSignatureCandidate:
        """Valida o candidato da LLM com Pydantic e regras do contrato carregado."""
        if self._contains_forbidden_llm_key(candidate):
            raise RuntimeError(
                "Resposta da LLM tentou alterar campos proibidos para o fallback."
            )

        try:
            candidate_model = LayoutSignatureCandidate.model_validate(candidate)
        except ValidationError as exc:
            raise RuntimeError(
                "Resposta da LLM nao respeita o contrato Pydantic do layout "
                f"signature candidato: {exc}"
            ) from exc

        schema_roots = self._contract_schema_roots_from_context(fallback_problem_context)
        schema_paths = self._contract_schema_paths_from_context(fallback_problem_context)
        for mapping_path in candidate_model.mapeamento_canonico:
            if not self._mapping_path_is_in_contract(
                mapping_path,
                schema_roots,
                schema_paths,
            ):
                raise RuntimeError(
                    "Resposta da LLM tentou criar candidato com mapeamento para "
                    f"campo fora do schema_saida do contrato: {mapping_path}."
                )

        allowed_scope = str(fallback_problem_context.get("escopo_permitido", "")).strip()
        if allowed_scope and candidate_model.escopo_correcao != allowed_scope:
            raise RuntimeError(
                "Resposta da LLM tentou usar escopo diferente do permitido pela "
                f"classificacao deterministica: {candidate_model.escopo_correcao}."
            )

        self._validate_candidate_lineage(candidate_model, fallback_problem_context)
        self._validate_candidate_allowed_scope(candidate_model, fallback_problem_context)
        self._validate_candidate_extra_sections(candidate_model)
        self._validate_candidate_does_not_write_final_values(candidate_model)
        self._validate_partial_candidate_does_not_remove_unrelated_mappings(
            candidate_model,
            fallback_problem_context,
        )
        return candidate_model

    @staticmethod
    def _validate_candidate_lineage(
        candidate: LayoutSignatureCandidate,
        fallback_problem_context: dict[str, Any],
    ) -> None:
        """Confirma que o candidato usa a linhagem recebida no contexto."""
        fallback_context = fallback_problem_context.get("fallback_context", {})
        if not isinstance(fallback_context, dict):
            raise RuntimeError("Contexto de fallback ausente para validar linhagem do candidato.")

        expected_document_id = str(fallback_context.get("document_id", "")).strip()
        expected_execution_id = str(fallback_context.get("execution_id", "")).strip()
        if candidate.document_id != expected_document_id:
            raise RuntimeError(
                "Layout candidato retornou document_id diferente do contexto de fallback."
            )
        if candidate.execution_id_origem != expected_execution_id:
            raise RuntimeError(
                "Layout candidato retornou execution_id_origem diferente do contexto de fallback."
            )

        base_ref = fallback_problem_context.get("layout_signature_base_ref", {})
        if not isinstance(base_ref, dict):
            raise RuntimeError("Referencia do layout base ausente para validar candidato.")
        expected_base_key = str(base_ref.get("object_key", "")).strip()
        if candidate.base_layout_signature.object_key != expected_base_key:
            raise RuntimeError(
                "Layout candidato retornou base_layout_signature.object_key diferente do layout base."
            )

    def _validate_candidate_allowed_scope(
        self,
        candidate: LayoutSignatureCandidate,
        fallback_problem_context: dict[str, Any],
    ) -> None:
        """Garante que candidato total ou inicial so apareca quando explicitamente permitido."""
        allowed_scope = str(fallback_problem_context.get("escopo_permitido", "")).strip()
        if candidate.escopo_correcao == self.FULL_REMAP_SCOPE and allowed_scope != self.FULL_REMAP_SCOPE:
            raise RuntimeError(
                "Layout candidato tentou regeneracao total sem ruptura estrutural ampla."
            )
        if candidate.escopo_correcao == self.CREATION_SCOPE and allowed_scope != self.CREATION_SCOPE:
            raise RuntimeError(
                "Layout candidato tentou criacao inicial sem modo explicitamente permitido."
            )

    def _validate_candidate_extra_sections(
        self,
        candidate: LayoutSignatureCandidate,
    ) -> None:
        """Permite secoes extras somente em candidato completo."""
        extra_sections = set((candidate.model_extra or {}).keys())
        if not extra_sections:
            return
        if candidate.escopo_correcao == self.PARTIAL_SCOPE:
            raise RuntimeError(
                "Layout candidato parcial tentou incluir secoes extras fora do patch permitido: "
                f"{sorted(extra_sections)}."
            )
        if candidate.escopo_correcao not in {self.FULL_REMAP_SCOPE, self.CREATION_SCOPE}:
            raise RuntimeError(
                "Layout candidato tentou incluir secoes extras em escopo nao permitido."
            )

    def _validate_candidate_does_not_write_final_values(
        self,
        candidate: LayoutSignatureCandidate,
    ) -> None:
        """Bloqueia sinais de valores finais de negocio no candidato de layout."""
        candidate_dict = candidate.model_dump(mode="json", exclude_none=True)
        forbidden_keys = {
            "valor_resolvido",
            "valor_final",
            "valor_extraido",
            "schema_saida_resolvido",
            "dados_resolvidos",
            "resultado_resolvido",
        }
        if self._contains_any_key(candidate_dict, forbidden_keys):
            raise RuntimeError(
                "Layout candidato tentou escrever valores finais em vez de seletores/layout."
            )

    def _validate_partial_candidate_does_not_remove_unrelated_mappings(
        self,
        candidate: LayoutSignatureCandidate,
        fallback_problem_context: dict[str, Any],
    ) -> None:
        """Impede que correcao parcial apague mapeamentos nao relacionados a falha."""
        if candidate.escopo_correcao != self.PARTIAL_SCOPE:
            return

        base_context = fallback_problem_context.get("layout_signature_base_validation_context", {})
        if not isinstance(base_context, dict):
            return
        base_paths_raw = base_context.get("mapeamento_canonico_paths", [])
        if not isinstance(base_paths_raw, list):
            return

        base_paths = {str(path) for path in base_paths_raw}
        candidate_paths = set(candidate.mapeamento_canonico)
        if not base_paths or not candidate_paths:
            return

        missing_paths = base_paths - candidate_paths
        if missing_paths:
            sample = sorted(missing_paths)[:10]
            raise RuntimeError(
                "Layout candidato parcial removeu mapeamentos do layout base. "
                f"Exemplos: {sample}."
            )

    @staticmethod
    def _contract_schema_roots_from_context(
        fallback_problem_context: dict[str, Any],
    ) -> set[str]:
        """Extrai campos raiz do schema_saida incluidos no contexto da LLM."""
        contract = fallback_problem_context.get("contrato_semantico_relevante", {})
        if not isinstance(contract, dict):
            return set()
        roots = contract.get("schema_saida_campos_raiz", [])
        if not isinstance(roots, list):
            return set()
        return {str(root).strip() for root in roots if str(root).strip()}

    @staticmethod
    def _contract_schema_paths_from_context(
        fallback_problem_context: dict[str, Any],
    ) -> set[str]:
        """Extrai paths declarados no schema_saida incluidos no contexto da LLM."""
        contract = fallback_problem_context.get("contrato_semantico_relevante", {})
        if not isinstance(contract, dict):
            return set()
        paths = contract.get("schema_saida_paths", [])
        if not isinstance(paths, list):
            return set()
        return {str(path).strip() for path in paths if str(path).strip()}

    @staticmethod
    def _mapping_path_is_in_contract(
        path: str,
        schema_roots: set[str],
        schema_paths: set[str],
    ) -> bool:
        """Confirma que o path de mapeamento aponta para path do contrato."""
        if not schema_roots:
            return False
        normalized = path.strip()
        if normalized.startswith("mapeamento_canonico."):
            normalized = normalized.removeprefix("mapeamento_canonico.")
        normalized = FallbackCandidateValidationService._normalize_mapping_path(normalized)
        if schema_paths and normalized not in schema_paths:
            return False
        root = normalized.split(".", maxsplit=1)[0]
        return root in schema_roots

    @staticmethod
    def _normalize_mapping_path(path: str) -> str:
        """Remove filtros de array para comparar mapeamento com schema_saida."""
        parts = []
        for part in path.split("."):
            clean = part.split("[", maxsplit=1)[0].strip()
            if clean:
                parts.append(clean)
        return ".".join(parts)

    def _contains_forbidden_llm_key(self, value: Any) -> bool:
        """Bloqueia chaves que indicam tentativa de alterar fronteiras proibidas."""
        forbidden = {
            "schema_saida",
            "schema_saida_resolvido",
            "referencia_contrato_semantico",
            "contrato_semantico",
            "regras_execucao",
            "versao_artefato",
        }
        return self._contains_any_key(value, forbidden)

    def _contains_any_key(self, value: Any, forbidden: set[str]) -> bool:
        """Busca qualquer chave proibida em uma estrutura JSON."""
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key) in forbidden:
                    return True
                if self._contains_any_key(item, forbidden):
                    return True
        if isinstance(value, list):
            return any(self._contains_any_key(item, forbidden) for item in value)
        return False


FALLBACK_CANDIDATE_VALIDATION_SERVICE = FallbackCandidateValidationService()

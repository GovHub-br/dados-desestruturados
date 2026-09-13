from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from document_processing.domain.contracts.mapping_requirements import (
    MappingRequirementsError,
    mapping_requirements_from_context,
    parsed_mapping_path,
)
from document_processing.domain.contracts.schema import normalize_schema_path
from document_processing.domain.layouts.paths import (
    normalize_mapping_path,
    split_mapping_path,
)

from .mapping_plan import MappingPlanService, MappingUnit
from .models import (
    LayoutSignatureCandidate,
    LayoutSignatureFragment,
    UnmappedRequiredField,
)


class UnmappedRequiredFieldsError(RuntimeError):
    """A LLM declarou corretamente que a evidencia nao cobre campo obrigatorio."""

    def __init__(self, fields: list[UnmappedRequiredField]) -> None:
        self.fields = fields
        details = [
            {
                "path": field.path,
                "seletores": field.seletores,
                "motivo": field.motivo,
                "artefatos_verificados": field.artefatos_verificados,
            }
            for field in fields
        ]
        super().__init__(
            "Evidencia insuficiente para requisitos obrigatorios do contrato: "
            f"{details}."
        )


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
        array_paths = self._contract_schema_array_paths_from_context(
            fallback_problem_context
        )
        fixed_paths = {
            str(path).strip()
            for path in fallback_problem_context.get("_paths_fixos_do_contrato", [])
            if str(path).strip()
        }
        for mapping_path in candidate_model.mapeamento_canonico:
            if normalize_schema_path(mapping_path) in fixed_paths:
                raise RuntimeError(
                    "Resposta da LLM tentou mapear valor fixo do contrato semantico: "
                    f"{mapping_path}. Esse valor e preenchido deterministicamente pela DAG 2."
                )
            if not self._mapping_path_is_in_contract(
                mapping_path,
                schema_roots,
                schema_paths,
            ):
                raise RuntimeError(
                    "Resposta da LLM tentou criar candidato com mapeamento para "
                    f"campo fora do schema_saida do contrato: {mapping_path}."
                )
            if not self._mapping_path_has_required_array_selectors(
                mapping_path,
                array_paths,
                mapping_entry=candidate_model.mapeamento_canonico[mapping_path].model_dump(
                    mode="json", exclude_none=True
                ),
            ):
                raise RuntimeError(
                    "Resposta da LLM criou mapeamento que atravessa array sem "
                    f"seletor explicito: {mapping_path}."
                )

        allowed_scope = str(fallback_problem_context.get("escopo_permitido", "")).strip()
        if allowed_scope and candidate_model.escopo_correcao != allowed_scope:
            raise RuntimeError(
                "Resposta da LLM tentou usar escopo diferente do permitido pela "
                f"classificacao deterministica: {candidate_model.escopo_correcao}."
            )

        self._validate_candidate_lineage(candidate_model, fallback_problem_context)
        self._validate_candidate_allowed_scope(candidate_model, fallback_problem_context)
        self._validate_candidate_covers_mapping_requirements(
            candidate_model,
            fallback_problem_context,
        )
        self._validate_table_mappings_use_indices_only(
            candidate_model,
            schema_paths=schema_paths,
        )
        self._validate_candidate_does_not_override_deterministic_headers(candidate_model)
        self._validate_candidate_extra_sections(candidate_model)
        self._validate_candidate_does_not_write_final_values(candidate_model)
        self._validate_partial_candidate_does_not_remove_unrelated_mappings(
            candidate_model,
            fallback_problem_context,
        )
        return candidate_model

    def validate_layout_fragment(
        self,
        fragment: dict[str, Any],
        *,
        unit: MappingUnit,
        fallback_problem_context: dict[str, Any],
    ) -> LayoutSignatureFragment:
        """Valida um fragmento usando as mesmas regras da DAG 2 em escopo reduzido."""
        try:
            fragment_model = LayoutSignatureFragment.model_validate(fragment)
        except ValidationError as exc:
            raise RuntimeError(
                "Resposta da LLM nao respeita o contrato Pydantic do fragmento de layout: "
                f"{exc}"
            ) from exc
        if fragment_model.unidade_mapeamento != unit.id:
            raise RuntimeError(
                "Fragmento retornou unidade_mapeamento diferente da unidade solicitada: "
                f"{fragment_model.unidade_mapeamento}."
            )

        allowed_prefixes = unit.mapping_paths
        # Um path pode falhar por dois motivos opostos, e a LLM precisa saber qual:
        # ou parou antes do campo terminal (esta dentro da unidade, so incompleto),
        # ou aponta para outra unidade. Reportar os dois como "fora da unidade"
        # manda o laco de reparo procurar o erro onde ele nao esta.
        incomplete_paths: list[str] = []
        foreign_paths: list[str] = []
        for mapping_path in fragment_model.mapeamento_canonico:
            normalized = normalize_schema_path(mapping_path)
            if any(
                normalized == required_path or normalized.startswith(f"{required_path}.")
                for required_path in allowed_prefixes
            ):
                continue
            if any(
                required_path.startswith(f"{normalized}.")
                for required_path in allowed_prefixes
            ):
                incomplete_paths.append(mapping_path)
            else:
                foreign_paths.append(mapping_path)
        if incomplete_paths:
            raise RuntimeError(
                "Fragmento parou antes do campo terminal: "
                f"{incomplete_paths}. Cada entrada de mapeamento_canonico precisa "
                "terminar em um campo mapeavel da unidade "
                f"{unit.id}, e nao no array que o contem. Complete com um de: "
                f"{sorted(allowed_prefixes)}."
            )
        if foreign_paths:
            raise RuntimeError(
                "Fragmento tentou mapear campo fora da unidade semantica "
                f"{unit.id}: {foreign_paths}."
            )

        contract_context = fallback_problem_context.get("contrato_semantico_relevante", {})
        if not isinstance(contract_context, dict):
            raise RuntimeError("Contexto do contrato ausente para validar fragmento.")
        scoped_contract = MappingPlanService.scoped_contract_context(contract_context, unit)
        scoped_context = {
            **fallback_problem_context,
            "contrato_semantico_relevante": scoped_contract,
        }
        fallback_context = scoped_context.get("fallback_context", {})
        if not isinstance(fallback_context, dict):
            raise RuntimeError("fallback_context ausente para validar fragmento.")
        scope = str(scoped_context.get("escopo_permitido", "")).strip()
        candidate_projection = {
            "tipo_artefato": "layout_signature_candidato",
            "status_layout": "candidato",
            "escopo_correcao": scope,
            "document_id": fallback_context.get("document_id"),
            "execution_id_origem": fallback_context.get("execution_id"),
            "base_layout_signature": (
                None
                if scope == self.CREATION_SCOPE
                else scoped_context.get("layout_signature_base_ref")
            ),
            "fontes_relevantes": fragment_model.fontes_relevantes,
            "regras_deteccao_mudanca": [],
            "campos_nao_mapeados": fragment_model.campos_nao_mapeados,
            "mapeamento_canonico": fragment_model.mapeamento_canonico,
            "metadados_estruturais_evidencia": (
                fragment_model.metadados_estruturais_evidencia
            ),
        }
        self.validate_candidate_layout(candidate_projection, scoped_context)
        return fragment_model

    @staticmethod
    def _validate_candidate_covers_mapping_requirements(
        candidate: LayoutSignatureCandidate,
        fallback_problem_context: dict[str, Any],
    ) -> None:
        """Exige todos os campos e observacoes declarados pelo contrato."""
        contract = fallback_problem_context.get("contrato_semantico_relevante", {})
        try:
            requirements = mapping_requirements_from_context(contract)
        except MappingRequirementsError as exc:
            raise RuntimeError(str(exc)) from exc

        parsed_mappings = [
            (mapping_path, *parsed_mapping_path(mapping_path))
            for mapping_path in candidate.mapeamento_canonico
        ]
        missing: list[tuple[str, dict[str, str]]] = []
        for requirement in requirements:
            value_mappings = [
                item for item in parsed_mappings if item[1] == requirement.path
            ]
            if not value_mappings:
                if requirement.observations:
                    missing.extend(
                        (requirement.path, observation.selectors)
                        for observation in requirement.observations
                        if observation.required
                    )
                else:
                    missing.append((requirement.path, {}))
                continue

            for observation in requirement.observations:
                if not observation.required:
                    continue
                matching_values = [
                    item
                    for item in value_mappings
                    if all(
                        item[2].get(key) == value
                        for key, value in observation.selectors.items()
                    )
                ]
                if not matching_values:
                    missing.append((requirement.path, observation.selectors))
                    continue

                parent_path = requirement.path.rsplit(".", maxsplit=1)[0]
                for context_field in observation.context_fields:
                    context_path = f"{parent_path}.{context_field}"
                    if not any(
                        normalized_path == context_path
                        and all(
                            selectors.get(key) == value
                            for key, value in value_selectors.items()
                        )
                        for _mapping_path, normalized_path, selectors in parsed_mappings
                        for _value_mapping_path, _value_path, value_selectors in matching_values
                    ):
                        missing.append((context_path, observation.selectors))

        if missing:
            FallbackCandidateValidationService._raise_if_missing_fields_were_declared(
                missing=missing,
                declared=candidate.campos_nao_mapeados,
            )
            missing_descriptions = [
                (
                    path
                    if not selectors
                    else f"{path} com seletores {selectors}"
                )
                for path, selectors in missing
            ]
            raise RuntimeError(
                "Layout candidato nao cobre requisitos obrigatorios de mapeamento: "
                f"{missing_descriptions}."
            )

        if candidate.campos_nao_mapeados:
            raise RuntimeError(
                "Layout candidato declarou campos_nao_mapeados que ja possuem "
                "mapeamento obrigatorio completo."
            )

    @staticmethod
    def optional_mapping_observations_not_mapped(
        candidate: LayoutSignatureCandidate,
        fallback_problem_context: dict[str, Any],
    ) -> list[tuple[str, dict[str, str]]]:
        """Lista ausencias opcionais para auditoria, sem bloquear o candidato."""
        contract = fallback_problem_context.get("contrato_semantico_relevante", {})
        try:
            requirements = mapping_requirements_from_context(contract)
        except MappingRequirementsError as exc:
            raise RuntimeError(str(exc)) from exc

        parsed_mappings = [
            (mapping_path, *parsed_mapping_path(mapping_path))
            for mapping_path in candidate.mapeamento_canonico
        ]
        missing: list[tuple[str, dict[str, str]]] = []
        for requirement in requirements:
            value_mappings = [
                item for item in parsed_mappings if item[1] == requirement.path
            ]
            for observation in requirement.observations:
                if observation.required:
                    continue
                matching_values = [
                    item for item in value_mappings
                    if all(
                        item[2].get(key) == value
                        for key, value in observation.selectors.items()
                    )
                ]
                if not matching_values:
                    missing.append((requirement.path, observation.selectors))
                    continue

                parent_path = requirement.path.rsplit(".", maxsplit=1)[0]
                for context_field in observation.context_fields:
                    context_path = f"{parent_path}.{context_field}"
                    if not any(
                        normalized_path == context_path
                        and all(
                            selectors.get(key) == value
                            for key, value in value_selectors.items()
                        )
                        for _mapping_path, normalized_path, selectors in parsed_mappings
                        for _value_mapping_path, _value_path, value_selectors in matching_values
                    ):
                        missing.append((context_path, observation.selectors))
        return missing

    @staticmethod
    def _raise_if_missing_fields_were_declared(
        *,
        missing: list[tuple[str, dict[str, str]]],
        declared: list[UnmappedRequiredField],
    ) -> None:
        """Aceita abstencao somente quando ela corresponde exatamente ao requisito ausente."""
        expected = {
            (normalize_schema_path(path), tuple(sorted(selectors.items())))
            for path, selectors in missing
        }
        declared_keys = {
            (
                normalize_schema_path(field.path),
                tuple(sorted(field.seletores.items())),
            )
            for field in declared
        }
        invalid = declared_keys - expected
        undeclared = expected - declared_keys
        if invalid:
            raise RuntimeError(
                "campos_nao_mapeados declarou path ou seletores que nao correspondem "
                f"a requisito pendente: {sorted(invalid)}."
            )
        if undeclared:
            return
        raise UnmappedRequiredFieldsError(declared)

    @staticmethod
    def _validate_table_mappings_use_indices_only(
        candidate: LayoutSignatureCandidate,
        *,
        schema_paths: set[str],
    ) -> None:
        """Exige selecao posicional e bloqueia regex em novos layouts de tabela."""
        table_origins = {"cabecalho_de_tabela", "celula_de_tabela"}
        for mapping_path, entry in candidate.mapeamento_canonico.items():
            payload = entry.model_dump(mode="json", exclude_none=True)
            if entry.tipo_origem == "valor_fixo" and "valor_fixo" not in payload:
                raise RuntimeError(
                    "Mapeamento valor_fixo deve declarar a chave valor_fixo: "
                    f"{mapping_path}."
                )
            if entry.tipo_origem == "linhas_de_tabela":
                fields = payload.get("campos", [])
                segments = payload.get("segmentos", payload.get("faixas_linhas", []))
                if not isinstance(segments, list):
                    segments = []
                has_positional_columns = isinstance(
                    payload.get("indices_colunas"), list
                ) or any(
                    isinstance(segment, dict)
                    and isinstance(segment.get("indices_colunas"), list)
                    for segment in segments
                )
                if not isinstance(fields, list) or (not fields and not has_positional_columns):
                    raise RuntimeError(
                        "Mapeamento linhas_de_tabela deve declarar campos nomeados "
                        "ou indices_colunas posicionais: "
                        f"{mapping_path}."
                    )
                fields_to_validate = list(fields) if isinstance(fields, list) else []
                for segment in segments:
                    if isinstance(segment, dict) and isinstance(segment.get("campos"), list):
                        fields_to_validate.extend(segment["campos"])
                for field in fields_to_validate:
                    if not isinstance(field, dict):
                        raise RuntimeError(
                            "Cada campo de linhas_de_tabela deve ser objeto: "
                            f"{mapping_path}."
                        )
                    allowed_field_keys = {"caminho_saida", "indice_coluna", "tipo"}
                    invalid_field_keys = set(field) - allowed_field_keys
                    if invalid_field_keys:
                        raise RuntimeError(
                            "Campo de linhas_de_tabela usa chaves nao suportadas "
                            f"{sorted(invalid_field_keys)} em {mapping_path}; use somente "
                            "caminho_saida, indice_coluna e tipo."
                        )
                    if not str(field.get("caminho_saida", "")).strip() or not isinstance(
                        field.get("indice_coluna"), int
                    ):
                        raise RuntimeError(
                            "Cada campo de linhas_de_tabela exige caminho_saida e "
                            f"indice_coluna inteiro: {mapping_path}."
                        )
                    if field.get("tipo") not in {None, "texto", "numero"}:
                        raise RuntimeError(
                            "tipo de campo em linhas_de_tabela deve ser texto ou numero; "
                            f"nao use derivacoes: {mapping_path}."
                        )
                    output_path = str(field.get("caminho_saida", "")).strip()
                    if output_path and f"{normalize_schema_path(mapping_path)}.{output_path}" not in schema_paths:
                        raise RuntimeError(
                            "caminho_saida de linhas_de_tabela nao pertence ao item "
                            f"de destino no schema_saida: {mapping_path}.{output_path}."
                        )
                continue
            if entry.tipo_origem not in table_origins:
                continue
            selector = payload.get("seletor_coluna")
            if not isinstance(selector, dict) or not isinstance(
                selector.get("indice_coluna_esperado"), int
            ):
                raise RuntimeError(
                    "Mapeamento de tabela deve declarar seletor_coluna.indice_coluna_esperado: "
                    f"{mapping_path}."
                )
            if "padrao_cabecalho_aceito" in selector:
                raise RuntimeError(
                    "Mapeamento de tabela nao pode usar padrao_cabecalho_aceito; "
                    "use apenas o indice de coluna observado: "
                    f"{mapping_path}."
                )
            if entry.tipo_origem != "celula_de_tabela":
                continue
            # Coluna e posicional (periodos ficam fixos dentro da tabela), mas
            # linha e semantica: o mesmo indicador aparece na linha 17 de uma
            # tabela e na linha 7 de outra do mesmo documento. O resolvedor so
            # aceita a linha pelo rotulo; o indice e apenas uma dica.
            row_selector = payload.get("seletor_linha")
            accepted_label = (
                row_selector.get("valor_aceito") if isinstance(row_selector, dict) else None
            )
            if not isinstance(accepted_label, str) or not accepted_label.strip():
                raise RuntimeError(
                    "Mapeamento celula_de_tabela deve declarar seletor_linha.valor_aceito "
                    "com o rotulo observado na linha; indice_linha_esperado sozinho nao "
                    "basta porque a posicao da linha varia entre tabelas do mesmo "
                    f"documento: {mapping_path}."
                )

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

        if candidate.escopo_correcao == FallbackCandidateValidationService.CREATION_SCOPE:
            if candidate.base_layout_signature is not None:
                raise RuntimeError(
                    "Layout candidato de criacao inicial nao deve declarar layout base."
                )
            return

        base_ref = fallback_problem_context.get("layout_signature_base_ref", {})
        if not isinstance(base_ref, dict):
            raise RuntimeError("Referencia do layout base ausente para validar candidato.")
        if candidate.base_layout_signature is None:
            raise RuntimeError("Layout candidato de remapeamento deve referenciar layout base.")
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

    @staticmethod
    def _validate_candidate_does_not_override_deterministic_headers(
        candidate: LayoutSignatureCandidate,
    ) -> None:
        """Impede que a LLM escreva cabecalhos compostos pela DAG."""
        extra_sections = set((candidate.model_extra or {}).keys())
        protected_headers = {"empresa", "entidade", "documento_origem"}
        overridden = sorted(extra_sections & protected_headers)
        if overridden:
            raise RuntimeError(
                "Layout candidato tentou alterar cabecalhos determinísticos da DAG: "
                f"{overridden}."
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
        structure = contract.get("estrutura_schema_saida", {})
        roots = (
            structure.get("campos_raiz", [])
            if isinstance(structure, dict)
            else contract.get("schema_saida_campos_raiz", [])
        )
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
        structure = contract.get("estrutura_schema_saida", {})
        paths = (
            structure.get("paths_permitidos", [])
            if isinstance(structure, dict)
            else contract.get("schema_saida_paths", [])
        )
        if not isinstance(paths, list):
            return set()
        return {str(path).strip() for path in paths if str(path).strip()}

    @staticmethod
    def _contract_schema_array_paths_from_context(
        fallback_problem_context: dict[str, Any],
    ) -> set[str]:
        """Extrai caminhos de arrays que exigem seletores no mapeamento."""
        contract = fallback_problem_context.get("contrato_semantico_relevante", {})
        if not isinstance(contract, dict):
            return set()
        structure = contract.get("estrutura_schema_saida", {})
        paths = (
            structure.get("arrays_que_exigem_seletor", [])
            if isinstance(structure, dict)
            else contract.get("schema_saida_array_paths", [])
        )
        if not isinstance(paths, list):
            return set()
        return {str(path).strip() for path in paths if str(path).strip()}

    @staticmethod
    def _mapping_path_has_required_array_selectors(
        path: str,
        array_paths: set[str],
        *,
        mapping_entry: dict[str, Any] | None = None,
    ) -> bool:
        """Exige filtro por item, exceto ao mapear a colecao inteira por linhas."""
        if not array_paths:
            return True
        cumulative: list[str] = []
        for raw_part in split_mapping_path(path):
            clean_part = raw_part.split("[", maxsplit=1)[0].strip()
            if not clean_part:
                continue
            cumulative.append(clean_part)
            current_path = ".".join(cumulative)
            if (
                current_path in array_paths
                and current_path == normalize_mapping_path(path)
                and (mapping_entry or {}).get("tipo_origem") == "linhas_de_tabela"
            ):
                continue
            if current_path in array_paths and "[" not in raw_part:
                return False
        return True

    @staticmethod
    def _mapping_path_is_in_contract(
        path: str,
        schema_roots: set[str],
        schema_paths: set[str],
    ) -> bool:
        """Confirma que o path de mapeamento aponta para path do contrato."""
        if not schema_roots:
            return False
        try:
            normalized = path.strip()
            if normalized.startswith("mapeamento_canonico."):
                normalized = normalized.removeprefix("mapeamento_canonico.")
            normalized = FallbackCandidateValidationService._normalize_mapping_path(normalized)
        except ValueError as exc:
            raise RuntimeError(
                FallbackCandidateValidationService._describe_bad_mapping_path(path)
            ) from exc
        if schema_paths and normalized not in schema_paths:
            return False
        root = normalized.split(".", maxsplit=1)[0]
        return root in schema_roots

    @staticmethod
    def _describe_bad_mapping_path(path: str) -> str:
        """Nomeia a violacao de gramatica encontrada, em vez de supor indice posicional."""
        for segment in str(path).split("."):
            filtros = re.findall(r"\[([^\]]*)\]", segment)
            if len(filtros) > 1:
                return (
                    "Caminho de mapeamento canonico invalido: o segmento "
                    f"'{segment}' acumula {len(filtros)} filtros. Use no maximo um "
                    "filtro por segmento, no formato campo[chave=valor]; para "
                    f"distinguir por mais de uma chave, filtre em segmentos diferentes: {path}."
                )
            for filtro in filtros:
                if "=" not in filtro:
                    rotulo = (
                        "indice posicional"
                        if filtro.strip().lstrip("-").isdigit()
                        else "filtro sem chave"
                    )
                    return (
                        f"Caminho de mapeamento canonico invalido: '{segment}' usa "
                        f"{rotulo} '[{filtro}]'. Em arrays use somente filtros "
                        f"semanticos no formato campo[chave=valor]: {path}."
                    )
                if "&" in filtro.partition("=")[2]:
                    return (
                        f"Caminho de mapeamento canonico invalido: o filtro '[{filtro}]' "
                        f"em '{segment}' concatena condicoes com '&'. Cada segmento aceita "
                        "um unico filtro chave=valor: escolha a chave que identifica o item "
                        f"e mapeie as demais como campos do proprio item: {path}."
                    )
        return (
            "Caminho de mapeamento canonico invalido. Use campo.campo para objetos "
            f"e campo[chave=valor] para itens de array: {path}."
        )

    @staticmethod
    def _normalize_mapping_path(path: str) -> str:
        """Remove filtros de array para comparar mapeamento com schema_saida."""
        return normalize_mapping_path(path)

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

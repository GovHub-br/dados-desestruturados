"""Componente especializado do caso de uso de fallback LLM."""

from __future__ import annotations

from ._common import *  # noqa: F401,F403


class CandidateGenerationMixin:
    def generate_candidate_layout(
        self,
        fallback_problem_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Chama a LLM e valida que a resposta e um layout candidato JSON."""
        constraints = fallback_problem_context.get("llm_constraints", {})
        if not isinstance(constraints, dict) or not constraints.get("chamar_llm"):
            raise RuntimeError("Contexto de fallback nao permite chamada LLM.")

        fallback_context = self._fallback_context_from_problem_context(
            fallback_problem_context
        )
        scope = str(fallback_problem_context.get("escopo_permitido", "")).strip()
        if scope in {self.CREATION_SCOPE, self.FULL_REMAP_SCOPE}:
            contract_context = fallback_problem_context.get("contrato_semantico_relevante", {})
            if not isinstance(contract_context, dict):
                raise RuntimeError("Contexto sem contrato semantico para gerar layout.")
            units = self.mapping_plan_service.build(contract_context)
            if self._should_generate_by_mapping_units(
                fallback_problem_context=fallback_problem_context,
                units=units,
            ):
                return self._generate_candidate_layout_by_units(
                    fallback_problem_context=fallback_problem_context,
                    fallback_context=fallback_context,
                    units=units,
                )

        return self._generate_candidate_layout_single(
            fallback_problem_context=fallback_problem_context,
            fallback_context=fallback_context,
        )


    def _generate_candidate_layout_single(
        self,
        *,
        fallback_problem_context: dict[str, Any],
        fallback_context: dict[str, str],
    ) -> dict[str, Any]:
        """Mantem o caminho unico para contratos pequenos ou correcoes parciais."""
        artifact_selection: LayoutArtifactSelection | None = None
        artifact_selection_raw: str | None = None
        llm_payloads = self._llm_payloads_from_context(fallback_problem_context)
        enriched_context = deepcopy(llm_payloads["candidate_generation"])

        if self._should_select_artifacts_with_llm(fallback_problem_context):
            (
                artifact_selection,
                artifact_selection_raw,
                loaded_artifacts,
            ) = self.select_relevant_artifacts(
                llm_payloads["artifact_selection"],
                fallback_context=fallback_context,
                manifest=fallback_problem_context.get("_manifesto_extracao_completo", {}),
            )
            self._persist_llm_validated(
                fallback_context=fallback_context,
                stage="selecao_artefatos",
                filename="selecao_artefatos_layout.json",
                payload=artifact_selection.model_dump(mode="json"),
            )
            enriched_context.update(
                {
                    "artefatos_contexto_llm": loaded_artifacts,
                }
            )
        candidate_validation_context = {
            **enriched_context,
            "fallback_context": fallback_context,
            "_paths_fixos_do_contrato": fallback_problem_context.get(
                "_paths_fixos_do_contrato", []
            ),
        }

        validation_errors: list[str] = []
        corrections_used = 0
        system_prompt: str | None = None
        user_payload = enriched_context
        messages: list[dict[str, str]] | None = self._initial_candidate_messages(
            enriched_context
        )
        attempt = 0
        parsed: dict[str, Any] | None = None
        raw_content = ""
        while True:
            try:
                parsed, raw_content = self._generate_candidate_json(
                    system_prompt=system_prompt,
                    user_payload=user_payload,
                    messages=messages,
                    fallback_context=fallback_context,
                    attempt=attempt,
                )
            except FallbackLlmClientError as exc:
                validation_error = str(exc)
                validation_errors.append(validation_error)
                if (
                    not self._is_correctable_llm_response_error(exc)
                    or corrections_used >= self.MAX_CANDIDATE_CORRECTION_ATTEMPTS
                ):
                    raise RuntimeError(
                        "Falha ao chamar LLM de fallback: "
                        f"{validation_error}"
                    ) from exc

                corrections_used += 1
                logging.warning(
                    "Resposta LLM invalida; solicitando correcao %s/%s: %s",
                    corrections_used,
                    self.MAX_CANDIDATE_CORRECTION_ATTEMPTS,
                    validation_error,
                )
                system_prompt = candidate_layout_repair_system_prompt()
                messages = None
                user_payload = self._candidate_repair_payload(
                    enriched_context=enriched_context,
                    attempt=corrections_used,
                    validation_error=validation_error,
                    invalid_candidate=exc.raw_content or "",
                )
                attempt = corrections_used
                continue

            try:
                if parsed is None:
                    raise RuntimeError("Resposta LLM ausente apos chamada.")
                candidate_model = self.candidate_validator.validate_candidate_layout(
                    parsed,
                    candidate_validation_context,
                )
                break
            except UnmappedRequiredFieldsError as exc:
                self._persist_unmapped_required_fields(
                    fallback_context=fallback_context,
                    stage="layout_signature_candidato",
                    attempt=attempt,
                    error=exc,
                )
                self._persist_llm_error(
                    fallback_context=fallback_context,
                    stage="layout_signature_candidato",
                    attempt=attempt,
                    error=exc,
                    parsed_response=parsed,
                    raw_response=raw_content,
                )
                raise RuntimeError(
                    "Layout candidato interrompido por evidencia insuficiente para "
                    "campo obrigatorio do contrato. Consulte campos_nao_mapeados "
                    "persistido no fallback."
                ) from exc
            except RuntimeError as exc:
                validation_error = str(exc)
                validation_errors.append(validation_error)
                self._persist_llm_error(
                    fallback_context=fallback_context,
                    stage="layout_signature_candidato",
                    attempt=attempt,
                    error=exc,
                    parsed_response=parsed,
                    raw_response=raw_content,
                )
                if corrections_used >= self.MAX_CANDIDATE_CORRECTION_ATTEMPTS:
                    raise RuntimeError(
                        "Layout candidato continuou invalido apos "
                        f"{self.MAX_CANDIDATE_CORRECTION_ATTEMPTS} tentativa(s) de "
                        f"correcao. Ultimo erro: {validation_error}"
                    ) from exc

                corrections_used += 1
                logging.warning(
                    "Layout candidato rejeitado; solicitando correcao %s/%s a LLM: %s",
                    corrections_used,
                    self.MAX_CANDIDATE_CORRECTION_ATTEMPTS,
                    validation_error,
                )
                system_prompt = candidate_layout_repair_system_prompt()
                messages = None
                user_payload = self._candidate_repair_payload(
                    enriched_context=enriched_context,
                    attempt=corrections_used,
                    validation_error=validation_error,
                    invalid_candidate=parsed,
                )
                attempt = corrections_used

        self._persist_unmapped_optional_observations(
            fallback_context=fallback_context,
            candidate=candidate_model,
            candidate_validation_context=candidate_validation_context,
            artifact_paths=self._artifact_paths_for_unmapped_observations(
                artifact_selection=artifact_selection,
                loaded_artifacts=enriched_context.get("artefatos_contexto_llm"),
            ),
        )
        return {
            "tipo_artefato": "resposta_llm_layout_signature_candidato",
            "artifact_selection": (
                artifact_selection.model_dump(mode="json")
                if artifact_selection is not None
                else None
            ),
            "artifact_selection_raw_response": artifact_selection_raw,
            "candidate_layout": candidate_model.model_dump(mode="json", exclude_none=True),
            "raw_response": raw_content,
            "correction_attempts_used": corrections_used,
            "validation_errors_repaired": validation_errors,
        }

"""Componente especializado do caso de uso de fallback LLM."""

from __future__ import annotations

from ._common import *  # noqa: F401,F403


class ArtifactSelectionMixin:
    def select_relevant_artifacts(
        self,
        selection_payload: dict[str, Any],
        *,
        fallback_context: dict[str, str],
        manifest: dict[str, Any],
        stage: str = "selecao_artefatos",
    ) -> tuple[LayoutArtifactSelection, str, dict[str, Any]]:
        """Seleciona e comprova artefatos, com retries guiados por validacao."""
        self.artifact_selection_validator.validate_inventory(
            selection_payload=selection_payload
        )
        response_schema = LayoutArtifactSelection.model_json_schema()
        llm_options = self._llm_options_for_stage("selecao_artefatos")
        system_prompt = artifact_selection_system_prompt()
        user_payload = selection_payload

        for attempt in range(self.MAX_ARTIFACT_SELECTION_CORRECTION_ATTEMPTS + 1):
            self._persist_llm_input(
                fallback_context=fallback_context,
                stage=stage,
                attempt=attempt,
                system_prompt=system_prompt,
                user_payload=user_payload,
                response_schema=response_schema,
                llm_options=llm_options,
            )
            try:
                parsed, raw_content = self.llm_client.generate_json(
                    system_prompt=system_prompt,
                    user_payload=user_payload,
                    response_schema=response_schema,
                    **llm_options,
                )
            except FallbackLlmClientError as exc:
                self._persist_llm_error(
                    fallback_context=fallback_context,
                    stage=stage,
                    attempt=attempt,
                    error=exc,
                )
                if attempt >= self.MAX_ARTIFACT_SELECTION_CORRECTION_ATTEMPTS:
                    raise RuntimeError(
                        f"Falha ao chamar LLM para selecao de artefatos: {exc}"
                    ) from exc
                system_prompt = artifact_selection_repair_system_prompt()
                user_payload = self._artifact_selection_repair_payload(
                    selection_payload=selection_payload,
                    attempt=attempt + 1,
                    validation_error=str(exc),
                    invalid_selection=exc.raw_content,
                )
                continue

            self._persist_llm_response(
                fallback_context=fallback_context,
                stage=stage,
                attempt=attempt,
                parsed_response=parsed,
                raw_response=raw_content,
            )
            loaded_artifacts: dict[str, Any] = {}
            try:
                artifact_selection = LayoutArtifactSelection.model_validate(parsed)
                self.artifact_selection_validator.validate_paths(
                    artifact_selection=artifact_selection,
                    selection_payload=selection_payload,
                    max_selected_artifacts=self.inventory_service.MAX_CHUNKS_PER_ARTIFACT,
                )
                selected_artifact_paths = [
                    item.path for item in artifact_selection.artifact_paths
                ]
                loaded_artifacts = self.inventory_service.load_selected_extraction_artifacts(
                    manifest=manifest,
                    artifact_paths=selected_artifact_paths,
                    get_bytes=lambda object_key: self.minio_client.get_bytes(object_key=object_key),
                )
                loaded_artifacts = self.inventory_service.enrich_selected_jsonl_anchor_evidence(
                    manifest=manifest,
                    artifact_selection=artifact_selection,
                    loaded_artifacts=loaded_artifacts,
                    get_bytes=lambda object_key: self.minio_client.get_bytes(object_key=object_key),
                )
                self.artifact_selection_validator.validate_coverage(
                    artifact_selection=artifact_selection,
                    selection_payload=selection_payload,
                    loaded_artifacts=loaded_artifacts,
                )
            except (ValidationError, ArtifactSelectionValidationError) as exc:
                self._persist_llm_error(
                    fallback_context=fallback_context,
                    stage=stage,
                    attempt=attempt,
                    error=exc,
                    parsed_response=parsed,
                    raw_response=raw_content,
                )
                if attempt >= self.MAX_ARTIFACT_SELECTION_CORRECTION_ATTEMPTS:
                    raise RuntimeError(
                        f"Selecao de artefatos sem cobertura comprovada: {exc}"
                    ) from exc
                system_prompt = artifact_selection_repair_system_prompt()
                user_payload = self._artifact_selection_repair_payload(
                    selection_payload=selection_payload,
                    attempt=attempt + 1,
                    validation_error=str(exc),
                    invalid_selection=parsed,
                    loaded_artifacts=loaded_artifacts,
                )
                continue

            return artifact_selection, raw_content, loaded_artifacts

        raise RuntimeError("Selecao de artefatos excedeu o limite de tentativas.")


    def _artifact_selection_repair_payload(
        self,
        *,
        selection_payload: dict[str, Any],
        attempt: int,
        validation_error: str,
        invalid_selection: Any,
        loaded_artifacts: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Mantem o contexto e entrega a evidencia ja carregada no retry."""
        payload = {
            **selection_payload,
            "correcao_selecao_artefatos": {
                "tentativa": attempt,
                "maximo_tentativas": self.MAX_ARTIFACT_SELECTION_CORRECTION_ATTEMPTS,
                "erro_validacao": validation_error,
                "selecao_anterior_invalida": invalid_selection,
            },
        }
        if loaded_artifacts:
            payload["artefatos_carregados_para_correcao"] = loaded_artifacts
        return payload

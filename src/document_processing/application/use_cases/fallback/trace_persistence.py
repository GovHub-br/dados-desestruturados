"""Componente especializado do caso de uso de fallback LLM."""

from __future__ import annotations

from ._common import *  # noqa: F401,F403


class FallbackTracePersistenceMixin:
    def _persist_llm_input(
        self,
        *,
        fallback_context: dict[str, str],
        stage: str,
        attempt: int,
        system_prompt: str | None,
        user_payload: dict[str, Any],
        messages: list[dict[str, str]] | None = None,
        response_schema: dict[str, Any] | None,
        llm_options: dict[str, Any] | None = None,
    ) -> None:
        """Persiste exatamente o payload enviado para a LLM."""
        config = self.config_loader.load_local_platform_config()
        payload: dict[str, Any] = {
            "tipo_artefato": f"entrada_llm_{stage}",
            "stage": stage,
            "attempt": attempt,
            "provider": config.fallback_llm_provider,
            "model": config.fallback_llm_model,
            "response_schema": response_schema,
            "opcoes_requisicao_llm": llm_options or {},
            "persistido_em": datetime.now(UTC).isoformat(),
        }
        if messages is not None:
            payload["messages"] = messages
        else:
            payload["system_prompt"] = system_prompt
            payload["user_payload"] = user_payload
        self.minio_client.put_json(
            object_key=self._fallback_object_key(
                fallback_context,
                self._llm_artifact_filename("entrada_llm", stage, attempt),
            ),
            payload=payload,
        )


    def _persist_llm_response(
        self,
        *,
        fallback_context: dict[str, str],
        stage: str,
        attempt: int,
        parsed_response: dict[str, Any],
        raw_response: str,
    ) -> None:
        """Persiste resposta bruta e resposta parseada antes da validacao final."""
        payload = {
            "tipo_artefato": f"resposta_llm_{stage}",
            "stage": stage,
            "attempt": attempt,
            "raw_response": raw_response,
            "parsed_response": parsed_response,
            "api_response_metadata": getattr(
                self.llm_client, "last_response_metadata", None
            ),
            "persistido_em": datetime.now(UTC).isoformat(),
        }
        self.minio_client.put_json(
            object_key=self._fallback_object_key(
                fallback_context,
                self._llm_artifact_filename("resposta_llm", stage, attempt),
            ),
            payload=payload,
        )


    def _persist_llm_error(
        self,
        *,
        fallback_context: dict[str, str],
        stage: str,
        attempt: int,
        error: BaseException,
        parsed_response: dict[str, Any] | None = None,
        raw_response: str | None = None,
    ) -> None:
        """Persiste erro de chamada, parse ou validacao da LLM."""
        raw_content = raw_response
        if raw_content is None and isinstance(error, FallbackLlmClientError):
            raw_content = error.raw_content
        persisted_raw_response = self._raw_response_for_persistence(raw_content)
        payload = {
            "tipo_artefato": f"erro_llm_{stage}",
            "stage": stage,
            "attempt": attempt,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "parsed_response": parsed_response,
            "api_response_metadata": (
                error.response_metadata
                if isinstance(error, FallbackLlmClientError)
                else None
            ),
            "persistido_em": datetime.now(UTC).isoformat(),
        }
        if persisted_raw_response != parsed_response:
            payload["raw_response"] = persisted_raw_response
        self.minio_client.put_json(
            object_key=self._fallback_object_key(
                fallback_context,
                self._llm_artifact_filename("erro_llm", stage, attempt),
            ),
            payload=payload,
        )


    def _persist_unmapped_required_fields(
        self,
        *,
        fallback_context: dict[str, str],
        stage: str,
        attempt: int,
        error: UnmappedRequiredFieldsError,
    ) -> None:
        """Registra ausencia comprovada sem transformar o candidato em layout publicavel."""
        payload = {
            "tipo_artefato": "campos_nao_mapeados_layout",
            "stage": stage,
            "attempt": attempt,
            "status": "evidencia_insuficiente_para_requisito_obrigatorio",
            "campos_nao_mapeados": [
                field.model_dump(mode="json") for field in error.fields
            ],
            "persistido_em": datetime.now(UTC).isoformat(),
        }
        self.minio_client.put_json(
            object_key=self._fallback_object_key(
                fallback_context,
                self._llm_artifact_filename("campos_nao_mapeados", stage, attempt),
            ),
            payload=payload,
        )


    def _persist_unmapped_optional_observations(
        self,
        *,
        fallback_context: dict[str, str],
        candidate: LayoutSignatureCandidate,
        candidate_validation_context: dict[str, Any],
        artifact_paths: list[str],
    ) -> None:
        """Audita observacoes opcionais ausentes sem afetar a publicacao."""
        collect_missing = getattr(
            self.candidate_validator,
            "optional_mapping_observations_not_mapped",
            None,
        )
        if not callable(collect_missing):
            return
        missing = collect_missing(candidate, candidate_validation_context)
        if not missing:
            return
        verified_artifacts = list(dict.fromkeys(path for path in artifact_paths if path))
        if not verified_artifacts:
            logging.warning(
                "Observacoes opcionais ausentes nao foram persistidas: nenhum artefato "
                "verificado foi informado."
            )
            return
        payload = {
            "tipo_artefato": "campos_nao_mapeados_layout",
            "stage": "layout_signature_candidato",
            "attempt": 0,
            "status": "observacoes_opcionais_nao_comprovadas",
            "bloqueia_publicacao": False,
            "campos_nao_mapeados": [
                {
                    "path": path,
                    "seletores": selectors,
                    "motivo": (
                        "Observacao declarada em campos_obrigatorios com "
                        "obrigatorio=false nao foi comprovada pelos artefatos selecionados."
                    ),
                    "artefatos_verificados": verified_artifacts,
                    "obrigatorio": False,
                }
                for path, selectors in missing
            ],
            "persistido_em": datetime.now(UTC).isoformat(),
        }
        self.minio_client.put_json(
            object_key=self._fallback_object_key(
                fallback_context,
                self._llm_artifact_filename(
                    "campos_nao_mapeados", "layout_signature_candidato", 0
                ),
            ),
            payload=payload,
        )


    @staticmethod
    def _artifact_paths_for_unmapped_observations(
        *,
        artifact_selection: LayoutArtifactSelection | None,
        loaded_artifacts: Any,
    ) -> list[str]:
        """Preserva os artefatos efetivamente usados na auditoria de ausencia."""
        if artifact_selection is not None:
            return [item.path for item in artifact_selection.artifact_paths]
        if isinstance(loaded_artifacts, dict):
            return [str(path) for path in loaded_artifacts if str(path).strip()]
        return []


    @staticmethod
    def _raw_response_for_persistence(raw_response: str | None) -> Any:
        """Converte resposta JSON valida em objeto para facilitar a leitura no MinIO."""
        if not isinstance(raw_response, str):
            return raw_response
        try:
            return json.loads(raw_response)
        except json.JSONDecodeError:
            # Em respostas truncadas ou invalidas, preservar exatamente o texto recebido.
            return raw_response


    def _persist_llm_validated(
        self,
        *,
        fallback_context: dict[str, str],
        stage: str,
        filename: str,
        payload: dict[str, Any],
    ) -> None:
        """Persiste a saida validada de uma etapa LLM."""
        validated_payload = deepcopy(payload)
        validated_payload.setdefault("tipo_artefato", stage)
        validated_payload["validado_em"] = datetime.now(UTC).isoformat()
        self.minio_client.put_json(
            object_key=self._fallback_object_key(fallback_context, filename),
            payload=validated_payload,
        )


    @staticmethod
    def _llm_artifact_filename(prefix: str, stage: str, attempt: int) -> str:
        """Nomeia tentativas sem sobrescrever evidencias anteriores."""
        directory, separator, stage_name = stage.rpartition("/")
        base = f"{prefix}_{stage_name if separator else stage}"
        if attempt > 0:
            base = f"{base}_tentativa_{attempt}"
        filename = f"{base}.json"
        return f"{directory}/{filename}" if separator else filename

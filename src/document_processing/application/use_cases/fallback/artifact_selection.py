"""Componente especializado do caso de uso de fallback LLM."""

from __future__ import annotations

from . import prompt_sets
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
        selection_payload = self._with_evidence_prefilter(
            selection_payload,
            fallback_context=fallback_context,
            manifest=manifest,
            stage=stage,
        )
        response_schema = LayoutArtifactSelection.model_json_schema()
        llm_options = self._llm_options_for_stage("selecao_artefatos")
        system_prompt = self._prompt_selecao("selecao-artefatos-system")
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
                system_prompt = self._prompt_selecao("selecao-artefatos-repair")
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
                system_prompt = self._prompt_selecao("selecao-artefatos-repair")
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


    def _with_evidence_prefilter(
        self,
        selection_payload: dict[str, Any],
        *,
        fallback_context: dict[str, str],
        manifest: dict[str, Any],
        stage: str,
    ) -> dict[str, Any]:
        """Fase 0: restringe a escolha da LLM aos artefatos que o contrato sustenta.

        O pre-filtro e deterministico: sinonimos do contrato contra o resumo do
        inventario e, quando o resumo nao decide, contra o artefato inteiro lido
        do MinIO (uma leitura por artefato). Fica gravado como
        ``prefiltro_evidencia.json`` para auditoria e metricas.
        """
        inventory = selection_payload.get("inventario_extracao", {})
        summary = inventory.get("resumo", {}) if isinstance(inventory, dict) else {}
        items = summary.get("items", []) if isinstance(summary, dict) else []
        items = items if isinstance(items, list) else []
        result = run_prefilter(
            items,
            selection_payload.get("contrato_semantico_relevante", {}),
            load_artifact_text=self._artifact_text_loader(manifest=manifest, items=items),
        )
        candidates = prefilter_payload(result.candidates)
        prefix = stage.rsplit("/", 1)[0] + "/" if "/" in stage else ""
        self._persist_llm_validated(
            fallback_context=fallback_context,
            stage=stage,
            filename=f"{prefix}prefiltro_evidencia.json",
            payload={
                "tipo_artefato": "prefiltro_evidencia",
                "unidade_mapeamento": (
                    dict(selection_payload.get("unidade_mapeamento") or {}).get("id")
                ),
                "total_artefatos_inventario": len(items),
                "candidatos_por_requisito": candidates,
                "leitura_completa": {
                    "artefatos_lidos": list(result.artefatos_lidos),
                    "excluidos_apos_leitura": list(result.excluidos_apos_leitura),
                    "sem_leitura": list(result.sem_leitura),
                },
            },
        )
        return {
            **selection_payload,
            "candidatos_por_requisito": candidates,
            "politica_candidatos": (
                "Para cada campo_saida, escolha somente entre os paths listados em "
                "candidatos_por_requisito; quando a lista de um campo estiver vazia, "
                "qualquer artefato do inventario e permitido para ele. Cada candidato "
                "traz os termos do contrato encontrados nele (fonte 'resumo' ou "
                "'artefato_completo'). Um candidato com motivo 'amostra_incompleta' "
                "nao pode ser lido por inteiro e so deve ser escolhido se o titulo ou o "
                "contexto indicarem que ele contem o indicador."
            ),
        }


    def _artifact_text_loader(
        self,
        *,
        manifest: dict[str, Any],
        items: list[Any],
    ):
        """Leitor do artefato inteiro para o pre-filtro: path do inventario -> texto.

        Resolve o object key pelo manifesto e le o JSON do MinIO; qualquer falha
        devolve None e o dominio trata o artefato como nao lido.
        """
        artifact_uris = [str(uri) for uri in manifest.get("artifact_uris", []) or []]
        by_path = {
            str(item.get("path", "")).strip("/"): item
            for item in items
            if isinstance(item, dict)
        }

        def load(path: str) -> str | None:
            object_key = self.inventory_service.find_artifact_object_key(
                artifact_uris=artifact_uris,
                origin_file=path,
            )
            if not object_key or not object_key.endswith(".json"):
                return None
            try:
                parsed = json.loads(self.minio_client.get_bytes(object_key=object_key))
            except Exception as exc:
                logging.warning("Pre-filtro: nao foi possivel ler %s (%s).", object_key, exc)
                return None
            return artifact_full_text(parsed, item=by_path.get(path))

        return load


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


    def _prompt_selecao(self, sufixo: str) -> str:
        """Resolve um bloco da etapa de selecao e registra a versao usada."""
        conjunto = (
            prompt_sets.CONJUNTO_SELECAO_REPARO
            if sufixo.endswith("repair")
            else prompt_sets.CONJUNTO_SELECAO
        )
        resolvido = prompt_sets.resolver(sufixo)
        self._registrar_prompts([resolvido.como_registro()], conjunto=conjunto)
        return resolvido.texto

"""Componente especializado do caso de uso de fallback LLM."""

from __future__ import annotations

from ._common import *  # noqa: F401,F403


class MappingUnitGenerationMixin:
    def _should_generate_by_mapping_units(
        self,
        *,
        fallback_problem_context: dict[str, Any],
        units: list[MappingUnit],
    ) -> bool:
        """Ativa a geracao por blocos apenas quando ela reduz um layout amplo."""
        scope = str(fallback_problem_context.get("escopo_permitido", "")).strip()
        return (
            len(units) > 1
            and scope in {self.CREATION_SCOPE, self.FULL_REMAP_SCOPE}
            and self._should_select_artifacts_with_llm(fallback_problem_context)
        )


    def _generate_candidate_layout_by_units(
        self,
        *,
        fallback_problem_context: dict[str, Any],
        fallback_context: dict[str, str],
        units: list[MappingUnit],
    ) -> dict[str, Any]:
        """Gera, valida e consolida fragmentos independentes do layout.

        A divisao e totalmente deterministica: o contrato define os campos
        obrigatorios e este servico os agrupa pela raiz semantica. A LLM nunca
        escolhe a quantidade de blocos nem quais campos pertencem a eles.
        """
        llm_payloads = self._llm_payloads_from_context(fallback_problem_context)
        manifest = fallback_problem_context.get("_manifesto_extracao_completo", {})
        if not isinstance(manifest, dict):
            raise RuntimeError("Contexto sem manifesto de extracao para gerar layout por blocos.")

        plan_payload = {
            "tipo_artefato": "plano_mapeamento_layout",
            "versao": "1.0",
            "estrategia": "agrupamento_deterministico_por_raiz_semantica",
            "unidades": [unit.payload() for unit in units],
            "status": "em_execucao",
            "gerado_em": datetime.now(UTC).isoformat(),
        }
        self.minio_client.put_json(
            object_key=self._fallback_object_key(fallback_context, "plano_mapeamento.json"),
            payload=plan_payload,
        )
        logging.info(
            "Plano deterministico de layout criado com %s unidade(s): %s",
            len(units),
            [
                {
                    "id": unit.id,
                    "campos_saida": list(unit.paths),
                }
                for unit in units
            ],
        )

        generated_units: list[dict[str, Any]] = []
        validation_errors: list[str] = []
        corrections_used = 0
        for position, unit in enumerate(units, start=1):
            unit_stage_prefix = f"unidades/{unit.id}"
            logging.info(
                "Unidade %s/%s (%s): iniciando selecao de artefatos para %s",
                position,
                len(units),
                unit.id,
                list(unit.paths),
            )
            selection_payload = self._selection_payload_for_unit(
                llm_payloads["artifact_selection"],
                unit,
            )
            artifact_selection, selection_raw, loaded_artifacts = self.select_relevant_artifacts(
                selection_payload,
                fallback_context=fallback_context,
                manifest=manifest,
                stage=f"{unit_stage_prefix}/selecao_artefatos",
            )
            logging.info(
                "Unidade %s/%s (%s): selecao aprovada com %s artefato(s): %s",
                position,
                len(units),
                unit.id,
                len(artifact_selection.artifact_paths),
                [item.path for item in artifact_selection.artifact_paths],
            )
            self._persist_llm_validated(
                fallback_context=fallback_context,
                stage=f"{unit_stage_prefix}/selecao_artefatos",
                filename=f"{unit_stage_prefix}/selecao_artefatos_layout.json",
                payload=artifact_selection.model_dump(mode="json"),
            )

            fragment_payload = self._fragment_payload_for_unit(
                candidate_payload=llm_payloads["candidate_generation"],
                unit=unit,
                loaded_artifacts=loaded_artifacts,
            )
            logging.info(
                "Unidade %s/%s (%s): iniciando geracao do fragmento de layout",
                position,
                len(units),
                unit.id,
            )
            fragment, raw_response, unit_corrections, unit_errors = self._generate_layout_fragment(
                fallback_problem_context=fallback_problem_context,
                fallback_context=fallback_context,
                unit=unit,
                fragment_payload=fragment_payload,
                stage=f"{unit_stage_prefix}/fragmento_layout_signature",
            )
            logging.info(
                "Unidade %s/%s (%s): fragmento validado com %s mapeamento(s) e %s correcao(oes)",
                position,
                len(units),
                unit.id,
                len(fragment.mapeamento_canonico),
                unit_corrections,
            )
            self._persist_llm_validated(
                fallback_context=fallback_context,
                stage=f"{unit_stage_prefix}/fragmento_layout_signature",
                filename=f"{unit_stage_prefix}/fragmento_layout_signature.json",
                payload=fragment.model_dump(mode="json", exclude_none=True),
            )
            generated_units.append(
                {
                    "unit": unit,
                    "artifact_selection": artifact_selection,
                    "artifact_selection_raw_response": selection_raw,
                    "loaded_artifacts": loaded_artifacts,
                    "fragment": fragment,
                    "raw_response": raw_response,
                    "correction_attempts_used": unit_corrections,
                    "validation_errors_repaired": unit_errors,
                }
            )
            corrections_used += unit_corrections
            validation_errors.extend(unit_errors)

        candidate = self._merge_layout_fragments(
            fallback_problem_context=fallback_problem_context,
            fallback_context=fallback_context,
            generated_units=generated_units,
        )
        logging.info(
            "Fragmentos consolidados: %s unidade(s), %s mapeamento(s) no layout candidato.",
            len(generated_units),
            len(candidate.get("mapeamento_canonico", {})),
        )
        self._persist_unmapped_optional_observations(
            fallback_context=fallback_context,
            candidate=LayoutSignatureCandidate.model_validate(candidate),
            candidate_validation_context=fallback_problem_context,
            artifact_paths=[
                artifact.path
                for item in generated_units
                for artifact in item["artifact_selection"].artifact_paths
            ],
        )
        self._persist_llm_validated(
            fallback_context=fallback_context,
            stage="layout_signature_candidato_consolidado",
            filename="layout_signature_candidato_consolidado.json",
            payload=candidate,
        )
        plan_payload["status"] = "concluido"
        plan_payload["concluido_em"] = datetime.now(UTC).isoformat()
        self.minio_client.put_json(
            object_key=self._fallback_object_key(fallback_context, "plano_mapeamento.json"),
            payload=plan_payload,
        )
        return {
            "tipo_artefato": "resposta_llm_layout_signature_candidato",
            "modo_geracao": "por_blocos_deterministicos",
            "mapping_plan": plan_payload,
            "artifact_selection": None,
            "artifact_selection_raw_response": None,
            "unidades_mapeamento": [
                {
                    "id": item["unit"].id,
                    "raiz_semantica": item["unit"].root_path,
                    "artifact_selection": item["artifact_selection"].model_dump(mode="json"),
                    "fragmento": item["fragment"].model_dump(mode="json", exclude_none=True),
                    "correction_attempts_used": item["correction_attempts_used"],
                }
                for item in generated_units
            ],
            "candidate_layout": candidate,
            "raw_response": None,
            "correction_attempts_used": corrections_used,
            "validation_errors_repaired": validation_errors,
        }


    def _selection_payload_for_unit(
        self,
        selection_payload: dict[str, Any],
        unit: MappingUnit,
    ) -> dict[str, Any]:
        """Projeta somente o contrato necessario para selecionar um bloco."""
        payload = deepcopy(selection_payload)
        contract_context = payload.get("contrato_semantico_relevante", {})
        if not isinstance(contract_context, dict):
            raise RuntimeError("Payload de selecao sem contrato semantico relevante.")
        payload["contrato_semantico_relevante"] = (
            self.mapping_plan_service.scoped_contract_context(contract_context, unit)
        )
        payload["unidade_mapeamento"] = unit.payload()
        return payload


    def _fragment_payload_for_unit(
        self,
        *,
        candidate_payload: dict[str, Any],
        unit: MappingUnit,
        loaded_artifacts: dict[str, Any],
    ) -> dict[str, Any]:
        """Entrega ao modelo apenas contrato, alvos e evidencia de uma unidade."""
        contract_context = candidate_payload.get("contrato_semantico_relevante", {})
        if not isinstance(contract_context, dict):
            raise RuntimeError("Payload de candidato sem contrato semantico relevante.")
        targets = candidate_payload.get("alvos_mapeaveis", [])
        if not isinstance(targets, list):
            targets = []
        unit_paths = set(unit.paths)
        return {
            "tipo_payload": "geracao_fragmento_layout_signature",
            "contexto_execucao": candidate_payload.get("contexto_execucao", {}),
            "unidade_mapeamento": unit.payload(),
            "contrato_semantico_relevante": self.mapping_plan_service.scoped_contract_context(
                contract_context,
                unit,
            ),
            "alvos_mapeaveis": [
                target
                for target in targets
                if isinstance(target, dict)
                and str(target.get("campo_saida", "")).strip() in unit_paths
            ],
            "exemplo_estrutura_mapeamento_unidade": unit_mapping_structure_example(
                unit_id=unit.id
            ),
            "artefatos_contexto_llm": loaded_artifacts,
        }

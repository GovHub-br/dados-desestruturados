"""Componente especializado do caso de uso de fallback LLM."""

from __future__ import annotations

from . import prompt_sets
from ._common import *  # noqa: F401,F403


class FragmentGenerationMixin:
    def _generate_layout_fragment(
        self,
        *,
        fallback_problem_context: dict[str, Any],
        fallback_context: dict[str, str],
        unit: MappingUnit,
        fragment_payload: dict[str, Any],
        stage: str,
    ) -> tuple[LayoutSignatureFragment, str, int, list[str]]:
        """Chama a LLM para um fragmento, com retry limitado e auditavel."""
        response_schema = LayoutSignatureFragment.model_json_schema()
        llm_options = self._llm_options_for_stage("fragmento_layout_signature")
        messages = self._fragment_messages(fragment_payload=fragment_payload)
        errors: list[str] = []
        corrections_used = 0
        attempt = 0
        raw_content = ""
        while True:
            self._persist_llm_input(
                fallback_context=fallback_context,
                stage=stage,
                attempt=attempt,
                system_prompt=None,
                user_payload={},
                messages=messages,
                response_schema=response_schema,
                llm_options=llm_options,
            )
            try:
                parsed, raw_content = self.llm_client.generate_json(
                    messages=messages,
                    response_schema=response_schema,
                    **llm_options,
                )
                self._persist_llm_response(
                    fallback_context=fallback_context,
                    stage=stage,
                    attempt=attempt,
                    parsed_response=parsed,
                    raw_response=raw_content,
                )
            except FallbackLlmClientError as exc:
                errors.append(str(exc))
                self._persist_llm_error(
                    fallback_context=fallback_context,
                    stage=stage,
                    attempt=attempt,
                    error=exc,
                )
                if self._is_length_exhausted_without_content(exc):
                    raise RuntimeError(
                        "LLM esgotou a janela de conclusao sem emitir JSON para a unidade "
                        f"{unit.id}. Reduza o bloco ou aumente o limite de saida."
                    ) from exc
                if (
                    not self._is_correctable_llm_response_error(exc)
                    or corrections_used >= self.MAX_CANDIDATE_CORRECTION_ATTEMPTS
                ):
                    raise RuntimeError(
                        f"Falha ao gerar fragmento da unidade {unit.id}: {exc}"
                    ) from exc
                corrections_used += 1
                repair_payload = self._fragment_repair_payload(
                    fragment_payload=fragment_payload,
                    attempt=corrections_used,
                    validation_error=str(exc),
                    invalid_fragment=exc.raw_content,
                )
                messages = self._fragment_messages(
                    fragment_payload=fragment_payload,
                    repair_payload=repair_payload,
                )
                attempt = corrections_used
                continue

            try:
                fragment = self.candidate_validator.validate_layout_fragment(
                    parsed,
                    unit=unit,
                    fallback_problem_context=fallback_problem_context,
                )
                return fragment, raw_content, corrections_used, errors
            except UnmappedRequiredFieldsError as exc:
                self._persist_unmapped_required_fields(
                    fallback_context=fallback_context,
                    stage=stage,
                    attempt=attempt,
                    error=exc,
                )
                self._persist_llm_error(
                    fallback_context=fallback_context,
                    stage=stage,
                    attempt=attempt,
                    error=exc,
                    parsed_response=parsed,
                    raw_response=raw_content,
                )
                raise RuntimeError(
                    "Geracao de layout interrompida por evidencia insuficiente para "
                    f"campo obrigatorio da unidade {unit.id}. Consulte "
                    "campos_nao_mapeados persistido no fallback."
                ) from exc
            except RuntimeError as exc:
                errors.append(str(exc))
                self._persist_llm_error(
                    fallback_context=fallback_context,
                    stage=stage,
                    attempt=attempt,
                    error=exc,
                    parsed_response=parsed,
                    raw_response=raw_content,
                )
                if corrections_used >= self.MAX_CANDIDATE_CORRECTION_ATTEMPTS:
                    raise RuntimeError(
                        f"Fragmento da unidade {unit.id} continuou invalido apos "
                        f"{self.MAX_CANDIDATE_CORRECTION_ATTEMPTS} tentativa(s). "
                        f"Ultimo erro: {exc}"
                    ) from exc
                corrections_used += 1
                repair_payload = self._fragment_repair_payload(
                    fragment_payload=fragment_payload,
                    attempt=corrections_used,
                    validation_error=str(exc),
                    invalid_fragment=parsed,
                )
                messages = self._fragment_messages(
                    fragment_payload=fragment_payload,
                    repair_payload=repair_payload,
                )
                attempt = corrections_used


    def _merge_layout_fragments(
        self,
        *,
        fallback_problem_context: dict[str, Any],
        fallback_context: dict[str, str],
        generated_units: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Consolida fragmentos sem inferencia: colisao de path e sempre erro."""
        mappings: dict[str, Any] = {}
        sources: dict[str, Any] = {}
        evidence: dict[str, Any] = {"unidades_mapeamento": {}}
        for item in generated_units:
            unit = item["unit"]
            fragment: LayoutSignatureFragment = item["fragment"]
            duplicate_paths = set(mappings).intersection(fragment.mapeamento_canonico)
            if duplicate_paths:
                raise RuntimeError(
                    "Fragmentos de layout possuem mapeamentos conflitantes: "
                    f"{sorted(duplicate_paths)}."
                )
            mappings.update(
                {
                    path: entry.model_dump(mode="json", exclude_none=True)
                    for path, entry in fragment.mapeamento_canonico.items()
                }
            )
            sources[unit.id] = fragment.fontes_relevantes
            evidence["unidades_mapeamento"][unit.id] = (
                fragment.metadados_estruturais_evidencia
            )

        scope = str(fallback_problem_context.get("escopo_permitido", "")).strip()
        candidate = {
            "tipo_artefato": "layout_signature_candidato",
            "status_layout": "candidato",
            "escopo_correcao": scope,
            "document_id": fallback_context["document_id"],
            "execution_id_origem": fallback_context["execution_id"],
            "base_layout_signature": (
                None
                if scope == self.CREATION_SCOPE
                else fallback_problem_context.get("layout_signature_base_ref")
            ),
            "fontes_relevantes": sources,
            "regras_deteccao_mudanca": [],
            "mapeamento_canonico": mappings,
            "metadados_estruturais_evidencia": evidence,
        }
        candidate_model = self.candidate_validator.validate_candidate_layout(
            candidate,
            fallback_problem_context,
        )
        return candidate_model.model_dump(mode="json", exclude_none=True)


    def _fragment_repair_payload(
        self,
        *,
        fragment_payload: dict[str, Any],
        attempt: int,
        validation_error: str,
        invalid_fragment: Any,
    ) -> dict[str, Any]:
        """Mantem o erro localizado, sem repetir candidato grande no retry."""
        return {
            "correcao_mapeamento": {
                "tentativa": attempt,
                "maximo_tentativas": self.MAX_CANDIDATE_CORRECTION_ATTEMPTS,
                "erro_validacao": validation_error,
                "trecho_resposta_invalida": self._compact_fragment_for_repair(
                    invalid_fragment,
                    validation_error,
                ),
            },
        }


    @staticmethod
    def _compact_fragment_for_repair(
        invalid_fragment: Any,
        validation_error: str,
    ) -> Any:
        """Retem apenas entradas relacionadas ao erro para evitar inflar retries."""
        if not isinstance(invalid_fragment, dict):
            return invalid_fragment
        mappings = invalid_fragment.get("mapeamento_canonico")
        if not isinstance(mappings, dict):
            return invalid_fragment
        matching = {
            path: value
            for path, value in mappings.items()
            if str(path) in validation_error
        }
        if not matching:
            matching = dict(list(mappings.items())[:3])
        return {
            "tipo_artefato": invalid_fragment.get("tipo_artefato"),
            "unidade_mapeamento": invalid_fragment.get("unidade_mapeamento"),
            "mapeamento_canonico": matching,
        }


    def _fragment_messages(
        self,
        *,
        fragment_payload: dict[str, Any],
        repair_payload: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        """Alterna instrucoes completas e dados reduzidos de uma unidade de mapeamento.

        A sequencia com reparo e um conjunto proprio: ela insere o bloco de
        correcao antes da recapitulacao final, e nao apenas troca o system.
        """
        execution_context = fragment_payload.get("contexto_execucao", {})
        if not isinstance(execution_context, dict):
            execution_context = {}
        scope = str(execution_context.get("escopo_correcao", "")).strip()

        def json_block(name: str) -> str:
            return json.dumps(
                {name: fragment_payload.get(name, {})},
                ensure_ascii=False,
                indent=2,
            )

        texto_escopo, blocos_escopo = prompt_sets.escopo_unidade(scope)
        variaveis = {
            "instrucao_escopo": texto_escopo,
            "contexto_execucao": json_block("contexto_execucao"),
            "unidade_e_contrato": json.dumps(
                {
                    "unidade_mapeamento": fragment_payload.get("unidade_mapeamento", {}),
                    "contrato_semantico_relevante": fragment_payload.get(
                        "contrato_semantico_relevante", {}
                    ),
                    "alvos_mapeaveis": fragment_payload.get("alvos_mapeaveis", []),
                },
                ensure_ascii=False,
                indent=2,
            ),
            "exemplo_estrutura": json_block("exemplo_estrutura_mapeamento_unidade"),
            "artefatos_contexto_llm": json_block("artefatos_contexto_llm"),
        }
        conjunto = prompt_sets.CONJUNTO_UNIDADE
        if repair_payload is not None:
            conjunto = prompt_sets.CONJUNTO_UNIDADE_REPARO
            variaveis["payload_correcao"] = json.dumps(
                repair_payload, ensure_ascii=False, indent=2
            )

        mensagens, utilizados = prompt_sets.montar(
            conjunto,
            resolvidos={
                bloco.nome: bloco for bloco in blocos_escopo
            },
            variaveis=variaveis,
        )
        self._registrar_prompts(utilizados, conjunto=conjunto)
        return mensagens

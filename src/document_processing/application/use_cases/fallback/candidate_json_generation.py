"""Componente especializado do caso de uso de fallback LLM."""

from __future__ import annotations

from . import prompt_sets
from ._common import *  # noqa: F401,F403


class CandidateJsonGenerationMixin:
    def _generate_candidate_json(
        self,
        *,
        system_prompt: str | None,
        user_payload: dict[str, Any],
        messages: list[dict[str, str]] | None,
        fallback_context: dict[str, str],
        attempt: int,
    ) -> tuple[dict[str, Any], str]:
        """Executa uma chamada de candidato com schema e erro padronizado."""
        response_schema = LayoutSignatureCandidate.model_json_schema()
        self._persist_llm_input(
            fallback_context=fallback_context,
            stage="layout_signature_candidato",
            attempt=attempt,
            system_prompt=system_prompt,
            user_payload=user_payload,
            messages=messages,
            response_schema=response_schema,
        )
        try:
            if messages is not None:
                parsed, raw_content = self.llm_client.generate_json(
                    messages=messages,
                    response_schema=response_schema,
                )
            else:
                parsed, raw_content = self.llm_client.generate_json(
                    system_prompt=system_prompt,
                    user_payload=user_payload,
                    response_schema=response_schema,
                )
            self._persist_llm_response(
                fallback_context=fallback_context,
                stage="layout_signature_candidato",
                attempt=attempt,
                parsed_response=parsed,
                raw_response=raw_content,
            )
            return parsed, raw_content
        except FallbackLlmClientError as exc:
            self._persist_llm_error(
                fallback_context=fallback_context,
                stage="layout_signature_candidato",
                attempt=attempt,
                error=exc,
            )
            raise


    def _initial_candidate_messages(
        self,
        enriched_context: dict[str, Any],
    ) -> list[dict[str, str]]:
        """Alterna instrucoes didaticas e blocos variaveis da primeira geracao.

        A ordem das mensagens continua sendo decisao de codigo; o texto de cada
        instrucao vem do conjunto `layout-candidato`, resolvido bloco a bloco.
        """
        scope = str(enriched_context.get("escopo_permitido", "")).strip()

        def json_block(name: str) -> str:
            return json.dumps(
                {name: enriched_context.get(name, {})},
                ensure_ascii=False,
                indent=2,
            )

        escopo = prompt_sets.escopo_candidato(scope)
        mensagens, utilizados = prompt_sets.montar(
            prompt_sets.CONJUNTO_CANDIDATO,
            resolvidos={"instrucao_escopo": escopo},
            variaveis={
                "instrucao_escopo": escopo.texto,
                "contexto_execucao": json_block("contexto_execucao"),
                "contrato_e_alvos": json.dumps(
                    {
                        "contrato_semantico_relevante": enriched_context.get(
                            "contrato_semantico_relevante", {}
                        ),
                        "alvos_mapeaveis": enriched_context.get("alvos_mapeaveis", []),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                "exemplo_estrutura": json_block("exemplo_estrutura_layout_signature"),
                "artefatos_contexto_llm": json_block("artefatos_contexto_llm"),
            },
        )
        self._registrar_prompts(utilizados, conjunto=prompt_sets.CONJUNTO_CANDIDATO)
        return mensagens

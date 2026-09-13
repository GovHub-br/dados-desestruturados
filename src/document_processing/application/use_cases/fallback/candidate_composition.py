"""Componente especializado do caso de uso de fallback LLM."""

from __future__ import annotations

from ._common import *  # noqa: F401,F403


class CandidateCompositionMixin:
    def _candidate_repair_payload(
        self,
        *,
        enriched_context: dict[str, Any],
        attempt: int,
        validation_error: str,
        invalid_candidate: Any,
    ) -> dict[str, Any]:
        """Monta payload minimo para retry corretivo da LLM."""
        return {
            **enriched_context,
            "correcao_candidato": {
                "tentativa": attempt,
                "maximo_tentativas": self.MAX_CANDIDATE_CORRECTION_ATTEMPTS,
                "erro_validacao": validation_error,
                "candidato_invalido": invalid_candidate,
                "instrucao": (
                    "Corrija somente o erro informado e devolva o objeto JSON "
                    "completo do layout_signature_candidato, sem markdown ou "
                    "texto externo."
                ),
            },
        }


    @staticmethod
    def _is_correctable_llm_response_error(error: FallbackLlmClientError) -> bool:
        """Distingue erro de resposta corrigivel de erro tecnico/configuracao."""
        if error.raw_content is not None:
            return True
        message = str(error).lower()
        return "json" in message or "conteudo" in message


    @staticmethod
    def _is_length_exhausted_without_content(error: FallbackLlmClientError) -> bool:
        """Reconhece a chamada que esgotou a conclusao sem emitir resposta util."""
        metadata = error.response_metadata
        if not isinstance(metadata, dict):
            return False
        return (
            str(metadata.get("finish_reason", "")).strip().lower() == "length"
            and not bool(metadata.get("content_presente"))
        )


    @staticmethod
    def _is_response_without_content(error: FallbackLlmClientError) -> bool:
        """Reconhece a resposta que nao trouxe texto algum, por qualquer caminho.

        Repetir a mesma chamada nao adianta, mas repetir com outro orcamento sim:
        quando o raciocinio consome a conclusao inteira, o que falta e espaco para
        a resposta, nao capacidade do modelo.
        """
        if error.raw_content:
            return False
        if CandidateCompositionMixin._is_length_exhausted_without_content(error):
            return True
        return "conteudo textual vazio" in str(error).lower()


    @staticmethod
    def _budget_relief_options(llm_options: dict[str, Any]) -> dict[str, Any] | None:
        """Devolve opcoes que liberam a conclusao, ou None se nao ha o que liberar.

        O raciocinio divide o mesmo teto com a resposta. Desliga-lo devolve o
        orcamento inteiro ao JSON, que e o que esta etapa precisa emitir: o
        mapeamento tem gramatica fechada e nao se beneficia de deliberacao longa.
        """
        if str(llm_options.get("thinking_mode", "")).strip().lower() != "enabled":
            return None
        return {**llm_options, "thinking_mode": "disabled"}


    @staticmethod
    def _llm_payloads_from_context(
        fallback_problem_context: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        """Extrai payloads LLM ja montados por escopo e etapa."""
        payloads = fallback_problem_context.get("llm_payloads")
        if not isinstance(payloads, dict):
            raise RuntimeError("fallback_problem_context sem llm_payloads.")
        artifact_selection = payloads.get("artifact_selection")
        candidate_generation = payloads.get("candidate_generation")
        if not isinstance(artifact_selection, dict) or not isinstance(candidate_generation, dict):
            raise RuntimeError(
                "fallback_problem_context.llm_payloads deve conter "
                "artifact_selection e candidate_generation."
            )
        return {
            "artifact_selection": artifact_selection,
            "candidate_generation": candidate_generation,
        }


    @staticmethod
    def _fallback_context_from_problem_context(
        fallback_problem_context: dict[str, Any],
    ) -> dict[str, str]:
        """Extrai contexto de fallback do payload antes de filtrar o prompt."""
        fallback_context = fallback_problem_context.get("fallback_context")
        if not isinstance(fallback_context, dict):
            raise RuntimeError("fallback_problem_context sem fallback_context.")
        entity_slug = str(
            fallback_context.get("entity_slug") or fallback_context.get("company_slug") or ""
        ).strip()
        if not entity_slug:
            raise RuntimeError("fallback_context sem campo obrigatorio: entity_slug")
        required = ("document_id", "execution_id", "manifest_key")
        cleaned: dict[str, str] = {}
        cleaned["entity_slug"] = entity_slug
        for field in required:
            value = str(fallback_context.get(field, "")).strip()
            if not value:
                raise RuntimeError(f"fallback_context sem campo obrigatorio: {field}")
            cleaned[field] = value
        for optional in ("domain", "fallback_execution_id", "source_execution_id", "fallback_mode", "motivo", "entity_name", "contrato_semantico_uri"):
            value = str(fallback_context.get(optional, "")).strip()
            if value:
                cleaned[optional] = value
        return cleaned


    def _next_layout_version(self, entity_slug: str, *, domain: str) -> str:
        """Calcula a proxima versao minor do layout sem depender da LLM."""
        config = self.config_loader.load_local_platform_config()
        prefix = f"{self._prefix_for_domain(config.minio_layout_prefix, domain)}/{entity_slug}/"
        keys = self.minio_client.list_object_keys(
            prefix=prefix,
            suffix="/layout_signature_deterministico.json",
        )
        versions: list[tuple[int, int, int]] = []
        for key in keys:
            match = re.search(r"/v(\d+)\.(\d+)\.(\d+)/layout_signature_deterministico\.json$", key)
            if not match:
                continue
            versions.append(tuple(int(part) for part in match.groups()))

        if not versions:
            return "v1.0.0"
        major, minor, _patch = max(versions)
        return f"v{major}.{minor + 1}.0"


    @staticmethod
    def _build_initial_layout_skeleton(
        *,
        contract_key: str,
        contract: dict[str, Any],
        manifest_key: str,
        manifest: dict[str, Any],
        fallback_context: dict[str, str],
    ) -> dict[str, Any]:
        """Cria cabecalhos imutaveis do primeiro layout sem pedir isso a LLM."""
        manifest_candidate = manifest.get("candidate", {})
        if not isinstance(manifest_candidate, dict):
            manifest_candidate = {}

        document_origin: dict[str, Any] = {
            "document_id": fallback_context["document_id"],
            "execution_id": fallback_context["execution_id"],
            "manifest_key": manifest_key,
        }
        input_pdf_uri = str(manifest.get("input_pdf_uri", "")).strip()
        if input_pdf_uri:
            document_origin["arquivo_pdf"] = input_pdf_uri
        period_label = str(manifest_candidate.get("period_label", "")).strip()
        if period_label:
            document_origin["periodo"] = period_label

        return {
            "tipo_artefato": "layout_signature_com_mapeamento_canonico_deterministico",
            "entidade": {
                "slug": str(
                    fallback_context.get("entity_slug")
                    or fallback_context.get("company_slug")
                    or "entidade_desconhecida"
                ),
                "nome": str(
                    fallback_context.get("entity_name")
                    or manifest_candidate.get("entity_name")
                    or manifest_candidate.get("company_name")
                    or fallback_context.get("entity_slug")
                    or fallback_context.get("company_slug")
                    or "entidade_desconhecida"
                ).strip(),
            },
            "referencia_contrato_semantico": {
                "arquivo": contract_key.rstrip("/").rsplit("/", maxsplit=1)[-1],
                "versao": contract.get("versao"),
            },
            "documento_origem": document_origin,
            "regras_execucao": {
                "modo_resolucao": "deterministico",
                "extrair_valores_brutos": True,
                "calcular_variacoes_na_extracao": False,
                "gerar_resultado_validacao_em_runtime": True,
                "acionar_llm_apenas_em_fallback": True,
            },
        }


    @staticmethod
    def _compose_initial_layout_for_revalidation(
        *,
        initial_layout_skeleton: dict[str, Any],
        candidate: dict[str, Any],
        candidate_key: str,
    ) -> dict[str, Any]:
        """Combina o candidato validado com os campos iniciais de responsabilidade da DAG."""
        layout = CandidateCompositionMixin._apply_candidate_sections(
            base_layout=initial_layout_skeleton,
            candidate=candidate,
        )
        layout["lineage_fallback_candidato"] = {
            "candidate_layout_object_key": candidate_key,
            "document_id": candidate.get("document_id"),
            "execution_id_origem": candidate.get("execution_id_origem"),
        }
        return layout


    @staticmethod
    def _apply_candidate_sections(
        *,
        base_layout: dict[str, Any],
        candidate: dict[str, Any],
    ) -> dict[str, Any]:
        """Aplica somente secoes editaveis do candidato a um layout existente."""
        layout = deepcopy(base_layout)
        candidate_only_keys = {
            "tipo_artefato",
            "status_layout",
            "escopo_correcao",
            "document_id",
            "execution_id_origem",
            "base_layout_signature",
            "publicacao_automatica_habilitada",
            "entidade",
            "empresa",
            "persistido_em",
            "candidate_layout_object_key",
            "candidate_layout_uri",
            "secoes_atualizadas",
        }
        for key, value in candidate.items():
            if key not in candidate_only_keys:
                layout[key] = value
        return layout


    @staticmethod
    def _build_published_layout_from_candidate(
        *,
        base_layout: dict[str, Any],
        candidate: dict[str, Any],
        version: str,
        candidate_key: str,
        revalidation_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Aplica o candidato ao layout base e remove metadados exclusivos de candidato."""
        published = CandidateCompositionMixin._apply_candidate_sections(
            base_layout=base_layout,
            candidate=candidate,
        )

        published["versao_artefato"] = version.removeprefix("v")
        published["publicado_em"] = datetime.now(UTC).isoformat()
        published["lineage_fallback"] = {
            "candidate_layout_object_key": candidate_key,
            "base_layout_signature": candidate.get("base_layout_signature"),
            "document_id": candidate.get("document_id"),
            "execution_id_origem": candidate.get("execution_id_origem"),
            "escopo_correcao": candidate.get("escopo_correcao"),
            "validation_object_key": revalidation_result.get("validation_object_key"),
        }
        return published

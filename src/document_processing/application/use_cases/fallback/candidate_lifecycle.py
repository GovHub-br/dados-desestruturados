"""Componente especializado do caso de uso de fallback LLM."""

from __future__ import annotations

from ._common import *  # noqa: F401,F403


class CandidateLifecycleMixin:
    def persist_candidate_layout(
        self,
        candidate_layout_response: dict[str, Any],
        loaded_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Materializa o layout candidato em area isolada de fallback."""
        candidate = candidate_layout_response.get("candidate_layout")
        if not isinstance(candidate, dict):
            raise RuntimeError("Resposta LLM sem candidate_layout para persistir.")

        fallback_context = self._loaded_fallback_context(loaded_context)
        object_key = self._fallback_object_key(
            fallback_context,
            "layout_signature_candidato.json",
        )
        candidate_to_persist = deepcopy(candidate)
        candidate_to_persist["persistido_em"] = datetime.now(UTC).isoformat()
        candidate_to_persist["candidate_layout_object_key"] = object_key
        candidate_to_persist["secoes_atualizadas"] = self._candidate_updated_sections(candidate)

        uri = self.minio_client.put_json(object_key=object_key, payload=candidate_to_persist)
        persisted: dict[str, Any] = {
            "tipo_artefato": "layout_signature_candidato_persistido",
            "status": "persistido",
            "candidate_layout_object_key": object_key,
            "candidate_layout_uri": uri,
            "fallback_context": fallback_context,
        }
        initial_layout_skeleton = loaded_context.get("initial_layout_skeleton")
        if isinstance(initial_layout_skeleton, dict) and initial_layout_skeleton:
            revalidation_layout = self._compose_initial_layout_for_revalidation(
                initial_layout_skeleton=initial_layout_skeleton,
                candidate=candidate,
                candidate_key=object_key,
            )
            revalidation_layout_key = self._fallback_object_key(
                fallback_context,
                "layout_signature_candidato_revalidacao.json",
            )
            persisted["revalidation_layout_object_key"] = revalidation_layout_key
            persisted["revalidation_layout_uri"] = self.minio_client.put_json(
                object_key=revalidation_layout_key,
                payload=revalidation_layout,
            )
        return persisted


    def build_revalidation_conf(
        self,
        persisted_candidate: dict[str, Any],
        loaded_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Monta o dag_run.conf usado para revalidar o candidato na DAG 2."""
        fallback_context = self._loaded_fallback_context(loaded_context)
        object_keys = loaded_context.get("object_keys", {})
        if not isinstance(object_keys, dict):
            object_keys = {}

        candidate_key = str(persisted_candidate.get("candidate_layout_object_key", "")).strip()
        if not candidate_key:
            raise RuntimeError("Layout candidato persistido sem object_key.")
        revalidation_layout_key = str(
            persisted_candidate.get("revalidation_layout_object_key", candidate_key)
        ).strip()
        if not revalidation_layout_key:
            raise RuntimeError("Layout de revalidacao sem object_key.")

        revalidation_prefix = self._fallback_prefix(fallback_context, "revalidation")
        revalidation_conf = {
            "domain": fallback_context.get("domain"),
            "entity_slug": fallback_context["entity_slug"],
            "entity_name": fallback_context.get("entity_name"),
            # Compatibilidade com a DAG 2 e manifestos de construtoras legados.
            "company_slug": fallback_context.get("company_slug"),
            "document_id": fallback_context["document_id"],
            "execution_id": fallback_context["execution_id"],
            "source_execution_id": fallback_context.get(
                "source_execution_id",
                fallback_context["execution_id"],
            ),
            "fallback_execution_id": fallback_context.get(
                "fallback_execution_id",
                fallback_context["execution_id"],
            ),
            "manifest_key": fallback_context["manifest_key"],
            "trigger_origin_dag": "dag_valida_e_fallback_llm",
            "modo_execucao": "revalidacao_layout_candidato",
            "layout_signature_object_key": revalidation_layout_key,
            "layout_signature_uri": self._minio_uri(revalidation_layout_key),
            "candidate_layout_object_key": candidate_key,
            "fallback_revalidation_layout_object_key": revalidation_layout_key,
            "fallback_candidate_object_key": candidate_key,
            "fallback_base_layout_object_key": object_keys.get("layout_signature_base"),
            "fallback_revalidation_prefix": revalidation_prefix,
            "fallback_mode": fallback_context.get("fallback_mode"),
        }
        contrato_semantico_uri = str(
            fallback_context.get("contrato_semantico_uri") or ""
        ).strip()
        if contrato_semantico_uri and contrato_semantico_uri.lower() != "none":
            revalidation_conf["contrato_semantico_uri"] = contrato_semantico_uri
        return revalidation_conf


    def evaluate_revalidation_result(
        self,
        revalidation_conf: dict[str, Any],
    ) -> dict[str, Any]:
        """Le a validacao da DAG 2 contra o candidato e decide se pode publicar."""
        prefix = str(revalidation_conf.get("fallback_revalidation_prefix", "")).strip()
        if not prefix:
            raise RuntimeError("Revalidacao sem fallback_revalidation_prefix.")

        validation_key = f"{prefix.rstrip('/')}/validacao_layout_signature.json"
        validation = self._load_json_object(validation_key, "validacao_relayout_candidato")
        status_info = validation.get("status_compatibilidade")
        if not isinstance(status_info, dict):
            raise RuntimeError(
                f"validacao_layout_signature da revalidacao malformada: {validation_key}"
            )

        status = str(status_info.get("status", "")).strip()
        result = {
            "tipo_artefato": "resultado_revalidacao_layout_candidato",
            "validation_object_key": validation_key,
            "status_compatibilidade": status,
            "aprovado_para_publicacao": status == "compativel",
            "codigos_alerta": status_info.get("codigos_alerta", []),
            "candidate_layout_object_key": revalidation_conf.get("candidate_layout_object_key"),
        }
        status_key = f"{prefix.rstrip('/')}/resultado_revalidacao_candidato.json"
        result["resultado_revalidacao_object_key"] = status_key
        result["resultado_revalidacao_uri"] = self.minio_client.put_json(
            object_key=status_key,
            payload=result,
        )
        if status != "compativel":
            raise RuntimeError(
                "Layout candidato reprovado pela DAG 2. "
                f"Status: {status}. Validacao: {validation_key}."
            )
        return result


    def publish_validated_layout_version(
        self,
        revalidation_result: dict[str, Any],
        revalidation_conf: dict[str, Any],
    ) -> dict[str, Any]:
        """Publica uma nova versao de layout somente apos revalidacao compativel."""
        if not bool(revalidation_result.get("aprovado_para_publicacao")):
            raise RuntimeError("Candidato nao aprovado para publicacao automatica.")

        candidate_key = str(revalidation_conf.get("candidate_layout_object_key", "")).strip()
        if not candidate_key:
            raise RuntimeError("Publicacao sem candidate_layout_object_key.")
        candidate = self._load_json_object(candidate_key, "layout_signature_candidato")
        if candidate.get("publicacao_automatica_habilitada") is False:
            raise RuntimeError("Candidato desabilitou publicacao automatica.")

        entity_slug = str(
            revalidation_conf.get("entity_slug") or revalidation_conf.get("company_slug") or ""
        ).strip()
        if not entity_slug:
            raise RuntimeError("Publicacao sem entity_slug.")

        base_key = str(
            candidate.get("base_layout_signature", {}).get("object_key", "")
            if isinstance(candidate.get("base_layout_signature"), dict)
            else ""
        ).strip()
        if base_key:
            base_layout = self._load_json_object(base_key, "layout_signature_base")
        else:
            revalidation_layout_key = str(
                revalidation_conf.get("fallback_revalidation_layout_object_key", "")
            ).strip()
            base_layout = (
                self._load_json_object(
                    revalidation_layout_key,
                    "layout_signature_candidato_revalidacao",
                )
                if revalidation_layout_key
                else {}
            )
        config = self.config_loader.load_local_platform_config()
        domain = str(revalidation_conf.get("domain") or config.dominio).strip()
        next_version = self._next_layout_version(entity_slug, domain=domain)
        published_key = (
            f"{self._prefix_for_domain(config.minio_layout_prefix, domain)}/"
            f"{entity_slug}/{next_version}/layout_signature_deterministico.json"
        )
        if self.minio_client.object_exists(published_key):
            raise RuntimeError(
                "Publicacao recusada para evitar sobrescrita de layout existente: "
                f"{published_key}"
            )

        published_layout = self._build_published_layout_from_candidate(
            base_layout=base_layout,
            candidate=candidate,
            version=next_version,
            candidate_key=candidate_key,
            revalidation_result=revalidation_result,
        )
        published_uri = self.minio_client.put_json(
            object_key=published_key,
            payload=published_layout,
        )
        pointer_key = self._current_layout_pointer_object_key(entity_slug, domain=domain)
        pointer_payload = {
            "tipo_artefato": "layout_signature_current_pointer",
            "entity_slug": entity_slug,
            "domain": domain,
            "current_version": next_version,
            "object_key": published_key,
            "uri": published_uri,
            "updated_at": datetime.now(UTC).isoformat(),
            "updated_by": "dag_valida_e_fallback_llm",
            "candidate_layout_object_key": candidate_key,
            "validation_object_key": revalidation_result.get("validation_object_key"),
        }
        pointer_uri = self.minio_client.put_json(
            object_key=pointer_key,
            payload=pointer_payload,
        )

        publication = {
            "tipo_artefato": "publicacao_layout_signature",
            "status": "publicado",
            "published_layout_object_key": published_key,
            "published_layout_uri": published_uri,
            "current_pointer_object_key": pointer_key,
            "current_pointer_uri": pointer_uri,
            "versao_publicada": next_version,
            "candidate_layout_object_key": candidate_key,
            "base_layout_signature_object_key": base_key,
            "validation_object_key": revalidation_result.get("validation_object_key"),
            "publicado_em": datetime.now(UTC).isoformat(),
        }
        publication_key = self._fallback_object_key(
            self._fallback_context_from_revalidation_conf(revalidation_conf),
            "publicacao_layout_signature.json",
        )
        publication["publication_object_key"] = publication_key
        publication["publication_uri"] = self.minio_client.put_json(
            object_key=publication_key,
            payload=publication,
        )
        return publication

"""Componente especializado da projeção de contexto do fallback."""

from __future__ import annotations

from ._context_support import *  # noqa: F401,F403
from .context_projection import FallbackContextProjectionMixin


class FallbackPayloadAssemblyMixin:
    @staticmethod
    def _base_artifact_selection_payload(
        context: dict[str, Any],
        *,
        tipo_payload: str,
        include_failure: bool = True,
        include_relevant_layout: bool = True,
    ) -> dict[str, Any]:
        """Base compartilhada dos payloads de selecao de artefatos."""
        payload: dict[str, Any] = {
            "tipo_payload": tipo_payload,
            "escopo_permitido": context.get("escopo_permitido"),
            "contrato_semantico_relevante": (
                FallbackPayloadAssemblyMixin._artifact_selection_contract_context(
                    context.get("contrato_semantico_relevante", {})
                )
            ),
            "inventario_extracao": context.get("inventario_extracao", {}),
        }
        if include_failure:
            payload["falha"] = context.get("falha", {})
        if include_relevant_layout:
            payload["layout_signature_relevante"] = context.get("layout_signature_relevante", {})
        return payload


    @staticmethod
    def _artifact_selection_contract_context(contract_context: Any) -> dict[str, Any]:
        """Projeta o contrato para a selecao sem expor estrutura de mapeamento.

        A primeira chamada precisa conhecer entidades, metricas e os poucos campos
        que requerem evidencia. Paths e arrays continuam restritos ao validador e
        a geracao do candidato.
        """
        if not isinstance(contract_context, dict):
            return {}

        semantic = contract_context.get("contrato_semantico", {})
        requirements = mapping_requirements_from_context(
            contract_context
        )
        identification = contract_context.get("identificacao", {})
        return {
            "identificacao": identification if isinstance(identification, dict) else {},
            "contrato_semantico": {
                "entidades": (
                    semantic.get("entidades", {}) if isinstance(semantic, dict) else {}
                ),
                "metricas": (
                    semantic.get("metricas", {}) if isinstance(semantic, dict) else {}
                ),
                "requisitos_mapeamento": mapping_requirements_payload(requirements),
            },
        }


    @staticmethod
    def _base_candidate_payload(
        context: dict[str, Any],
        *,
        tipo_payload: str,
        include_failure: bool = True,
        include_relevant_layout: bool = True,
        include_base_validation_context: bool = True,
    ) -> dict[str, Any]:
        """Base compartilhada dos payloads de geracao de candidato."""
        scope = context.get("escopo_permitido")
        payload: dict[str, Any] = {
            "tipo_payload": tipo_payload,
            "escopo_permitido": scope,
            "contexto_execucao": FallbackContextProjectionMixin._candidate_execution_context(
                context
            ),
            "contrato_semantico_relevante": context.get("contrato_semantico_relevante", {}),
            "alvos_mapeaveis": FallbackContextProjectionMixin._mappable_targets(
                context.get("contrato_semantico_relevante", {})
            ),
            "exemplo_estrutura_layout_signature": (
                FallbackPayloadAssemblyMixin._layout_signature_structure_example(context)
            ),
        }
        if include_failure:
            payload["falha"] = context.get("falha", {})
        if include_relevant_layout:
            payload["layout_signature_relevante"] = context.get("layout_signature_relevante", {})
        base_ref = context.get("layout_signature_base_ref")
        if base_ref is not None:
            payload["layout_signature_base_ref"] = base_ref
        if include_base_validation_context:
            payload["layout_signature_base_validation_context"] = context.get(
                "layout_signature_base_validation_context",
                {},
            )
        return payload


    @staticmethod
    def _layout_signature_structure_example(context: dict[str, Any]) -> dict[str, Any]:
        """Define um exemplo executavel da estrutura esperada do candidato."""
        execution_context = FallbackContextProjectionMixin._candidate_execution_context(context)
        scope = context.get("escopo_permitido")
        base_ref = context.get("layout_signature_base_ref")
        return {
            "modelo_resposta_no_nivel_raiz": {
                "tipo_artefato": "layout_signature_candidato",
                "status_layout": "candidato",
                "escopo_correcao": scope,
                "document_id": execution_context.get("document_id"),
                "execution_id_origem": execution_context.get("execution_id_origem"),
                "base_layout_signature": (
                    None if scope == "criacao_inicial_layout" else base_ref
                ),
                "fontes_relevantes": {},
                "regras_deteccao_mudanca": [],
                "campos_nao_mapeados": [],
                "mapeamento_canonico": {
                    "campo.permitido": {
                        "tipo_origem": "celula_de_tabela",
                        "arquivo_origem": "tables/table001.json",
                        "obrigatorio": True,
                    }
                },
                "metadados_estruturais_evidencia": {},
            },
            "secoes_necessarias": {
                "fontes_relevantes": "objeto JSON",
                "regras_deteccao_mudanca": "lista JSON",
                "campos_nao_mapeados": "lista JSON de ausencias comprovadas",
                "mapeamento_canonico": "objeto JSON nao vazio",
                "metadados_estruturais_evidencia": "objeto JSON",
            },
            "formato_campos_nao_mapeados": {
                "path": "campo.permitido",
                "seletores": {"papel_observacao": "referencia"},
                "motivo": "A evidencia carregada nao contem a observacao exigida.",
                "artefatos_verificados": ["tables/table001.json"],
            },
            "tipos_origem_permitidos": [
                "valor_fixo",
                "campo_derivado",
                "campo_json",
                "bloco_textual",
                "cabecalho_de_tabela",
                "celula_de_tabela",
                "linhas_de_tabela",
                "juncao_de_registros_json",
            ],
            "formatos_de_origem": {
                "valor_fixo": {
                    "tipo_origem": "valor_fixo",
                    "valor_fixo": "valor estavel declarado pelo layout",
                    "obrigatorio": True,
                },
                "campo_derivado": {
                    "tipo_origem": "campo_derivado",
                    "campo_origem": "outro.path.ja.resolvido",
                    "obrigatorio": True,
                },
                "campo_json": {
                    "tipo_origem": "campo_json",
                    "arquivo_origem": "manifesto_execucao.json",
                    "caminho_json": "campo.publicado.no.artefato",
                    "obrigatorio": True,
                },
                "bloco_textual": {
                    "tipo_origem": "bloco_textual",
                    "arquivo_origem": "blocks/blocks.jsonl",
                    "padrao": "expressao regular que encontra o valor",
                    "obrigatorio": True,
                },
                "cabecalho_de_tabela": {
                    "tipo_origem": "cabecalho_de_tabela",
                    "arquivo_origem": "tables/table001.json",
                    "seletor_coluna": {
                        "indice_coluna_esperado": 1,
                    },
                    "obrigatorio": True,
                },
                "celula_de_tabela": {
                    "tipo_origem": "celula_de_tabela",
                    "arquivo_origem": "tables/table001.json",
                    "seletor_linha": {
                        "coluna_rotulo": 0,
                        "valor_aceito": "rotulo exatamente observado",
                        "indice_linha_esperado": 0,
                    },
                    "seletor_coluna": {
                        "indice_coluna_esperado": 1,
                    },
                    "obrigatorio": True,
                },
                "linhas_de_tabela": {
                    "tipo_origem": "linhas_de_tabela",
                    "arquivo_origem": "tables/table001.json",
                    "linha_inicial": 0,
                    "linha_final": 10,
                    "indices_colunas": [0, 1],
                    "obrigatorio": True,
                },
                "juncao_de_registros_json": {
                    "tipo_origem": "juncao_de_registros_json",
                    "fontes": [
                        {
                            "arquivo_origem": "charts/chart001.json",
                            "caminho_chave": "periodo",
                            "campos": [
                                {"campo_saida": "valor_a", "caminho_json": "valor"}
                            ],
                        },
                        {
                            "arquivo_origem": "charts/chart002.json",
                            "caminho_chave": "periodo",
                            "campos": [
                                {"campo_saida": "valor_b", "caminho_json": "valor"}
                            ],
                        },
                    ],
                    "obrigatorio": True,
                },
            },
            "exemplo_de_mapeamento": {
                "valor_fixo": {
                    "campo.de_saida": {
                        "tipo_origem": "valor_fixo",
                        "valor_fixo": "unidades",
                        "obrigatorio": True,
                    }
                },
                "celula_de_tabela_com_seletores": {
                    "colecao[dimensao=valor].medidas[papel=referencia]": {
                        "tipo_origem": "celula_de_tabela",
                        "arquivo_origem": "tables/table001.json",
                        "papel": "referencia",
                        "seletor_linha": {
                            "tipo_match": "exato",
                            "coluna_rotulo": 0,
                            "valor_aceito": "rotulo observado",
                            "indice_linha_esperado": 12,
                        },
                        "seletor_coluna": {
                            "indice_coluna_esperado": 1,
                            "contexto_observado": "valor publicado",
                        },
                        "obrigatorio": True,
                    }
                },
            },
        }

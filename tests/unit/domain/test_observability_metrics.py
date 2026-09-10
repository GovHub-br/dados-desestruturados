"""Testes das metricas de observabilidade do fluxo Atlas."""

from __future__ import annotations

import unittest

from document_processing.domain.observability import (
    end_to_end_metrics,
    fallback_execution_metrics,
    fallback_stage_metrics,
    layout_validation_metrics,
    resolution_metrics,
    transition_metrics,
)


def _by_name(metrics) -> dict[str, object]:
    """Indexa metricas pelo nome para facilitar as asserts."""
    return {metric.name: metric.value for metric in metrics}


class LayoutValidationMetricsTest(unittest.TestCase):
    def test_validacao_sem_regras_nao_conta_como_cobertura(self) -> None:
        """Status compativel com zero regras nao pode parecer validacao real."""
        report = {
            "status_compatibilidade": {
                "status": "compativel",
                "regras_total": 0,
                "regras_aprovadas": 0,
                "regras_reprovadas": 0,
                "codigos_alerta": [],
            }
        }
        values = _by_name(layout_validation_metrics(report))
        self.assertEqual(values["validacao_status"], "compativel")
        self.assertEqual(values["validacao_regras_total"], 0.0)
        self.assertEqual(values["validacao_cobertura_de_regras"], 0.0)

    def test_validacao_com_regras_aprovadas(self) -> None:
        """Regras executadas e aprovadas produzem taxa e cobertura positivas."""
        report = {
            "status_compatibilidade": {
                "status": "compativel",
                "regras_total": 4,
                "regras_aprovadas": 3,
                "regras_reprovadas": 1,
                "codigos_alerta": ["FALHA_X"],
            }
        }
        values = _by_name(layout_validation_metrics(report))
        self.assertEqual(values["validacao_regras_total"], 4.0)
        self.assertEqual(values["validacao_taxa_aprovacao_regras"], 0.75)
        self.assertEqual(values["validacao_regras_reprovadas"], 1.0)
        self.assertEqual(values["validacao_cobertura_de_regras"], 1.0)


class ResolutionMetricsTest(unittest.TestCase):
    def test_cobertura_de_obrigatorios_e_omitida_quando_nao_ha_obrigatorios(self) -> None:
        """Ausencia de campos obrigatorios nao pode virar cobertura zero."""
        audit = [
            {"obrigatorio": False, "status_resolucao": "resolvido", "evidencia": {}}
            for _ in range(3)
        ]
        values = _by_name(resolution_metrics(audit))
        self.assertNotIn("resolucao_cobertura_obrigatorios", values)
        self.assertEqual(values["resolucao_campos_obrigatorios"], 0.0)
        self.assertEqual(values["resolucao_cobertura_campos"], 1.0)

    def test_cobertura_de_obrigatorios_quando_existem(self) -> None:
        """Com obrigatorios declarados, a cobertura reflete o que foi resolvido."""
        audit = [
            {"obrigatorio": True, "status_resolucao": "resolvido", "evidencia": {}},
            {"obrigatorio": True, "status_resolucao": "nao_resolvido", "evidencia": {}},
            {"obrigatorio": False, "status_resolucao": "resolvido", "evidencia": {}},
        ]
        values = _by_name(resolution_metrics(audit))
        self.assertEqual(values["resolucao_campos_obrigatorios"], 2.0)
        self.assertEqual(values["resolucao_cobertura_obrigatorios"], 0.5)
        self.assertEqual(values["resolucao_campos_nao_resolvidos"], 1.0)

    def test_literais_do_contrato_nao_inflam_a_cobertura_observada(self) -> None:
        """Valores fixos do contrato saem da cobertura de valores observados."""
        audit = [
            {
                "obrigatorio": False,
                "status_resolucao": "resolvido",
                "evidencia": {"origem": "literal_do_contrato_semantico"},
            },
            {"obrigatorio": False, "status_resolucao": "nao_resolvido", "evidencia": {}},
        ]
        values = _by_name(resolution_metrics(audit))
        self.assertEqual(values["resolucao_cobertura_campos"], 0.5)
        self.assertEqual(values["resolucao_cobertura_obs"], 0.0)

    def test_cobertura_do_contrato_usa_folhas_dinamicas(self) -> None:
        """Campos dinamicos do contrato definem o denominador real da cobertura."""
        contract = {
            "schema_saida": {
                "fonte": "relatorio",
                "periodo": "string",
                "valores": {"a": "number", "b": "number | null"},
            }
        }
        audit = [{"obrigatorio": False, "status_resolucao": "resolvido", "evidencia": {}}]
        values = _by_name(resolution_metrics(audit, contract=contract))
        self.assertEqual(values["resolucao_cobertura_do_contrato"], round(1 / 3, 6))


class FallbackMetricsTest(unittest.TestCase):
    def test_acerto_de_primeira_exige_sucesso_e_uma_tentativa(self) -> None:
        """Sucesso apos correcao nao conta como acerto na primeira tentativa."""
        primeira = _by_name(
            fallback_stage_metrics(stage="selecao_artefatos", attempts=1, succeeded=True)
        )
        self.assertEqual(primeira["llm_acerto_1a_tentativa"], 1.0)
        self.assertEqual(primeira["llm_etapa_sucesso"], 1.0)

        corrigida = _by_name(
            fallback_stage_metrics(stage="selecao_artefatos", attempts=3, succeeded=True)
        )
        self.assertEqual(corrigida["llm_acerto_1a_tentativa"], 0.0)
        self.assertEqual(corrigida["llm_etapa_sucesso"], 1.0)
        self.assertEqual(corrigida["llm_tentativas"], 3.0)

    def test_tokens_somam_todas_as_tentativas(self) -> None:
        """O custo da etapa inclui as tentativas descartadas."""
        values = _by_name(
            fallback_stage_metrics(
                stage="layout_signature_candidato",
                attempts=2,
                succeeded=True,
                usage_by_attempt=[
                    {"total_tokens": 100, "completion_tokens": 40},
                    {"total_tokens": 250, "completion_tokens": 90},
                ],
            )
        )
        self.assertEqual(values["llm_tokens_total"], 350.0)

    def test_gate_efetivo_reprova_aprovacao_sem_regras(self) -> None:
        """Aprovacao com zero regras executadas nao e gate efetivo."""
        values = _by_name(
            fallback_execution_metrics(
                scope="criacao_inicial_layout",
                candidate_valid=True,
                revalidation={"aprovado_para_publicacao": True},
                revalidation_validation={
                    "status_compatibilidade": {
                        "status": "compativel",
                        "regras_total": 0,
                        "regras_aprovadas": 0,
                    }
                },
                publication={"status": "publicado", "versao_publicada": "v1.0.0"},
                total_llm_attempts=4,
            )
        )
        self.assertEqual(values["revalidacao_aprovada"], 1.0)
        self.assertEqual(values["publicacao_realizada"], 1.0)
        self.assertEqual(values["revalidacao_regras_executadas"], 0.0)
        self.assertEqual(values["revalidacao_gate_efetivo"], 0.0)

    def test_gate_efetivo_aprova_com_regras_executadas(self) -> None:
        """Aprovacao sustentada por regras aprovadas conta como gate efetivo."""
        values = _by_name(
            fallback_execution_metrics(
                scope="correcao_parcial_mapeamento",
                candidate_valid=True,
                revalidation={"aprovado_para_publicacao": True},
                revalidation_validation={
                    "status_compatibilidade": {
                        "status": "compativel",
                        "regras_total": 5,
                        "regras_aprovadas": 5,
                    }
                },
                publication={"status": "publicado"},
                total_llm_attempts=2,
            )
        )
        self.assertEqual(values["revalidacao_gate_efetivo"], 1.0)


class TransitionAndEndToEndMetricsTest(unittest.TestCase):
    def test_transicao_registra_delta_de_cobertura(self) -> None:
        """A transicao entre etapas expoe regressao de cobertura."""
        values = _by_name(
            transition_metrics(
                origem="resolucao",
                destino="fallback",
                habilitada=True,
                motivo="incompativel",
                perda_de_cobertura=-0.25,
            )
        )
        self.assertEqual(values["transicao_resolucao_para_fallback"], 1.0)
        self.assertEqual(values["transicao_resolucao_para_fallback_delta_cobertura"], -0.25)

    def test_autonomia_e_o_inverso_do_uso_de_llm(self) -> None:
        """Autonomia deterministica cai a zero quando a LLM e acionada."""
        com_llm = _by_name(end_to_end_metrics(sucesso=True, exigiu_llm=True))
        sem_llm = _by_name(end_to_end_metrics(sucesso=True, exigiu_llm=False))
        self.assertEqual(com_llm["e2e_autonomia_deterministica"], 0.0)
        self.assertEqual(sem_llm["e2e_autonomia_deterministica"], 1.0)


if __name__ == "__main__":
    unittest.main()

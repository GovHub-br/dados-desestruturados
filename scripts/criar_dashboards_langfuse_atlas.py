#!/usr/bin/env python3
"""Cria os dashboards do Atlas no Langfuse.

O Langfuse nao expoe API publica para dashboards, entao os painéis sao escritos
direto nas tabelas `dashboards` e `dashboard_widgets` do banco do proprio
Langfuse. O script e idempotente: recria os widgets de cada dashboard pelo nome.

Uso:

    python scripts/criar_dashboards_langfuse_atlas.py --dry-run
    python scripts/criar_dashboards_langfuse_atlas.py
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
from typing import Any

import psycopg


def _id() -> str:
    """Identificador no formato usado pelas linhas existentes do Langfuse."""
    return secrets.token_hex(13)[:25]


def score_widget(
    name: str,
    description: str,
    score_names: list[str],
    *,
    chart_type: str = "LINE_TIME_SERIES",
    agg: str = "avg",
    dimension_by_name: bool = True,
    dimension_field: str = "name",
    view: str = "SCORES_NUMERIC",
    row_limit: int | None = None,
) -> dict[str, Any]:
    """Widget sobre metricas (scores) filtrando por nomes do catalogo.

    A medida depende da view. `scores-numeric` agrega o proprio valor; ja
    `scores-categorical` so aceita `count`, e a categoria observada aparece na
    dimensao `stringValue`. Dimensionar uma view categorica por `name` produziria
    uma unica fatia, porque o filtro ja fixa o nome da metrica.
    """
    categorical = view == "SCORES_CATEGORICAL"
    measure = "count" if categorical else "value"
    effective_agg = "count" if categorical else agg
    if categorical:
        dimensions = [{"field": "stringValue"}]
    elif dimension_by_name:
        dimensions = [{"field": dimension_field}]
    else:
        dimensions = []
    config: dict[str, Any] = {"type": chart_type}
    if row_limit:
        config["row_limit"] = row_limit
        config["show_value_labels"] = True
    return {
        "name": name,
        "description": description,
        "view": view,
        "dimensions": dimensions,
        "metrics": [{"agg": effective_agg, "measure": measure}],
        "filters": [
            {
                "type": "stringOptions",
                "value": score_names,
                "column": "name",
                "operator": "any of",
            }
        ],
        "chart_type": chart_type,
        "chart_config": config,
    }


def trace_widget(
    name: str,
    description: str,
    *,
    chart_type: str = "LINE_TIME_SERIES",
    agg: str = "count",
    measure: str = "count",
    dimensions: list[dict[str, str]] | None = None,
    filters: list[dict[str, Any]] | None = None,
    row_limit: int | None = None,
) -> dict[str, Any]:
    """Widget sobre traces, para volume, latencia e custo."""
    config: dict[str, Any] = {"type": chart_type}
    if row_limit:
        config["row_limit"] = row_limit
        config["show_value_labels"] = True
    return {
        "name": name,
        "description": description,
        "view": "TRACES",
        "dimensions": dimensions or [],
        "metrics": [{"agg": agg, "measure": measure}],
        "filters": filters or [],
        "chart_type": chart_type,
        "chart_config": config,
    }


def observation_widget(
    name: str,
    description: str,
    *,
    chart_type: str = "LINE_TIME_SERIES",
    agg: str = "sum",
    measure: str = "totalTokens",
    dimensions: list[dict[str, str]] | None = None,
    row_limit: int | None = None,
) -> dict[str, Any]:
    """Widget sobre observations, para tokens e latencia por etapa."""
    config: dict[str, Any] = {"type": chart_type}
    if row_limit:
        config["row_limit"] = row_limit
        config["show_value_labels"] = True
    return {
        "name": name,
        "description": description,
        "view": "OBSERVATIONS",
        "dimensions": dimensions or [],
        "metrics": [{"agg": agg, "measure": measure}],
        "filters": [],
        "chart_type": chart_type,
        "chart_config": config,
    }


DASHBOARDS: list[dict[str, Any]] = [
    {
        "name": "Atlas - Saude do Fluxo Ponta a Ponta",
        "description": (
            "Visao executiva do fluxo Atlas: quanto do pipeline se resolve sem LLM, "
            "quanto chega apto a bronze e quanto custa cada release."
        ),
        "widgets": [
            score_widget(
                "Autonomia deterministica",
                "Fracao de execucoes resolvidas sem acionar a LLM. Meta: subir ao longo do tempo.",
                ["e2e_autonomia_deterministica"],
                dimension_by_name=False,
            ),
            score_widget(
                "Sucesso e aptidao para bronze",
                "Execucoes concluidas com schema utilizavel e liberadas para ingestao.",
                ["e2e_sucesso", "e2e_apto_para_bronze"],
            ),
            score_widget(
                "Cobertura final do contrato",
                "Cobertura de campos do contrato no artefato final da execucao.",
                ["e2e_cobertura_final", "resolucao_cobertura_do_contrato"],
            ),
            score_widget(
                "Custo de LLM por execucao",
                "Tokens gastos por execucao de ponta a ponta.",
                ["e2e_tokens_llm", "fallback_tokens_total"],
            ),
            trace_widget(
                "Execucoes por etapa do fluxo",
                "Volume de traces por nome: extracao, resolucao, fallback e bronze.",
                chart_type="HORIZONTAL_BAR",
                dimensions=[{"field": "name"}],
                row_limit=10,
            ),
            trace_widget(
                "Latencia p95 por etapa",
                "Latencia p95 de cada etapa do fluxo Atlas.",
                agg="p95",
                measure="latency",
                dimensions=[{"field": "name"}],
            ),
        ],
    },
    {
        "name": "Atlas - Validacao e Resolucao Deterministica",
        "description": (
            "DAG 2: saude do layout signature e da resolucao deterministica. "
            "Mostra se as regras de deteccao de mudanca existem e se estao passando."
        ),
        "widgets": [
            score_widget(
                "Cobertura de regras deterministicas",
                (
                    "Fracao de validacoes que executaram ao menos uma regra. "
                    "Valor baixo indica layout signature publicado sem regras de deteccao."
                ),
                ["validacao_cobertura_de_regras"],
                dimension_by_name=False,
            ),
            score_widget(
                "Regras executadas e reprovadas",
                "Volume absoluto de regras deterministicas por execucao.",
                ["validacao_regras_total", "validacao_regras_reprovadas", "revalidacao_regras_executadas"],
            ),
            score_widget(
                "Taxa de aprovacao das regras",
                "Fracao das regras deterministicas aprovadas quando elas existem.",
                ["validacao_taxa_aprovacao_regras"],
                dimension_by_name=False,
            ),
            score_widget(
                "Cobertura da resolucao",
                (
                    "Campos resolvidos sobre mapeados, obrigatorios e observados. "
                    "A cobertura observada exclui literais do contrato."
                ),
                [
                    "resolucao_cobertura_campos",
                    "resolucao_cobertura_obrigatorios",
                    "resolucao_cobertura_obs",
                ],
                chart_type="HORIZONTAL_BAR",
                row_limit=10,
            ),
            score_widget(
                "Campos nao resolvidos",
                "Campos mapeados que falharam na resolucao deterministica.",
                ["resolucao_campos_nao_resolvidos", "resolucao_campos_mapeados"],
            ),
            score_widget(
                "Status de compatibilidade",
                "Distribuicao dos status de validacao do layout signature.",
                ["validacao_status"],
                view="SCORES_CATEGORICAL",
                chart_type="PIE",
            ),
        ],
    },
    {
        "name": "Atlas - Fallback LLM",
        "description": (
            "DAG 3: eficiencia do fallback assistido por LLM. "
            "Mostra qual etapa consome tentativas e tokens e qual escopo e escolhido."
        ),
        "widgets": [
            score_widget(
                "Acerto na primeira tentativa por etapa",
                (
                    "Fracao de etapas de LLM aprovadas sem ciclo de correcao. "
                    "Etapas com valor baixo sao as candidatas a ajuste de prompt."
                ),
                ["llm_acerto_1a_tentativa"],
                chart_type="HORIZONTAL_BAR",
                dimension_field="observationName",
                row_limit=15,
            ),
            score_widget(
                "Tentativas e sucesso das etapas de LLM",
                "Tentativas medias e taxa de sucesso das etapas assistidas por LLM.",
                ["llm_tentativas", "llm_etapa_sucesso"],
            ),
            observation_widget(
                "Tokens por etapa de LLM",
                "Consumo de tokens agrupado pelo nome da observation (etapa do fallback).",
                chart_type="HORIZONTAL_BAR",
                dimensions=[{"field": "name"}],
                row_limit=10,
            ),
            observation_widget(
                "Latencia p95 por etapa de LLM",
                "Latencia p95 de cada chamada de LLM do fallback.",
                agg="p95",
                measure="latency",
                dimensions=[{"field": "name"}],
            ),
            score_widget(
                "Escopo de correcao escolhido",
                (
                    "Distribuicao entre correcao parcial, regeneracao total e criacao inicial. "
                    "Correcao parcial deveria dominar."
                ),
                ["fallback_escopo"],
                view="SCORES_CATEGORICAL",
                chart_type="PIE",
            ),
            score_widget(
                "Candidato valido e tentativas totais",
                "Quantas execucoes produziram candidato valido e a que custo de chamadas.",
                ["fallback_candidato_valido", "fallback_tentativas_llm_total"],
            ),
            score_widget(
                "Acerto por versao de prompt",
                (
                    "Acerto na primeira tentativa agrupado pela versao do conjunto de "
                    "prompts que produziu a chamada. Vazio ate a etapa passar a resolver "
                    "prompt pelo Langfuse."
                ),
                ["llm_acerto_1a_tentativa"],
                chart_type="HORIZONTAL_BAR",
                dimension_field="observationPromptVersion",
                row_limit=10,
            ),
        ],
    },
    {
        "name": "Atlas - Transicoes e Gates de Publicacao",
        "description": (
            "Handoffs entre DAGs e a qualidade do gate que promove layout candidato a ativo. "
            "Separa aprovacao real de aprovacao vazia."
        ),
        "widgets": [
            score_widget(
                "Gate de publicacao efetivo",
                (
                    "Publicacoes sustentadas por regras deterministicas realmente executadas. "
                    "Valor proximo de zero significa promocao de layout sem evidencia."
                ),
                ["revalidacao_gate_efetivo"],
                dimension_by_name=False,
            ),
            score_widget(
                "Aprovacao versus gate efetivo",
                "Compara quanto foi aprovado com quanto foi aprovado com evidencia.",
                ["revalidacao_aprovada", "revalidacao_gate_efetivo", "publicacao_realizada"],
            ),
            score_widget(
                "Transicoes entre etapas",
                "Taxa de sucesso de cada handoff entre as DAGs do fluxo.",
                [
                    "transicao_extracao_para_resolucao",
                    "transicao_resolucao_para_fallback",
                    "transicao_fallback_para_resolucao",
                    "transicao_resolucao_para_bronze",
                ],
                chart_type="HORIZONTAL_BAR",
                row_limit=10,
            ),
            score_widget(
                "Regras no candidato revalidado",
                (
                    "Regras deterministicas executadas na revalidacao. "
                    "Zero indica candidato sem regras de deteccao de mudanca."
                ),
                ["revalidacao_regras_executadas"],
                dimension_by_name=False,
            ),
            trace_widget(
                "Execucoes de fallback por entidade",
                "Quais entidades mais dependem do fallback com LLM.",
                chart_type="HORIZONTAL_BAR",
                dimensions=[{"field": "userId"}],
                row_limit=15,
            ),
            score_widget(
                "Cobertura apos revalidacao",
                "Cobertura de campos obrigatorios medida na revalidacao do candidato.",
                ["resolucao_cobertura_obrigatorios"],
                dimension_by_name=False,
            ),
        ],
    },
]


def build_layout(widget_ids: list[str]) -> dict[str, Any]:
    """Distribui os widgets em uma grade de duas colunas."""
    widgets = []
    for index, widget_id in enumerate(widget_ids):
        widgets.append(
            {
                "x": 0 if index % 2 == 0 else 6,
                "y": (index // 2) * 5,
                "id": secrets.token_hex(8),
                "type": "widget",
                "x_size": 6,
                "y_size": 5,
                "widgetId": widget_id,
            }
        )
    return {"widgets": widgets}


def main() -> int:
    """Cria ou recria os dashboards do Atlas no banco do Langfuse."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--project", default="atlas")
    parser.add_argument(
        "--autor-email",
        default=os.getenv("LANGFUSE_DASHBOARD_AUTHOR_EMAIL", "mateus.castro3@gmail.com"),
        help="Email do usuario Langfuse registrado como autor dos paineis.",
    )
    args = parser.parse_args()

    dsn = (
        f"host={os.environ['LANGFUSE_DATABASE_HOST']} "
        f"port={os.environ['LANGFUSE_DATABASE_PORT']} "
        f"user={os.environ['LANGFUSE_DATABASE_USERNAME']} "
        f"password={os.environ['LANGFUSE_DATABASE_PASSWORD']} "
        f"dbname={os.environ['LANGFUSE_DATABASE_NAME']}"
    )

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("select id from projects where name = %s", (args.project,))
            row = cur.fetchone()
            if not row:
                print(f"projeto '{args.project}' nao encontrado.")
                return 1
            project_id = row[0]
            cur.execute("select id from users where email = %s", (args.autor_email,))
            author_row = cur.fetchone()
            author_id = author_row[0] if author_row else None
            print(f"projeto: {args.project} ({project_id})")
            print(f"autor: {args.autor_email} ({author_id or 'nao encontrado, usando null'})")

            for dashboard in DASHBOARDS:
                # O vinculo dashboard->widget vive no JSON `definition`, sem chave
                # estrangeira. Recriar o painel sem apagar os widgets antigos deixaria
                # linhas orfas acumulando em dashboard_widgets a cada execucao.
                cur.execute(
                    "select definition from dashboards where project_id = %s and name = %s",
                    (project_id, dashboard["name"]),
                )
                anterior = cur.fetchone()
                widgets_obsoletos: list[str] = []
                if anterior and isinstance(anterior[0], dict):
                    widgets_obsoletos = [
                        item["widgetId"]
                        for item in anterior[0].get("widgets", [])
                        if isinstance(item, dict) and item.get("widgetId")
                    ]

                widget_ids: list[str] = []
                for widget in dashboard["widgets"]:
                    widget_id = _id()
                    widget_ids.append(widget_id)
                    if args.dry_run:
                        continue
                    cur.execute(
                        """
                        insert into dashboard_widgets
                            (id, project_id, name, description, view, dimensions,
                             metrics, filters, chart_type, chart_config, created_by, updated_by)
                        values (%s, %s, %s, %s, %s::"DashboardWidgetViews", %s::jsonb, %s::jsonb,
                                %s::jsonb, %s::"DashboardWidgetChartType", %s::jsonb, %s, %s)
                        """,
                        (
                            widget_id,
                            project_id,
                            widget["name"],
                            widget["description"],
                            widget["view"],
                            json.dumps(widget["dimensions"]),
                            json.dumps(widget["metrics"]),
                            json.dumps(widget["filters"]),
                            widget["chart_type"],
                            json.dumps(widget["chart_config"]),
                            author_id,
                            author_id,
                        ),
                    )

                definition = build_layout(widget_ids)
                if args.dry_run:
                    print(
                        f"  [dry-run] {dashboard['name']} "
                        f"({len(dashboard['widgets'])} widgets)"
                    )
                    continue

                cur.execute(
                    "delete from dashboards where project_id = %s and name = %s",
                    (project_id, dashboard["name"]),
                )
                cur.execute(
                    """
                    insert into dashboards
                        (id, project_id, name, description, definition, filters,
                         created_by, updated_by)
                    values (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
                    """,
                    (
                        _id(),
                        project_id,
                        dashboard["name"],
                        dashboard["description"],
                        json.dumps(definition),
                        json.dumps([]),
                        author_id,
                        author_id,
                    ),
                )
                if widgets_obsoletos:
                    cur.execute(
                        "delete from dashboard_widgets where project_id = %s and id = any(%s)",
                        (project_id, widgets_obsoletos),
                    )
                print(
                    f"  criado: {dashboard['name']} ({len(widget_ids)} widgets"
                    + (f", {len(widgets_obsoletos)} obsoletos removidos" if widgets_obsoletos else "")
                    + ")"
                )

        if not args.dry_run:
            conn.commit()
    print("\nconcluido.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

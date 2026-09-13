#!/usr/bin/env python3
"""Compara as metricas do Atlas entre duas versoes do projeto.

E a ferramenta de decisao do desenvolvimento orientado a metricas: depois de
implementar uma mudanca, rode o fluxo com o novo rotulo de release e compare
com a versao anterior sobre os mesmos documentos. Se a metrica-alvo nao subiu,
ou se alguma metrica de guarda caiu, a mudanca nao fica.

Uso:

    python scripts/comparar_releases_langfuse.py --base prod-0.1.0 --novo dev-minha-mudanca
    python scripts/comparar_releases_langfuse.py --listar-releases
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import urllib.parse
import urllib.request
from collections import defaultdict
from typing import Any

# Metricas em que subir e melhor.
MAIOR_MELHOR = {
    "e2e_sucesso",
    "e2e_autonomia_deterministica",
    "e2e_apto_para_bronze",
    "e2e_cobertura_final",
    "resolucao_cobertura_campos",
    "resolucao_cobertura_obrigatorios",
    "resolucao_cobertura_obs",
    "resolucao_cobertura_do_contrato",
    "validacao_taxa_aprovacao_regras",
    "validacao_cobertura_de_regras",
    "validacao_regras_total",
    "revalidacao_gate_efetivo",
    "revalidacao_regras_executadas",
    "llm_acerto_1a_tentativa",
    "llm_etapa_sucesso",
    "fallback_candidato_valido",
    "transicao_extracao_para_resolucao",
    "transicao_fallback_para_resolucao",
    "transicao_resolucao_para_bronze",
    # Avaliacao off-line por etapa (scripts/executar_datasets_langfuse_atlas.py).
    "avaliacao_precisao",
    "avaliacao_revocacao",
    "avaliacao_f1",
    "avaliacao_igualdade_exata",
    "avaliacao_schema_valido",
    "avaliacao_candidato_valido",
    "avaliacao_acerto_tipo_origem",
    "avaliacao_acerto_arquivo_origem",
    "avaliacao_acerto_instrucao_origem",
    # Selecao de artefatos: quanto da evidencia escolhida sustenta a unidade.
    "selecao_evidencia_especifica",
}

# Metricas em que descer e melhor.
MENOR_MELHOR = {
    "e2e_tokens_llm",
    "e2e_duracao_segundos",
    "fallback_tokens_total",
    "fallback_tentativas_llm_total",
    "llm_tentativas",
    "llm_tokens_total",
    "resolucao_campos_nao_resolvidos",
    "validacao_regras_reprovadas",
    "transicao_resolucao_para_fallback",
    "selecao_evidencia_descartada",
}

# Metricas de guarda: nunca podem regredir, mesmo que nao sejam o alvo.
GUARDA = {
    "e2e_apto_para_bronze",
    "resolucao_cobertura_obrigatorios",
    "revalidacao_gate_efetivo",
    "validacao_cobertura_de_regras",
    # Perder a fonte certa nao tem conserto nas etapas seguintes: revocacao e
    # guarda, e a precisao da selecao so vale como alvo enquanto ela nao cair.
    "avaliacao_revocacao",
}


class LangfuseReader:
    """Leitura das metricas agregadas do Langfuse."""

    def __init__(self) -> None:
        self.base = os.environ["LANGFUSE_BASE_URL"].rstrip("/")
        raw = f"{os.environ['LANGFUSE_PUBLIC_KEY']}:{os.environ['LANGFUSE_SECRET_KEY']}"
        self.auth = base64.b64encode(raw.encode()).decode()

    def _get(self, path: str) -> dict[str, Any]:
        """Executa um GET autenticado."""
        request = urllib.request.Request(
            self.base + path, headers={"Authorization": f"Basic {self.auth}"}
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode() or "{}")

    def traces_por_release(self) -> dict[str, list[dict[str, Any]]]:
        """Mapeia release para os traces correspondentes, com documento e etapa."""
        por_release: dict[str, list[dict[str, Any]]] = defaultdict(list)
        page = 1
        while True:
            data = self._get(f"/api/public/traces?limit=100&page={page}")
            for trace in data.get("data", []):
                metadata = trace.get("metadata")
                metadata = metadata if isinstance(metadata, dict) else {}
                por_release[str(trace.get("release") or "sem-release")].append(
                    {
                        "id": trace["id"],
                        "documento": str(trace.get("sessionId") or ""),
                        "etapa": str(trace.get("name") or ""),
                        "execucao": str(metadata.get("execution_id") or ""),
                    }
                )
            meta = data.get("meta", {})
            if not data.get("data") or page * 100 >= int(meta.get("totalItems", 0)):
                break
            page += 1
        return por_release

    def scores(self) -> list[dict[str, Any]]:
        """Le todos os scores do projeto."""
        todos: list[dict[str, Any]] = []
        page = 1
        while True:
            data = self._get(f"/api/public/scores?limit=100&page={page}")
            todos.extend(data.get("data", []))
            meta = data.get("meta", {})
            if not data.get("data") or page * 100 >= int(meta.get("totalItems", 0)):
                break
            page += 1
        return todos


def agregar(
    scores: list[dict[str, Any]], trace_ids: set[str]
) -> dict[str, tuple[float, int]]:
    """Calcula media e contagem de cada metrica numerica de um conjunto de traces."""
    acumulado: dict[str, list[float]] = defaultdict(list)
    for score in scores:
        if score.get("traceId") not in trace_ids:
            continue
        if score.get("dataType") == "CATEGORICAL":
            continue
        value = score.get("value")
        if isinstance(value, (int, float)):
            acumulado[str(score.get("name"))].append(float(value))
    return {
        name: (sum(values) / len(values), len(values))
        for name, values in acumulado.items()
        if values
    }


def direcao(nome: str) -> int:
    """Retorna 1 se maior e melhor, -1 se menor e melhor, 0 se neutro."""
    if nome in MAIOR_MELHOR:
        return 1
    if nome in MENOR_MELHOR:
        return -1
    return 0


def main() -> int:
    """Compara duas releases e devolve codigo de saida diferente de zero em regressao."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="Release de referencia.")
    parser.add_argument("--novo", help="Release a avaliar.")
    parser.add_argument("--listar-releases", action="store_true")
    parser.add_argument(
        "--sem-pareamento",
        dest="pareado",
        action="store_false",
        help="Compara os conjuntos completos em vez de parear por documento.",
    )
    parser.add_argument(
        "--tolerancia",
        type=float,
        default=0.01,
        help="Variacao relativa ignorada como ruido (padrao 1%%).",
    )
    args = parser.parse_args()

    reader = LangfuseReader()
    por_release = reader.traces_por_release()

    if args.listar_releases or not (args.base and args.novo):
        print("releases disponiveis:")
        for release, ids in sorted(por_release.items(), key=lambda item: -len(item[1])):
            print(f"  {release:<44} {len(ids):>4} traces")
        if not (args.base and args.novo):
            print("\ninforme --base e --novo para comparar.")
        return 0

    base_traces = por_release.get(args.base, [])
    novo_traces = por_release.get(args.novo, [])
    if not base_traces:
        print(f"release base '{args.base}' nao tem traces.")
        return 1
    if not novo_traces:
        print(f"release novo '{args.novo}' nao tem traces.")
        return 1

    # Comparacao pareada: so entram documentos presentes nas duas releases,
    # senao a media mistura conjuntos diferentes de PDFs e a variacao vira ruido.
    def _chave(trace: dict[str, Any]) -> tuple[str, str, str]:
        return (trace["documento"], trace["etapa"], trace["execucao"])

    def _chaves(traces: list[dict[str, Any]]) -> set[tuple[str, str, str]]:
        return {_chave(t) for t in traces if t["documento"] and t["execucao"]}

    comuns = _chaves(base_traces) & _chaves(novo_traces)
    if args.pareado and comuns:
        base_ids = {t["id"] for t in base_traces if _chave(t) in comuns}
        novo_ids = {t["id"] for t in novo_traces if _chave(t) in comuns}
        modo = f"pareado por execucao ({len(comuns)} execucoes em comum)"
    else:
        base_ids = {t["id"] for t in base_traces}
        novo_ids = {t["id"] for t in novo_traces}
        modo = "agregado (conjuntos podem diferir)"
        if args.pareado:
            modo += " - nenhum documento em comum"

    scores = reader.scores()
    base = agregar(scores, base_ids)
    novo = agregar(scores, novo_ids)

    print(f"modo : {modo}")
    print(f"base : {args.base:<44} {len(base_ids):>4} traces")
    print(f"novo : {args.novo:<44} {len(novo_ids):>4} traces")
    print()

    nomes = sorted(set(base) | set(novo))
    largura = max((len(name) for name in nomes), default=20)
    print(f"{'metrica':<{largura}}  {'base':>10}  {'novo':>10}  {'delta':>10}  situacao")
    print("-" * (largura + 48))

    regressoes: list[str] = []
    melhorias: list[str] = []

    for nome in nomes:
        base_valor, base_n = base.get(nome, (float("nan"), 0))
        novo_valor, novo_n = novo.get(nome, (float("nan"), 0))
        if not base_n or not novo_n:
            situacao = "ausente em uma das releases"
            base_txt = f"{base_valor:.3f}" if base_n else "-"
            novo_txt = f"{novo_valor:.3f}" if novo_n else "-"
            print(f"{nome:<{largura}}  {base_txt:>10}  {novo_txt:>10}  {'-':>10}  {situacao}")
            continue

        delta = novo_valor - base_valor
        escala = max(abs(base_valor), 1e-9)
        relativo = delta / escala
        sentido = direcao(nome)

        if abs(relativo) <= args.tolerancia:
            situacao = "estavel"
        elif sentido == 0:
            situacao = "mudou (metrica neutra)"
        elif (sentido > 0 and delta > 0) or (sentido < 0 and delta < 0):
            situacao = "melhorou"
            melhorias.append(nome)
        else:
            situacao = "REGREDIU" + (" [guarda]" if nome in GUARDA else "")
            regressoes.append(nome)

        print(
            f"{nome:<{largura}}  {base_valor:>10.3f}  {novo_valor:>10.3f}  "
            f"{delta:>+10.3f}  {situacao}"
        )

    print()
    if melhorias:
        print(f"melhorias ({len(melhorias)}): {', '.join(melhorias)}")
    if regressoes:
        guarda = [nome for nome in regressoes if nome in GUARDA]
        print(f"regressoes ({len(regressoes)}): {', '.join(regressoes)}")
        if guarda:
            print(f"\nREPROVADO: metrica de guarda regrediu: {', '.join(guarda)}")
            return 2
        print("\nATENCAO: houve regressao fora das metricas de guarda.")
        return 1
    if not melhorias:
        print("nenhuma variacao relevante: a mudanca nao moveu as metricas.")
    print("\nAPROVADO: nenhuma metrica de guarda regrediu.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

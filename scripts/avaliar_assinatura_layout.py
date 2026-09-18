#!/usr/bin/env python3
"""Harness de metricas da assinatura de layout (plano da assinatura, fases 0, 1 e 3).

Le os traces ``atlas.fallback`` de uma release no Langfuse, recalcula as metricas
por fase a partir das saidas da LLM + contrato + gabarito por documento, grava
os scores de volta (``assinatura_f<fase>_<metrica>``) e escreve um relatorio local.

Uso:
    python scripts/avaliar_assinatura_layout.py --release baseline0
    python scripts/avaliar_assinatura_layout.py --release baseline1 --sem-scores
    python scripts/avaliar_assinatura_layout.py --release baseline0 --contrato construtoras=infra/.../v1.9.0/contrato.json

Depois, compare releases com ``scripts/comparar_releases_langfuse.py``; os
scores deste harness entram na comparacao como qualquer outro.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from document_processing.domain.observability.signature_evaluation import (  # noqa: E402
    anchoring_metrics,
    expected_entries_metrics,
    selection_metrics,
    structural_metrics,
)

RAIZ = Path(__file__).resolve().parent.parent
CONTRATOS = RAIZ / "infra" / "minio-bootstrap" / "contracts"
GABARITOS = RAIZ / "eval" / "gabaritos"
RELATORIOS = RAIZ / "eval" / "relatorios"


class Langfuse:
    def __init__(self) -> None:
        self.base = os.environ["LANGFUSE_BASE_URL"].rstrip("/")
        raw = f"{os.environ['LANGFUSE_PUBLIC_KEY']}:{os.environ['LANGFUSE_SECRET_KEY']}"
        self.auth = base64.b64encode(raw.encode()).decode()

    def _request(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            self.base + path,
            data=data,
            headers={"Authorization": f"Basic {self.auth}", "Content-Type": "application/json"},
            method="POST" if data else "GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode() or "{}")
        except urllib.error.HTTPError as exc:
            corpo = exc.read().decode(errors="replace")
            raise RuntimeError(f"Langfuse {exc.code} em {path}: {corpo[:500]} | payload={json.dumps(payload)[:300]}") from exc

    def traces(self, release: str) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        page = 1
        while True:
            query = urllib.parse.urlencode({"release": release, "name": "atlas.fallback", "limit": 100, "page": page})
            data = self._request(f"/api/public/traces?{query}")
            found.extend(data.get("data", []))
            meta = data.get("meta", {})
            if not data.get("data") or page * 100 >= int(meta.get("totalItems", 0)):
                break
            page += 1
        return found

    def observations(self, trace_id: str) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        page = 1
        while True:
            data = self._request(f"/api/public/observations?traceId={trace_id}&limit=100&page={page}")
            found.extend(data.get("data", []))
            meta = data.get("meta", {})
            if not data.get("data") or page * 100 >= int(meta.get("totalItems", 0)):
                break
            page += 1
        return sorted(found, key=lambda item: str(item.get("startTime")))

    def score(self, trace_id: str, metric: Any, *, observation_id: str | None = None) -> None:
        # Scores booleanos viajam como 0/1 na API publica.
        valor = metric.value
        if isinstance(valor, bool):
            valor = 1 if valor else 0
        payload: dict[str, Any] = {
            "traceId": trace_id,
            "name": metric.name,
            "value": valor,
            "dataType": metric.data_type,
            "comment": metric.comment,
            "metadata": metric.metadata,
        }
        if observation_id:
            payload["observationId"] = observation_id
        self._request("/api/public/scores", payload)


def carregar_contratos(overrides: list[str]) -> dict[str, dict[str, Any]]:
    """Ultima versao local de cada dominio, salvo override ``dominio=caminho``."""
    contratos: dict[str, dict[str, Any]] = {}
    for dominio_dir in sorted(CONTRATOS.iterdir()):
        if not dominio_dir.is_dir():
            continue
        versoes = sorted(
            (p for p in dominio_dir.iterdir() if p.is_dir()),
            key=lambda p: tuple(int(x) for x in p.name.lstrip("v").split(".")),
        )
        if versoes:
            arquivo = next(versoes[-1].glob("*.json"))
            contratos[dominio_dir.name] = json.loads(arquivo.read_text(encoding="utf-8"))
    for item in overrides:
        dominio, _, caminho = item.partition("=")
        contratos[dominio.strip()] = json.loads(Path(caminho.strip()).read_text(encoding="utf-8"))
    return contratos


def carregar_gabaritos() -> dict[str, dict[str, Any]]:
    gabaritos: dict[str, dict[str, Any]] = {}
    for arquivo in GABARITOS.glob("*.json"):
        gabarito = json.loads(arquivo.read_text(encoding="utf-8"))
        gabaritos[str(gabarito.get("document_id"))] = gabarito
    return gabaritos


def _parsed(observation: dict[str, Any]) -> dict[str, Any]:
    output = observation.get("output")
    if isinstance(output, dict) and isinstance(output.get("parsed_response"), dict):
        return output["parsed_response"]
    return output if isinstance(output, dict) else {}


def _por_etapa(observations: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grupos: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for obs in observations:
        if obs.get("type") == "GENERATION":
            grupos[str(obs.get("name"))].append(obs)
    return grupos


def avaliar_trace(
    trace: dict[str, Any],
    observations: list[dict[str, Any]],
    *,
    contratos: dict[str, dict[str, Any]],
    gabaritos: dict[str, dict[str, Any]],
) -> list[tuple[Any, str | None]]:
    """Metricas de um trace: lista de (metrica, observation_id ou None)."""
    metadata = trace.get("metadata") or {}
    dominio = str(metadata.get("dominio") or "")
    contrato = contratos.get(dominio)
    gabarito = gabaritos.get(str(metadata.get("document_id") or ""))
    resultados: list[tuple[Any, str | None]] = []
    if not contrato:
        return resultados

    mapeamento_final: dict[str, Any] = {}
    mapeamento_primeira: dict[str, Any] = {}
    ausencias_final: list[dict[str, Any]] = []
    candidato_valido = True
    for nome, grupo in _por_etapa(observations).items():
        if nome.endswith("selecao_artefatos"):
            if gabarito:
                finais = [obs for obs in grupo if obs.get("level") != "ERROR"] or grupo[-1:]
                for metric in selection_metrics(_parsed(finais[-1]), gabarito, etapa="final"):
                    resultados.append((metric, finais[-1].get("id")))
                for metric in selection_metrics(_parsed(grupo[0]), gabarito, etapa="primeira_tentativa"):
                    resultados.append((metric, grupo[0].get("id")))
            continue
        if nome.endswith("layout_signature_candidato") or nome.endswith("fragmento_layout_signature"):
            finais = [obs for obs in grupo if obs.get("level") != "ERROR"]
            # Sem resposta aprovada, a ultima tentativa ainda diz o que a LLM declarou
            # (ausencias, por exemplo); o candidato invalido e marcado no relatorio.
            ultima = finais[-1] if finais else grupo[-1]
            candidato_valido = candidato_valido and bool(finais)
            parsed = _parsed(ultima)
            mapeamento_final.update(parsed.get("mapeamento_canonico") or {})
            ausencias_final.extend(parsed.get("campos_nao_mapeados") or [])
            primeira = _parsed(grupo[0])
            mapeamento_primeira.update(primeira.get("mapeamento_canonico") or {})

    identidade = _identidade_do_gabarito(gabarito)
    if mapeamento_primeira:
        for metric in structural_metrics(mapeamento_primeira, contrato, etapa="primeira_tentativa"):
            resultados.append((metric, None))
        if identidade:
            for metric in expected_entries_metrics(mapeamento_primeira, contrato, identidade, etapa="primeira_tentativa"):
                resultados.append((metric, None))
    if mapeamento_final or ausencias_final:
        for metric in structural_metrics(mapeamento_final, contrato, unmapped=ausencias_final, etapa="final"):
            metric.metadata["candidato_valido"] = candidato_valido
            resultados.append((metric, None))
        if identidade:
            for metric in expected_entries_metrics(mapeamento_final, contrato, identidade, etapa="final"):
                metric.metadata["candidato_valido"] = candidato_valido
                resultados.append((metric, None))
        if gabarito:
            for metric in anchoring_metrics(mapeamento_final, gabarito, unmapped=ausencias_final, etapa="final"):
                metric.metadata["candidato_valido"] = candidato_valido
                resultados.append((metric, None))
    return resultados


def _identidade_do_gabarito(gabarito: dict[str, Any] | None) -> dict[str, str]:
    """Identidade que o pipeline teria: slug operacional e periodo publicado."""
    if not gabarito:
        return {}
    identidade: dict[str, str] = {"entidade": str(gabarito.get("entidade", "")).strip()}
    declarada = gabarito.get("identidade") or {}
    if isinstance(declarada, dict):
        if str(declarada.get("entidade", "")).strip():
            identidade["entidade_nome"] = str(declarada["entidade"]).strip()
        if str(declarada.get("periodo", "")).strip():
            identidade["periodo"] = str(declarada["periodo"]).strip()
    return identidade if identidade["entidade"] else {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--release", required=True)
    parser.add_argument("--sem-scores", action="store_true", help="Nao grava scores no Langfuse; so o relatorio local.")
    parser.add_argument("--contrato", action="append", default=[], help="Override dominio=caminho do contrato a usar na avaliacao.")
    args = parser.parse_args()

    client = Langfuse()
    contratos = carregar_contratos(args.contrato)
    gabaritos = carregar_gabaritos()
    traces = client.traces(args.release)
    if not traces:
        print(f"release '{args.release}' sem traces atlas.fallback.")
        return 1

    relatorio: dict[str, Any] = {"release": args.release, "traces": {}, "medias": {}}
    acumulado: dict[str, list[float]] = defaultdict(list)
    gravados = 0
    for trace in traces:
        observations = client.observations(str(trace["id"]))
        resultados = avaliar_trace(trace, observations, contratos=contratos, gabaritos=gabaritos)
        entidade = str((trace.get("metadata") or {}).get("entidade") or trace["id"])
        por_trace: dict[str, Any] = {}
        for metric, observation_id in resultados:
            chave = f"{metric.name}@{metric.metadata.get('etapa', 'final')}"
            por_trace[chave] = metric.value
            if isinstance(metric.value, (int, float)) and not isinstance(metric.value, bool):
                acumulado[chave].append(float(metric.value))
            elif isinstance(metric.value, bool):
                acumulado[chave].append(1.0 if metric.value else 0.0)
            if not args.sem_scores:
                client.score(str(trace["id"]), metric, observation_id=observation_id)
                gravados += 1
        relatorio["traces"][entidade] = por_trace
        print(f"{entidade:<14} {len(resultados):>3} metricas")

    relatorio["medias"] = {
        chave: {"media": sum(valores) / len(valores), "minimo": min(valores), "n": len(valores)}
        for chave, valores in sorted(acumulado.items())
    }
    RELATORIOS.mkdir(parents=True, exist_ok=True)
    destino = RELATORIOS / f"{args.release}.json"
    destino.write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    largura = max(len(k) for k in relatorio["medias"]) if relatorio["medias"] else 40
    print(f"{'metrica@etapa':<{largura}}  {'media':>8}  {'min':>8}  n")
    for chave, agg in relatorio["medias"].items():
        print(f"{chave:<{largura}}  {agg['media']:>8.3f}  {agg['minimo']:>8.3f}  {agg['n']}")
    print(f"\nrelatorio: {destino}  |  scores gravados: {gravados}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

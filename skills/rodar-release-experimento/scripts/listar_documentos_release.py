#!/usr/bin/env python3
"""Recupera o conjunto exato de documentos de uma release do Atlas.

Le os traces `atlas.fallback` de uma release no Langfuse e, para cada um,
busca no Airflow o `dag_run.conf` que o produziu. O resultado e o lote que
deve ser reenviado a DAG 3 em uma nova release: mesmo `document_id`, mesma
`execution_id` da extracao (DAG 1) e mesmo `manifest_key`. E isso que permite
ao `scripts/comparar_releases_langfuse.py` parear execucao por execucao.

Uso:

    python skills/rodar-release-experimento/scripts/listar_documentos_release.py \
        --release exp-prereq-fase0 --saida /tmp/lote.json

Por padrao so entram os traces cujo `fallback_execution_id` segue o padrao do
lote (`dag_valida_e_fallback_llm__<release>__<dominio>__<entidade>`); runs
manuais que carregaram o rotulo por engano ficam de fora e sao listados como
aviso. Use `--incluir-manuais` para aceita-los.
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
from pathlib import Path
from typing import Any

DAG_ID = "dag_valida_e_fallback_llm"


def carregar_dotenv() -> Path:
    """Carrega o `.env` da raiz do repositorio sem sobrescrever o ambiente."""
    for candidato in [Path.cwd(), *Path(__file__).resolve().parents]:
        env = candidato / ".env"
        if env.is_file():
            for linha in env.read_text().splitlines():
                linha = linha.strip()
                if not linha or linha.startswith("#") or "=" not in linha:
                    continue
                chave, valor = linha.split("=", 1)
                os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))
            return candidato
    raise SystemExit("Nao encontrei um .env a partir do diretorio atual.")


class Langfuse:
    def __init__(self) -> None:
        self.base = os.environ["LANGFUSE_BASE_URL"].rstrip("/")
        raw = f"{os.environ['LANGFUSE_PUBLIC_KEY']}:{os.environ['LANGFUSE_SECRET_KEY']}"
        self.auth = base64.b64encode(raw.encode()).decode()

    def get(self, path: str, **query: Any) -> dict[str, Any]:
        url = f"{self.base}{path}?{urllib.parse.urlencode(query)}"
        request = urllib.request.Request(url, headers={"Authorization": f"Basic {self.auth}"})
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode() or "{}")

    def traces_fallback(self, release: str) -> list[dict[str, Any]]:
        traces: list[dict[str, Any]] = []
        page = 1
        while True:
            data = self.get(
                "/api/public/traces", name="atlas.fallback", release=release, limit=100, page=page
            )
            traces.extend(data.get("data", []))
            if page >= int(data.get("meta", {}).get("totalPages", 1)):
                return traces
            page += 1


class Airflow:
    def __init__(self) -> None:
        porta = os.environ.get("AIRFLOW_PORT", "18080")
        self.base = os.environ.get("AIRFLOW_LOCAL_URL", f"http://localhost:{porta}").rstrip("/")
        corpo = json.dumps(
            {
                "username": os.environ.get("AIRFLOW_ADMIN_USER", "admin"),
                "password": os.environ.get("AIRFLOW_ADMIN_PASSWORD", "admin"),
            }
        ).encode()
        request = urllib.request.Request(
            f"{self.base}/auth/token", data=corpo, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            self.token = json.loads(response.read().decode())["access_token"]

    def dag_run(self, run_id: str) -> dict[str, Any] | None:
        url = f"{self.base}/api/v2/dags/{DAG_ID}/dagRuns/{urllib.parse.quote(run_id, safe='')}"
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--release", required=True, help="Release-base cujo lote sera recuperado.")
    parser.add_argument("--saida", help="Arquivo JSON de saida (padrao: stdout).")
    parser.add_argument(
        "--incluir-manuais",
        action="store_true",
        help="Aceita traces cujo run_id nao segue o padrao <release>__<dominio>__<entidade>.",
    )
    args = parser.parse_args()

    carregar_dotenv()
    langfuse = Langfuse()
    airflow = Airflow()

    traces = langfuse.traces_fallback(args.release)
    if not traces:
        print(f"Nenhum trace atlas.fallback com release '{args.release}'.", file=sys.stderr)
        return 1

    lote: list[dict[str, Any]] = []
    vistos: set[tuple[str, str]] = set()
    avisos: list[str] = []
    for trace in sorted(traces, key=lambda t: t.get("timestamp", "")):
        meta = trace.get("metadata") or {}
        dominio = str(meta.get("dominio") or "")
        entidade = str(meta.get("entidade") or trace.get("userId") or "")
        document_id = str(meta.get("document_id") or trace.get("sessionId") or "")
        execution_id = str(meta.get("execution_id") or "")
        fallback_execution_id = str(meta.get("fallback_execution_id") or "")
        run_id_esperado = f"{args.release}__{dominio}__{entidade}"
        do_lote = fallback_execution_id == f"{DAG_ID}__{run_id_esperado}"
        if not do_lote and not args.incluir_manuais:
            avisos.append(
                f"ignorado (fora do padrao do lote): {entidade} {document_id} "
                f"execucao={execution_id} fallback={fallback_execution_id}"
            )
            continue
        chave = (document_id, execution_id)
        if chave in vistos:
            continue
        vistos.add(chave)

        run_id = run_id_esperado if do_lote else fallback_execution_id.removeprefix(f"{DAG_ID}__")
        dag_run = airflow.dag_run(run_id)
        conf = (dag_run or {}).get("conf") or {}
        manifest_key = str(conf.get("manifest_key") or "")
        if not manifest_key:
            avisos.append(
                f"SEM manifest_key no Airflow para run_id={run_id} ({entidade}); "
                "procure o manifesto em execucoes/<dominio>/extracao/<entidade>/.../manifesto_execucao.json"
            )
        lote.append(
            {
                "dominio": dominio or str(conf.get("domain") or ""),
                "entidade": entidade,
                "document_id": document_id,
                "execution_id": execution_id or str(conf.get("execution_id") or ""),
                "manifest_key": manifest_key,
                "run_id_origem": run_id,
                "trace_id_origem": trace.get("id"),
                "timestamp_origem": trace.get("timestamp"),
            }
        )

    saida = {
        "release_base": args.release,
        "dag_id": DAG_ID,
        "total": len(lote),
        "documentos": lote,
    }
    texto = json.dumps(saida, indent=2, ensure_ascii=False)
    if args.saida:
        Path(args.saida).write_text(texto + "\n")
        print(f"{len(lote)} documento(s) gravado(s) em {args.saida}")
    else:
        print(texto)

    for aviso in avisos:
        print(f"aviso: {aviso}", file=sys.stderr)
    for doc in lote:
        print(
            f"  {doc['entidade']:<12} {doc['dominio']:<12} {doc['document_id']}  {doc['execution_id']}",
            file=sys.stderr,
        )
    faltando = [d["entidade"] for d in lote if not d["manifest_key"]]
    if faltando:
        print(f"ATENCAO: sem manifest_key: {', '.join(faltando)}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Dispara o lote de documentos diretamente na DAG 3 sob uma nova release.

Cada documento vai para `dag_valida_e_fallback_llm` em criacao inicial
forcada (`fallback_mode=criacao_inicial_layout`), sem passar pela DAG 2. E
isso que evita o atalho em que a DAG 2 encontra o layout signature ja
publicado em `layouts/<dominio>/<entidade>/current.json`, declara
`compativel` e nunca aciona o fallback que se quer medir.

Uso:

    python skills/rodar-release-experimento/scripts/disparar_lote_dag3.py \
        --release exp-minha-hipotese --lote /tmp/lote.json --dry-run
    python skills/rodar-release-experimento/scripts/disparar_lote_dag3.py \
        --release exp-minha-hipotese --lote /tmp/lote.json

Antes de disparar, o script confere que o container `airflow-scheduler`
carrega `ATLAS_RELEASE` igual a `--release` (a variavel e lida do ambiente do
container e memoizada; exportar na shell nao tem efeito) e que nenhum run com
o mesmo `run_id` ja existe.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

DAG_ID = "dag_valida_e_fallback_llm"
CAMPOS_LOTE = ("dominio", "entidade", "document_id", "execution_id", "manifest_key")


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
        self.headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def dag_run(self, run_id: str) -> dict[str, Any] | None:
        url = f"{self.base}/api/v2/dags/{DAG_ID}/dagRuns/{urllib.parse.quote(run_id, safe='')}"
        request = urllib.request.Request(url, headers=self.headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise

    def trigger(self, run_id: str, conf: dict[str, str]) -> dict[str, Any]:
        # `logical_date: null` e obrigatorio na API v2 do Airflow 3; sem ele a
        # chamada devolve 422 e nada e criado.
        corpo = json.dumps({"dag_run_id": run_id, "logical_date": None, "conf": conf}).encode()
        request = urllib.request.Request(
            f"{self.base}/api/v2/dags/{DAG_ID}/dagRuns",
            data=corpo,
            headers=self.headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())


def release_no_container(raiz: Path, servico: str) -> str | None:
    try:
        saida = subprocess.run(
            ["docker", "compose", "exec", "-T", servico, "bash", "-lc", 'echo "$ATLAS_RELEASE"'],
            cwd=raiz,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if saida.returncode != 0:
        return None
    return saida.stdout.strip()


def caffeinate_ativo() -> bool:
    saida = subprocess.run(["pgrep", "-x", "caffeinate"], capture_output=True, text=True, check=False)
    return saida.returncode == 0


def montar_conf(doc: dict[str, str], release: str, motivo: str) -> dict[str, str]:
    # Mesmas chaves dos lotes anteriores (baseline0, exp-prereq-fase0, ...).
    # `contrato_semantico_uri` fica de fora de proposito: a DAG 3 usa sempre o
    # contrato mais novo do dominio, ignorando o registrado no manifesto.
    return {
        "domain": doc["dominio"],
        "entity_slug": doc["entidade"],
        "document_id": doc["document_id"],
        "execution_id": doc["execution_id"],
        "manifest_key": doc["manifest_key"],
        "fallback_mode": "criacao_inicial_layout",
        "trigger_origin_dag": f"manual_{release}",
        "motivo": motivo or f"{release}_medicao",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--release", required=True, help="Rotulo da nova release (ATLAS_RELEASE).")
    parser.add_argument("--lote", required=True, help="JSON gerado por listar_documentos_release.py.")
    parser.add_argument("--motivo", default="", help="Texto livre gravado em conf.motivo.")
    parser.add_argument("--dry-run", action="store_true", help="Mostra os payloads sem disparar.")
    parser.add_argument(
        "--ignorar-release-container",
        action="store_true",
        help="Nao aborta se ATLAS_RELEASE do scheduler for diferente de --release.",
    )
    parser.add_argument("--intervalo", type=float, default=1.0, help="Segundos entre disparos.")
    parser.add_argument(
        "--entidade",
        action="append",
        default=[],
        help="Dispara so estas entidades do lote (repetivel). Padrao: todas.",
    )
    parser.add_argument(
        "--sufixo",
        default="",
        help="Sufixo do run_id para redisparo de um documento (ex.: __r2). O rotulo da release nao muda.",
    )
    args = parser.parse_args()

    raiz = carregar_dotenv()
    lote = json.loads(Path(args.lote).read_text())
    documentos: list[dict[str, str]] = lote.get("documentos", lote if isinstance(lote, list) else [])
    if args.entidade:
        documentos = [d for d in documentos if d.get("entidade") in set(args.entidade)]
    if not documentos:
        print("Lote vazio (ou nenhuma entidade do filtro esta no lote).", file=sys.stderr)
        return 1
    for doc in documentos:
        faltando = [c for c in CAMPOS_LOTE if not str(doc.get(c, "")).strip()]
        if faltando:
            print(f"documento incompleto ({doc.get('entidade')}): faltam {faltando}", file=sys.stderr)
            return 1

    release_scheduler = release_no_container(raiz, "airflow-scheduler")
    print(f"ATLAS_RELEASE no airflow-scheduler: {release_scheduler!r} (esperado {args.release!r})")
    if release_scheduler != args.release and not args.ignorar_release_container:
        print(
            "Abortado: recrie os servicos com "
            f"ATLAS_RELEASE={args.release} docker compose up -d airflow-scheduler airflow-webserver "
            "airflow-triggerer airflow-dag-processor (ou ajuste o .env e recrie).",
            file=sys.stderr,
        )
        return 1
    if not caffeinate_ativo():
        print(
            "aviso: caffeinate nao esta rodando; o sleep do host mata as tasks. "
            "Rode: nohup caffeinate -i -t 14400 >/dev/null 2>&1 &",
            file=sys.stderr,
        )

    airflow = Airflow()
    resultados: list[tuple[str, str]] = []
    for doc in documentos:
        run_id = f"{args.release}__{doc['dominio']}__{doc['entidade']}{args.sufixo}"
        conf = montar_conf(doc, args.release, args.motivo)
        if args.dry_run:
            print(json.dumps({"dag_run_id": run_id, "logical_date": None, "conf": conf}, indent=2, ensure_ascii=False))
            continue
        if airflow.dag_run(run_id):
            print(f"pulado (run_id ja existe): {run_id}")
            resultados.append((run_id, "ja_existia"))
            continue
        try:
            criado = airflow.trigger(run_id, conf)
            resultados.append((run_id, criado.get("state", "?")))
            print(f"OK  {run_id} -> {criado.get('state')}")
        except urllib.error.HTTPError as exc:
            corpo = exc.read().decode()[:300]
            resultados.append((run_id, f"erro {exc.code}"))
            print(f"ERR {run_id} -> {exc.code} {corpo}", file=sys.stderr)
        time.sleep(args.intervalo)

    if args.dry_run:
        print(f"\n{len(documentos)} payload(s); nada foi disparado.")
        return 0
    erros = [r for r in resultados if r[1].startswith("erro")]
    print(f"\n{len(resultados) - len(erros)}/{len(documentos)} run(s) aceito(s). A DAG 3 tem max_active_runs=1: os runs executam em fila.")
    print(f"Acompanhe em {airflow.base}/dags/{DAG_ID}/runs ou pelos traces `atlas.fallback` com release={args.release}.")
    return 1 if erros else 0


if __name__ == "__main__":
    raise SystemExit(main())

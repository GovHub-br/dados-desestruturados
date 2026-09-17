#!/usr/bin/env python3
"""Sincroniza os contratos semanticos entre o repositorio e o Langfuse.

O MinIO (via bootstrap.sh) continua sendo a fonte operacional: e o que as DAGs
leem em producao. Este script publica, alem disso, um espelho navegavel de
cada versao no Langfuse, para que o historico de um contrato viva na mesma
ferramenta onde ja vivem os prompts do fallback e as metricas do harness ---
ate agora so estes dois ultimos estavam la.

Um Langfuse text prompt por dominio (``atlas/contratos/<dominio>``); cada
versao local em ``infra/minio-bootstrap/contracts/<dominio>/<versao>/`` vira
uma versao desse prompt, rotulada com a propria versao semantica do contrato
(``v1.9.0``, nao ``latest``/``production``: varias versoes coexistem por
design, elas nao substituem umas as outras). O Langfuse marca sozinho a
versao mais recente de cada nome com o rotulo automatico ``latest`` --- nao
precisamos gerenciar isso aqui, so publicar em ordem crescente de versao.

    --verificar  lista o que esta publicado vs. o que existe localmente, sem escrever
    --publicar   publica as versoes ausentes ou divergentes (--dry-run so mostra)

Uso:

    python scripts/sincronizar_contratos_langfuse.py --verificar
    python scripts/sincronizar_contratos_langfuse.py --publicar --dry-run
    python scripts/sincronizar_contratos_langfuse.py --publicar
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import pathlib
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

RAIZ = pathlib.Path(__file__).resolve().parent.parent
CONTRATOS = RAIZ / "infra" / "minio-bootstrap" / "contracts"


class LangfusePrompts:
    """Leitura e escrita de prompts pela API publica (mesmo cliente de sincronizar_prompts_langfuse.py)."""

    def __init__(self) -> None:
        self.base = os.environ["LANGFUSE_BASE_URL"].rstrip("/")
        raw = f"{os.environ['LANGFUSE_PUBLIC_KEY']}:{os.environ['LANGFUSE_SECRET_KEY']}"
        self.auth = base64.b64encode(raw.encode()).decode()

    def publicado(self, nome: str, *, label: str) -> dict[str, Any] | None:
        url = (
            f"{self.base}/api/public/v2/prompts/{urllib.parse.quote(nome, safe='')}"
            f"?label={urllib.parse.quote(label)}"
        )
        request = urllib.request.Request(url, headers={"Authorization": f"Basic {self.auth}"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode() or "{}")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise

    def criar(self, corpo: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base}/api/public/v2/prompts",
            data=json.dumps(corpo).encode(),
            method="POST",
            headers={
                "Authorization": f"Basic {self.auth}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode() or "{}")


def nome_prompt(dominio: str) -> str:
    return f"atlas/contratos/{dominio}"


def versoes_locais(dominio_dir: pathlib.Path) -> list[tuple[str, pathlib.Path]]:
    """[(versao, arquivo_json)] do dominio, do mais antigo para o mais novo."""
    versoes: list[tuple[str, pathlib.Path]] = []
    for pasta in dominio_dir.iterdir():
        if not pasta.is_dir() or not pasta.name.startswith("v"):
            continue
        arquivos = sorted(pasta.glob("*.json"))
        if not arquivos:
            continue
        versoes.append((pasta.name, arquivos[0]))
    return sorted(versoes, key=lambda item: tuple(int(x) for x in item[0].lstrip("v").split(".")))


def conteudo_canonico(arquivo: pathlib.Path) -> str:
    """Texto a publicar: JSON reformatado de forma estavel, independente da formatacao local."""
    dado = json.loads(arquivo.read_text(encoding="utf-8"))
    return json.dumps(dado, ensure_ascii=False, indent=2)


def comparar(api: LangfusePrompts) -> list[dict[str, Any]]:
    """Estado de cada versao local de cada dominio: ausente, igual ou divergente no Langfuse."""
    estado: list[dict[str, Any]] = []
    if not CONTRATOS.is_dir():
        return estado
    for dominio_dir in sorted(p for p in CONTRATOS.iterdir() if p.is_dir()):
        dominio = dominio_dir.name
        versoes = versoes_locais(dominio_dir)
        if not versoes:
            continue
        mais_recente = versoes[-1][0]
        for versao, arquivo in versoes:
            texto = conteudo_canonico(arquivo)
            publicado = api.publicado(nome_prompt(dominio), label=versao)
            if publicado is None:
                situacao = "ausente"
            else:
                situacao = "igual" if publicado.get("prompt") == texto else "divergente"
            estado.append(
                {
                    "dominio": dominio,
                    "versao": versao,
                    "arquivo": arquivo,
                    "texto": texto,
                    "situacao": situacao,
                    "e_mais_recente": versao == mais_recente,
                    "langfuse_version": publicado.get("version") if publicado else None,
                }
            )
    return estado


def publicar(api: LangfusePrompts, *, dry_run: bool) -> int:
    """Publica, em ordem crescente de versao, o que estiver ausente ou divergente."""
    estado = comparar(api)
    publicados = 0
    for item in estado:
        if item["situacao"] == "igual":
            print(
                f"  igual       {item['dominio']:<12} {item['versao']:<8}"
                f" (Langfuse v{item['langfuse_version']})"
            )
            continue
        if dry_run:
            print(f"  [dry-run] {item['situacao']:<10} {item['dominio']:<12} {item['versao']}")
            continue
        resultado = api.criar(
            {
                "type": "text",
                "name": nome_prompt(item["dominio"]),
                "prompt": item["texto"],
                "labels": [item["versao"]],
                "tags": sorted(
                    {"atlas", "contrato", f"dominio:{item['dominio']}", f"versao:{item['versao']}"}
                ),
                "commitMessage": f"Espelho do repositorio: {item['arquivo'].relative_to(RAIZ)}",
            }
        )
        print(
            f"  publicado   {item['dominio']:<12} {item['versao']:<8}"
            f" -> Langfuse v{resultado.get('version')} (label {item['versao']})"
        )
        publicados += 1
    print(f"\n{publicados} versoes de contrato publicadas." if not dry_run else "\n[dry-run] nada gravado.")
    return 0


def verificar(api: LangfusePrompts) -> int:
    """Relata o que ja esta publicado vs. o que existe localmente, sem escrever."""
    estado = comparar(api)
    if not estado:
        print(f"Nenhum contrato encontrado em {CONTRATOS}.")
        return 1
    contagem = {"igual": 0, "divergente": 0, "ausente": 0}
    for item in estado:
        contagem[item["situacao"]] += 1
        marca = {"igual": "  ", "divergente": "~ ", "ausente": "! "}[item["situacao"]]
        latest = "  (mais recente local)" if item["e_mais_recente"] else ""
        print(f"{marca}{item['dominio']:<12} {item['versao']:<8}{latest}")
    print(
        f"\n{contagem['igual']} iguais, {contagem['divergente']} divergentes, "
        f"{contagem['ausente']} ausentes no Langfuse."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--publicar", action="store_true")
    grupo.add_argument("--verificar", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    api = LangfusePrompts()
    if args.publicar:
        return publicar(api, dry_run=args.dry_run)
    return verificar(api)


if __name__ == "__main__":
    raise SystemExit(main())

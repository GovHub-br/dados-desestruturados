#!/usr/bin/env python3
"""Sincroniza os prompts do fallback entre o repositorio e o Langfuse.

O Langfuse e o ponto de controle do conteudo: quem edita um bloco pela interface
muda o texto da proxima execucao. O repositorio guarda um espelho, que serve de
queda quando o Langfuse nao responde. Este script mantem os dois coerentes.

    --empurrar   publica o espelho do codigo como nova versao dos blocos que
                 divergem, e (re)publica os conjuntos que os agrupam
    --verificar  lista as divergencias sem escrever nada
    --puxar      salva os textos publicados em arquivos e mostra o diff, para a
                 atualizacao do espelho ser uma decisao revisada

Divergencia nao e erro: depois que alguem edita um bloco pela interface, o
esperado e justamente que o Langfuse esteja a frente do repositorio ate o espelho
ser atualizado.

Uso:

    python scripts/sincronizar_prompts_langfuse.py --verificar
    python scripts/sincronizar_prompts_langfuse.py --empurrar
    python scripts/sincronizar_prompts_langfuse.py --puxar --saida build/prompts
"""

from __future__ import annotations

import argparse
import base64
import difflib
import json
import os
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from document_processing.application.use_cases.fallback import prompt_sets  # noqa: E402


class LangfusePrompts:
    """Leitura e escrita de prompts pela API publica."""

    def __init__(self) -> None:
        self.base = os.environ["LANGFUSE_BASE_URL"].rstrip("/")
        raw = f"{os.environ['LANGFUSE_PUBLIC_KEY']}:{os.environ['LANGFUSE_SECRET_KEY']}"
        self.auth = base64.b64encode(raw.encode()).decode()

    def publicado(
        self, nome: str, *, label: str, resolver: bool = True
    ) -> dict[str, Any] | None:
        """Versao atualmente marcada com o rotulo, ou None se nao existir.

        `resolver=False` mantem as tags de composicao no lugar. E o que permite
        comparar um conjunto com a declaracao do codigo: resolvido, ele traz o
        texto dos blocos ja embutido e nunca seria igual as referencias.
        """
        url = (
            f"{self.base}/api/public/v2/prompts/{urllib.parse.quote(nome, safe='')}"
            f"?label={urllib.parse.quote(label)}"
            + ("" if resolver else "&resolve=false")
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
        """Cria uma nova versao de prompt."""
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


def referencia(sufixo: str, *, label: str) -> str:
    """Tag de composicao que faz um conjunto referenciar um bloco."""
    return f"@@@langfusePrompt:name={prompt_sets.nome_bloco(sufixo)}|label={label}@@@"


def mensagens_do_conjunto(conjunto: str, *, label: str) -> list[dict[str, str]]:
    """Traduz a sequencia declarada em codigo para um chat prompt do Langfuse.

    Blocos viram referencias, para que o conjunto mostre sempre o texto vigente
    de cada um; dados da execucao viram variaveis.
    """
    mensagens: list[dict[str, str]] = []
    for passo in prompt_sets.SEQUENCIAS[conjunto]:
        if isinstance(passo, prompt_sets._Dado):
            papel = "system" if str(passo) == "instrucao_escopo" else "user"
            mensagens.append({"role": papel, "content": "{{" + str(passo) + "}}"})
        else:
            mensagens.append({"role": "system", "content": referencia(passo, label=label)})
    return mensagens


def conjuntos_do_bloco(sufixo: str) -> list[str]:
    """Conjuntos em que um bloco aparece, pela sequencia ou por variavel."""
    encontrados = [
        conjunto
        for conjunto, sequencia in prompt_sets.SEQUENCIAS.items()
        if sufixo in sequencia
    ]
    encontrados += [
        conjunto
        for conjunto, sufixos in prompt_sets.BLOCOS_POR_VARIAVEL.items()
        if sufixo in sufixos
    ]
    return sorted(set(encontrados))


def comparar(api: LangfusePrompts, *, label: str) -> list[dict[str, Any]]:
    """Estado de cada bloco: ausente, igual ou divergente."""
    estado: list[dict[str, Any]] = []
    for bloco in prompt_sets.BLOCOS:
        espelho = bloco.espelho()
        publicado = api.publicado(bloco.nome, label=label)
        if publicado is None:
            situacao = "ausente"
            texto = None
            versao = None
        else:
            texto = publicado.get("prompt")
            versao = publicado.get("version")
            situacao = "igual" if texto == espelho else "divergente"
        estado.append(
            {
                "bloco": bloco,
                "situacao": situacao,
                "espelho": espelho,
                "publicado": texto,
                "versao": versao,
            }
        )
    return estado


def empurrar(api: LangfusePrompts, *, label: str, dry_run: bool) -> int:
    """Publica os blocos divergentes e republica os conjuntos."""
    estado = comparar(api, label=label)
    publicados = 0
    for item in estado:
        bloco = item["bloco"]
        if item["situacao"] == "igual":
            print(f"  igual       v{item['versao']}  {bloco.sufixo}")
            continue
        if dry_run:
            print(f"  [dry-run] {item['situacao']}  {bloco.sufixo}")
            continue
        resultado = api.criar(
            {
                "type": "text",
                "name": bloco.nome,
                "prompt": item["espelho"],
                "labels": [label],
                "tags": sorted(
                    {"atlas", f"etapa:{bloco.etapa}"}
                    | {f"conjunto:{nome}" for nome in conjuntos_do_bloco(bloco.sufixo)}
                ),
                "commitMessage": f"Espelho do repositorio: {bloco.descricao}",
            }
        )
        print(f"  publicado   v{resultado.get('version')}  {bloco.sufixo}")
        publicados += 1

    for conjunto in prompt_sets.SEQUENCIAS:
        nome = prompt_sets.nome_conjunto(conjunto)
        mensagens = mensagens_do_conjunto(conjunto, label=label)
        atual = api.publicado(nome, label=label, resolver=False)
        if atual is not None and atual.get("prompt") == mensagens:
            print(f"  igual       v{atual.get('version')}  conjunto {conjunto}")
            continue
        if dry_run:
            print(f"  [dry-run] conjunto {conjunto} ({len(mensagens)} mensagens)")
            continue
        resultado = api.criar(
            {
                "type": "chat",
                "name": nome,
                "prompt": mensagens,
                "labels": [label],
                "tags": sorted({"atlas", "conjunto", f"conjunto:{conjunto}"}),
                "commitMessage": "Sequencia de mensagens declarada em prompt_sets.py",
            }
        )
        print(f"  publicado   v{resultado.get('version')}  conjunto {conjunto}")
        publicados += 1

    print(f"\n{publicados} prompts publicados." if not dry_run else "\n[dry-run] nada gravado.")
    return 0


def verificar(api: LangfusePrompts, *, label: str) -> int:
    """Relata divergencias sem escrever. Divergir nao reprova."""
    estado = comparar(api, label=label)
    contagem = {"igual": 0, "divergente": 0, "ausente": 0}
    for item in estado:
        contagem[item["situacao"]] += 1
        marca = {"igual": "  ", "divergente": "~ ", "ausente": "! "}[item["situacao"]]
        versao = f"v{item['versao']}" if item["versao"] else "--"
        print(f"{marca}{versao:>5}  {item['bloco'].sufixo}")
    print(
        f"\n{contagem['igual']} iguais, {contagem['divergente']} divergentes, "
        f"{contagem['ausente']} ausentes no Langfuse."
    )
    if contagem["divergente"]:
        print(
            "\nDivergencia e esperada depois de uma edicao pela interface. "
            "Use --puxar para revisar e atualizar o espelho do repositorio."
        )
    return 0


def puxar(api: LangfusePrompts, *, label: str, saida: pathlib.Path) -> int:
    """Salva o texto publicado dos blocos divergentes e mostra o diff.

    Nao reescreve o codigo automaticamente: o espelho vive em literais Python
    com quebras de linha escolhidas a mao, e reescreve-los por programa e a forma
    mais facil de corromper silenciosamente justamente o texto que se quer
    proteger. O arquivo salvo serve para a atualizacao ser revisada.
    """
    estado = comparar(api, label=label)
    saida.mkdir(parents=True, exist_ok=True)
    divergentes = 0
    for item in estado:
        if item["situacao"] != "divergente":
            continue
        divergentes += 1
        destino = saida / f"{item['bloco'].sufixo}.txt"
        destino.write_text(item["publicado"] or "", encoding="utf-8")
        print(f"\n=== {item['bloco'].sufixo}  (Langfuse v{item['versao']}) -> {destino}")
        for linha in difflib.unified_diff(
            (item["espelho"] or "").split(". "),
            (item["publicado"] or "").split(". "),
            fromfile="espelho no repositorio",
            tofile=f"publicado v{item['versao']}",
            lineterm="",
        ):
            print(f"  {linha}")
    if not divergentes:
        print("Nenhuma divergencia: o espelho ja reflete o que esta publicado.")
    else:
        print(f"\n{divergentes} blocos salvos em {saida}. Atualize o espelho e rode os testes.")
    return 0


def main() -> int:
    """Empurra, verifica ou puxa os prompts do fallback."""
    parser = argparse.ArgumentParser(description=__doc__)
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--empurrar", action="store_true")
    grupo.add_argument("--verificar", action="store_true")
    grupo.add_argument("--puxar", action="store_true")
    parser.add_argument("--label", default=os.getenv("ATLAS_PROMPT_LABEL", "production"))
    parser.add_argument("--saida", type=pathlib.Path, default=pathlib.Path("build/prompts"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    api = LangfusePrompts()
    print(f"rotulo: {args.label}\n")
    if args.empurrar:
        return empurrar(api, label=args.label, dry_run=args.dry_run)
    if args.verificar:
        return verificar(api, label=args.label)
    return puxar(api, label=args.label, saida=args.saida)


if __name__ == "__main__":
    raise SystemExit(main())

"""Compara a extração nova com a antiga, PDF a PDF, e escreve um relatório em Markdown.

Só biblioteca padrão. Lê `extracoes/<antigo>/<slug>/extraction` e `extracoes/<novo>/<slug>/extraction`.

Como as tabelas são pareadas: o número do arquivo (`table005`) muda quando uma tabela é
separada ou fundida, então o pareamento é pelo CONTEÚDO. Primeiro se pareiam as tabelas de
mesmo `schema` e mesmas linhas (inclusive as de 0 linhas). Das que sobram, duas ficam ligadas
quando dividem pelo menos metade das linhas da menor. Cada grupo ligado é classificado:

- idêntica: mesmo `schema` e mesmas linhas, mesmo título
- só título: mesmas linhas e `schema`, `name` diferente
- cabeçalho mudou: mesmas linhas, `schema` diferente
- conteúdo mudou: 1 para 1 com linhas diferentes
- separada em N / fundida de N: 1 antiga para N novas, ou o contrário
- sumiu / nova: tabela sem par do outro lado

Para cada grupo que mudou há uma PROVA DE PARTIÇÃO dos dados: toda linha de dados do antes
precisa existir no agora (como dado ou, se era o cabeçalho verdadeiro que estava como linha,
como cabeçalho), e toda linha de dados do agora precisa existir no antes. Se isso vale, a
mudança só redistribuiu linhas e cabeçalhos entre tabelas. Linhas que sobram são listadas
como "ATENÇÃO" para conferência no PDF. Cabeçalhos recuperados ou removidos são contados à parte.

O relatório NÃO diz se a mudança é melhor ou pior: isso é julgado abrindo o PDF. Ele mostra
onde olhar, com título, cabeçalho e linhas de cada lado.

Uso: python comparar_extracoes.py [--antigo antigo] [--novo novo] [--saida arquivo.md] [--filtro texto]
O relatório vai para extracoes/ (fora do git); copie para resultados/<data>-<id>/ o que valer registrar.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1] / "extracoes"


def _tabelas(extraction: Path) -> list[dict]:
    achadas = []
    for caminho in sorted((extraction / "tables").glob("table*.json")):
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        linhas = [tuple(str(c).strip() for c in linha) for linha in dados.get("rows", [])]
        achadas.append(
            {
                "arquivo": caminho.name,
                "titulo": dados.get("name") or "",
                "schema": [str(c) for c in dados.get("schema", [])],
                "linhas": linhas,
                "chaves": set(linhas),
            }
        )
    return achadas


def _contar_linhas(caminho: Path) -> int | None:
    if not caminho.exists():
        return None
    return sum(1 for linha in caminho.read_text(encoding="utf-8").splitlines() if linha.strip())


def _contar_graficos(extraction: Path) -> int:
    return len(list((extraction / "charts").glob("chart*.json"))) if (extraction / "charts").exists() else 0


def _grupos(antigas: list[dict], novas: list[dict]) -> list[tuple[list[dict], list[dict]]]:
    """Pares exatos primeiro; nas que sobram, componentes conexos (aresta = divide >= metade das linhas da menor)."""
    pares: list[tuple[list[dict], list[dict]]] = []
    livres_novas = list(novas)
    antigas_restantes = []
    for a in antigas:
        achada = next((n for n in livres_novas if n["linhas"] == a["linhas"] and n["schema"] == a["schema"]), None)
        if achada is None:
            antigas_restantes.append(a)
        else:
            livres_novas.remove(achada)
            pares.append(([a], [achada]))
    antigas, novas = antigas_restantes, livres_novas
    nos = [("a", i) for i in range(len(antigas))] + [("n", i) for i in range(len(novas))]
    pai = {no: no for no in nos}

    def achar(no):
        while pai[no] != no:
            pai[no] = pai[pai[no]]
            no = pai[no]
        return no

    for i, a in enumerate(antigas):
        for j, n in enumerate(novas):
            comum = len(a["chaves"] & n["chaves"])
            menor = min(len(a["chaves"]), len(n["chaves"]))
            if comum and menor and comum / menor >= 0.5:
                pai[achar(("a", i))] = achar(("n", j))
    por_raiz: dict = {}
    for no in nos:
        por_raiz.setdefault(achar(no), []).append(no)
    grupos = []
    for membros in por_raiz.values():
        a = sorted((antigas[i] for t, i in membros if t == "a"), key=lambda x: x["arquivo"])
        n = sorted((novas[i] for t, i in membros if t == "n"), key=lambda x: x["arquivo"])
        grupos.append((a, n))
    grupos += pares
    return sorted(grupos, key=lambda g: (g[0] or g[1])[0]["arquivo"] if (g[0] or g[1]) else "")


def _classificar(a: list[dict], n: list[dict]) -> str:
    if a and not n:
        return "sumiu"
    if n and not a:
        return "nova"
    if len(a) == 1 and len(n) == 1:
        x, y = a[0], n[0]
        if x["linhas"] == y["linhas"] and x["schema"] == y["schema"]:
            return "idêntica" if x["titulo"] == y["titulo"] else "só título"
        if x["linhas"] == y["linhas"]:
            return "cabeçalho mudou"
        return "conteúdo mudou"
    if len(a) == 1:
        return f"separada em {len(n)}"
    if len(n) == 1:
        return f"fundida de {len(a)}"
    return f"reorganizada ({len(a)} → {len(n)})"


def _particao(a: list[dict], n: list[dict]) -> dict:
    """Prova de partição, separando linhas de DADOS de linhas de CABEÇALHO.

    - perdidas: linha de dados do antes que não existe em lugar nenhum do agora (nem como
      dado nem como cabeçalho). Uma linha de dados do antes que virou cabeçalho (o cabeçalho
      verdadeiro estava como linha) NÃO conta como perda.
    - inventadas: linha de dados do agora que não existe no antes (nem como dado nem como
      cabeçalho).
    - cabecalhos_recuperados: cabeçalho do agora que não existia no antes.
    - cabecalhos_removidos: cabeçalho do antes que não existe mais no agora.
    """
    dados_a = Counter(l for t in a for l in t["linhas"])
    dados_n = Counter(l for t in n for l in t["linhas"])
    cab_a = Counter(tuple(t["schema"]) for t in a)
    cab_n = Counter(tuple(t["schema"]) for t in n)
    perdidas = list(((dados_a - dados_n) - cab_n).elements())
    inventadas = list(((dados_n - dados_a) - cab_a).elements())
    recuperados = list(((cab_n - cab_a) - dados_a).elements())
    removidos = list(((cab_a - cab_n) - dados_n).elements())
    return {
        "dados_ok": not perdidas and not inventadas,
        "perdidas": perdidas,
        "inventadas": inventadas,
        "cab_recuperados": recuperados,
        "cab_removidos": removidos,
    }


def _descrever(t: dict) -> str:
    cab = " | ".join(t["schema"][:4]) + (" …" if len(t["schema"]) > 4 else "")
    return f"`{t['arquivo']}` título **{t['titulo']!r}**, {len(t['linhas'])} linhas, cabeçalho: {cab}"


def comparar(antigo: Path, novo: Path) -> dict:
    a, n = _tabelas(antigo), _tabelas(novo)
    grupos = [(ga, gn, _classificar(ga, gn)) for ga, gn in _grupos(a, n)]
    outros = {}
    for nome in ("sections/sections.jsonl", "blocks/blocks.jsonl", "metrics/metrics.jsonl",
                 "cases/cases.jsonl", "text_candidates/text_candidates.jsonl"):
        outros[nome] = (_contar_linhas(antigo / nome), _contar_linhas(novo / nome))
    outros["charts/ (quantidade)"] = (_contar_graficos(antigo), _contar_graficos(novo))
    return {"n_antigas": len(a), "n_novas": len(n), "grupos": grupos, "outros": outros}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--antigo", default="antigo")
    p.add_argument("--novo", default="novo")
    p.add_argument("--saida", default="", help="padrão: extracoes/comparacao_<antigo>_vs_<novo>.md (fora do git)")
    p.add_argument("--filtro", default="")
    args = p.parse_args()
    if not args.saida:
        args.saida = str(RAIZ / f"comparacao_{args.antigo}_vs_{args.novo}.md")

    def _concluido(pasta: Path) -> bool:
        meta = pasta / "meta.json"
        return meta.exists() and json.loads(meta.read_text(encoding="utf-8")).get("status") == "success"

    slugs = sorted(
        s.name for s in (RAIZ / args.novo).iterdir()
        if s.is_dir() and _concluido(s) and (RAIZ / args.antigo / s.name / "extraction").is_dir() and args.filtro in s.name
    )
    resumos, detalhes = [], []
    for slug in slugs:
        r = comparar(RAIZ / args.antigo / slug / "extraction", RAIZ / args.novo / slug / "extraction")
        cont: dict[str, int] = {}
        for _, _, cls in r["grupos"]:
            cont[cls] = cont.get(cls, 0) + 1
        mudancas = {k: v for k, v in cont.items() if k != "idêntica"}
        dif_outros = {k: v for k, v in r["outros"].items() if v[0] != v[1]}
        resumos.append(
            f"| {slug} | {r['n_antigas']} → {r['n_novas']} | {cont.get('idêntica', 0)} | "
            f"{', '.join(f'{k}: {v}' for k, v in mudancas.items()) or '—'} | "
            f"{', '.join(k.split()[0] + ' ' + str(v[0]) + '→' + str(v[1]) for k, v in dif_outros.items()) or '—'} |"
        )
        linhas = [f"\n### {slug}\n"]
        for ga, gn, cls in r["grupos"]:
            if cls == "idêntica":
                continue
            linhas.append(f"- **{cls}**")
            for t in ga:
                linhas.append(f"  - antes: {_descrever(t)}")
            for t in gn:
                linhas.append(f"  - agora: {_descrever(t)}")
            if cls != "só título":
                pr = _particao(ga, gn)
                if pr["dados_ok"]:
                    linhas.append(
                        "  - dados: **preservados** (nenhuma linha de dados perdida nem inventada); "
                        f"cabeçalhos recuperados: {len(pr['cab_recuperados'])}, removidos: {len(pr['cab_removidos'])}"
                    )
                else:
                    linhas.append(
                        f"  - dados: **ATENÇÃO**, {len(pr['perdidas'])} linha(s) de dados perdida(s) e "
                        f"{len(pr['inventadas'])} inventada(s)"
                    )
                    for linha in pr["perdidas"][:4]:
                        linhas.append(f"    - perdida: {' | '.join(linha)[:160]}")
                    for linha in pr["inventadas"][:4]:
                        linhas.append(f"    - inventada: {' | '.join(linha)[:160]}")
        if len(linhas) == 1:
            linhas.append("Nenhuma tabela mudou.")
        detalhes.append("\n".join(linhas))

    saida = [
        "# Comparação das extrações: antigo × novo\n",
        f"Gerado por `scripts/comparar_extracoes.py` ({args.antigo} × {args.novo}). "
        "Este relatório mostra **onde** as extrações diferem; se a diferença é melhor ou pior é "
        "decidido abrindo o PDF.\n",
        "| PDF | Tabelas | Idênticas | Mudanças | Outros artefatos que mudaram |",
        "| --- | --- | --- | --- | --- |",
        *resumos,
        "\n## Detalhe das tabelas que mudaram",
        *detalhes,
    ]
    Path(args.saida).write_text("\n".join(saida) + "\n", encoding="utf-8")
    print(f"{len(slugs)} PDF(s) comparados -> {args.saida}")


if __name__ == "__main__":
    main()

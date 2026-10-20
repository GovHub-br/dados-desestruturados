"""Procura tabelas perdidas ou não identificadas, comparando o PDF com a extração.

Só biblioteca padrão e o binário `pdftotext`. Para cada página do PDF, pega os números "de
dado" da camada de texto (com separador de milhar ou vírgula decimal, ex.: 1.351.937,
(15.041.444), 12,3%) e classifica cada um pelo que a extração entregou naquela página:

- tabela: o número está em alguma tabela da página (tolerância de 3 páginas para trás, porque
  a tabela pode ter sido fundida entre páginas e só guarda a página inicial);
- texto: está só em bloco/candidato de texto/métrica/caso da página (a tabela não foi
  identificada como tabela, ou é número de prosa);
- gráfico: está só em gráfico da página;
- outra página: não está na página, mas aparece em outro lugar da extração;
- ausente: não aparece em lugar nenhum da extração (dado perdido).

Uma página é sinalizada quando tem muitos números e boa parte deles não está em tabela.
O relatório mostra ONDE olhar; confirmar no PDF decide se havia tabela de fato (páginas com
muita prosa numérica ou gráficos geram falsos alertas).

Uso: python analisar_cobertura.py [--rotulo novo] [--saida arquivo.md] [--filtro texto]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1] / "extracoes"
NUMERO = re.compile(r"(?<![\d.,])(?:\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+,\d+)(?![\d]|[.,]\d)")
TOLERANCIA_TABELA = 3
MIN_NUMEROS = 15
MIN_FORA_DE_TABELA = 10


def _digitos(valor: str) -> str:
    """Valor de gráfico sem separadores e sem o `.0` do float: '1.062' e 1062.0 viram '1062'."""
    valor = re.sub(r"\.0$", "", valor.strip())
    return re.sub(r"[^\d]", "", valor)


def numeros(texto: str) -> set[str]:
    return set(NUMERO.findall(texto))


def paginas_do_pdf(pdf: Path) -> list[set[str]]:
    saida = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True, check=True).stdout
    paginas = saida.split("\f")
    if paginas and not paginas[-1].strip():
        paginas = paginas[:-1]
    return [numeros(p) for p in paginas]


def _jsonl(caminho: Path) -> list[dict]:
    if not caminho.exists():
        return []
    registros = []
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        if linha.strip():
            try:
                registros.append(json.loads(linha))
            except json.JSONDecodeError:
                continue
    return registros


def extracao_por_pagina(extraction: Path) -> dict:
    """Números da extração: tabelas (página inicial), texto e gráficos (por página)."""
    tabelas: dict[int, set[str]] = {}
    for meta in sorted((extraction / "tables").glob("table*/metadata.json")):
        pagina = json.loads(meta.read_text(encoding="utf-8")).get("page_number") or 0
        dados = json.loads(meta.parent.with_suffix(".json").read_text(encoding="utf-8"))
        # o cabeçalho conta: o Docling às vezes absorve a primeira linha de dados como `schema`
        texto = " ".join(str(c) for c in dados.get("schema", [])) + " " + " ".join(
            str(c) for linha in dados.get("rows", []) for c in linha
        )
        tabelas.setdefault(pagina, set()).update(numeros(texto))
    texto_por_pagina: dict[int, set[str]] = {}
    for nome in ("blocks/blocks.jsonl", "text_candidates/text_candidates.jsonl", "metrics/metrics.jsonl", "cases/cases.jsonl"):
        for reg in _jsonl(extraction / nome):
            texto_por_pagina.setdefault(reg.get("page_number") or 0, set()).update(
                numeros(json.dumps(reg, ensure_ascii=False))
            )
    graficos: dict[int, set[str]] = {}
    for pasta in sorted((extraction / "charts").glob("chart*/")):
        meta = pasta / "metadata.json"
        if not meta.exists():
            continue
        pagina = json.loads(meta.read_text(encoding="utf-8")).get("page_number") or 0
        pontos = pasta / "points.json"
        if pontos.exists():
            for ponto in json.loads(pontos.read_text(encoding="utf-8")):
                for campo in ("value_text", "value_numeric"):
                    valor = ponto.get(campo)
                    if valor is not None:
                        graficos.setdefault(pagina, set()).add(_digitos(str(valor)))
    return {"tabelas": tabelas, "texto": texto_por_pagina, "graficos": graficos}


def analisar(pdf: Path, extraction: Path) -> list[dict]:
    paginas = paginas_do_pdf(pdf)
    ex = extracao_por_pagina(extraction)
    todos = set().union(*ex["tabelas"].values(), *ex["texto"].values())
    todos_graficos = set().union(*ex["graficos"].values()) if ex["graficos"] else set()
    resultado = []
    for numero_pagina, tokens in enumerate(paginas, start=1):
        em_tabela_pagina = set().union(*(ex["tabelas"].get(p, set()) for p in range(max(1, numero_pagina - TOLERANCIA_TABELA), numero_pagina + 1)))
        em_texto = ex["texto"].get(numero_pagina, set())
        em_grafico = ex["graficos"].get(numero_pagina, set())
        cat = {"tabela": [], "texto": [], "grafico": [], "outra pagina": [], "ausente": []}
        for t in sorted(tokens):
            if t in em_tabela_pagina:
                cat["tabela"].append(t)
            elif t in em_texto:
                cat["texto"].append(t)
            elif _digitos(t) in em_grafico:
                cat["grafico"].append(t)
            elif t in todos or _digitos(t) in todos_graficos:
                cat["outra pagina"].append(t)
            else:
                cat["ausente"].append(t)
        fora = len(tokens) - len(cat["tabela"])
        resultado.append(
            {
                "pagina": numero_pagina,
                "total": len(tokens),
                "contagem": {k: len(v) for k, v in cat.items()},
                "amostra_ausente": cat["ausente"][:6],
                "sinalizada": len(tokens) >= MIN_NUMEROS and fora >= MIN_FORA_DE_TABELA,
            }
        )
    return resultado


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--rotulo", default="novo")
    p.add_argument("--saida", default="")
    p.add_argument("--filtro", default="")
    args = p.parse_args()

    base = RAIZ / args.rotulo
    linhas = [f"# Cobertura da extração `{args.rotulo}`: números do PDF × números extraídos\n",
              "Gerado por `scripts/analisar_cobertura.py`. Páginas sinalizadas = muitos números e boa parte fora de tabela; "
              "confirmar no PDF.\n",
              "| PDF | Págs. | Sinalizadas | Números nas sinalizadas: tabela / texto / gráfico / outra pág. / **ausente** |",
              "| --- | --- | --- | --- |"]
    detalhes = []
    for pasta in sorted(base.iterdir()):
        if args.filtro not in pasta.name or not (pasta / "extraction").is_dir():
            continue
        pdf = RAIZ / "pdfs" / f"{pasta.name}.pdf"
        if not pdf.exists():
            continue
        paginas = analisar(pdf, pasta / "extraction")
        marcadas = [pg for pg in paginas if pg["sinalizada"]]
        soma = {k: sum(pg["contagem"][k] for pg in marcadas) for k in ("tabela", "texto", "grafico", "outra pagina", "ausente")}
        linhas.append(
            f"| {pasta.name} | {len(paginas)} | {', '.join(str(pg['pagina']) for pg in marcadas) or '—'} | "
            f"{soma['tabela']} / {soma['texto']} / {soma['grafico']} / {soma['outra pagina']} / **{soma['ausente']}** |"
        )
        if marcadas:
            detalhes.append(f"\n### {pasta.name}\n")
            detalhes.append("| Pág. | Números | tabela | texto | gráfico | outra pág. | ausente | exemplos ausentes |")
            detalhes.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
            for pg in marcadas:
                c = pg["contagem"]
                detalhes.append(
                    f"| {pg['pagina']} | {pg['total']} | {c['tabela']} | {c['texto']} | {c['grafico']} | "
                    f"{c['outra pagina']} | {c['ausente']} | {', '.join(pg['amostra_ausente'])} |"
                )
    texto = "\n".join(linhas + detalhes) + "\n"
    if args.saida:
        Path(args.saida).write_text(texto, encoding="utf-8")
        print(f"escrito {args.saida}")
    else:
        print(texto)


if __name__ == "__main__":
    main()

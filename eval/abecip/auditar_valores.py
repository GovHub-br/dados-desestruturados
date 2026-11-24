"""Audita, valor a valor, o que a ABECIP publica contra uma referencia tirada do proprio PDF, sem passar pela LLM.

A referencia sai das tabelas da extracao, lidas por posicao com um leitor de numeros proprio (formato brasileiro
estrito, independente de `parse_flexible_number`), e cada celula e conferida pelas identidades que o boletim
garante:

- tabela 2 (financiamentos): acumulado no ano do mes = acumulado do mes anterior + valor do mes (unidades e R$);
- tabela 1 (poupanca): saldo do mes - saldo do mes anterior = variacao no mes; captacao acumulada = anterior + mes;
- tabela 3 (anual): os meses do ano corrente repetem a tabela 2; o ano fechado mais recente repete o acumulado
  de dezembro; os anos anteriores sao conferidos entre os PDFs de todos os meses (consenso);
- tabelas 4 a 6 (por instituicao): soma das instituicoes = TOTAL; Construcao + Aquisicao = Aquisicao e Construcao.

Celula que nao passa em nenhuma identidade fica marcada como "a conferir na imagem". Depois cada valor publicado
(`schema_saida`) e comparado com a referencia: certo, errado (mapeamento: o numero publicado existe em outra
celula; leitura: o publicado e a celula certa, mas a celula nao fecha), ausente ou a mais.

Roda no conteiner do Airflow:

    docker exec -w /opt/project/dados-desestruturados ocr_airflow_scheduler python \\
        eval/abecip/auditar_valores.py --execucao 2026-05=exp-faixas-rotulos-2__abecip__abecip__2026-05__r2 ... [--saida r.json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docling" / "scripts"))
import _lote  # noqa: E402
import simular_faixas_por_codigo as sim  # noqa: E402

from document_processing.application.use_cases.resolution.resolve_schema import (  # noqa: E402
    ResolveSchemaUseCase,
)

MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
PREFIXO_FALLBACK = "fallback/abecip/abecip/"
NUMERO_BR = re.compile(r"^-?\d{1,3}(?:\.\d{3})*(?:,\d+)?$|^-?\d+(?:,\d+)?$")
# Virgula decimal lida como ponto pelo OCR: depois do ultimo ponto vem 1 ou 2 digitos, entao nao e milhar.
DECIMAL_COM_PONTO = re.compile(r"^-?\d{1,3}(?:\.\d{3})*\.\d{1,2}$")


def numero(celula: Any) -> float | None:
    """Le so o formato brasileiro bem formado (ou a virgula decimal lida como ponto); o resto volta None."""
    texto = str(celula or "").strip().replace(" ", "")
    if DECIMAL_COM_PONTO.match(texto):
        inteiro, _, decimais = texto.rpartition(".")
        return float(f"{inteiro.replace('.', '')}.{decimais}")
    if not NUMERO_BR.match(texto):
        return None
    return float(texto.replace(".", "").replace(",", "."))


def chave(texto: Any) -> str:
    sem_acento = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", sem_acento.lower())


def igual(a: float | None, b: float | None, tolerancia: float = 0.051) -> bool:
    return a is not None and b is not None and abs(a - b) <= tolerancia


class Celula:
    def __init__(self, tabela: str, linha: int, coluna: int, bruto: Any):
        self.tabela, self.linha, self.coluna, self.bruto = tabela, linha, coluna, bruto
        self.valor = numero(bruto)
        self.confere: list[str] = []
        self.falha: list[str] = []

    def onde(self) -> str:
        return f"{self.tabela} l{self.linha} c{self.coluna} '{self.bruto}'"


def classificar_tabelas(tabelas: dict[str, list[list[Any]]], nomes: dict[str, str]) -> dict[str, str]:
    """Papel de cada tabela pelo numero do titulo ("4 - Construcao") e pela forma das linhas; o OCR troca letras
    do titulo ("Construgao", "Aquisigao"), entao o nome por extenso nao serve."""
    papel: dict[str, str] = {}
    for arquivo, linhas in tabelas.items():
        nome = chave(nomes.get(arquivo))
        primeira = [chave(c) for c in (linhas[0] if linhas else [])]
        por_instituicao = bool(linhas) and len(linhas[0]) == 5 and not re.fullmatch(r"20\d\d", primeira[0] or "")
        if por_instituicao and nome[:1] in {"4", "5", "6"}:
            papel[{"4": "inst_c", "5": "inst_a", "6": "inst_ac"}[nome[0]]] = arquivo
        elif primeira and re.fullmatch(r"20\d\d", primeira[0] or "") and len(linhas[0]) <= 7:
            papel["anual"] = arquivo
        elif primeira and primeira[0] in MESES and len(linhas[0]) >= 14:
            # poupanca tem a variacao percentual na col. 4; financiamentos tem 12 meses (inteiro grande) na col. 3
            papel["poupanca" if "%" in str(linhas[0][4]) else "financiamentos"] = arquivo
    return papel


def linhas_de_mes(linhas: list[list[Any]]) -> list[int]:
    return [i for i, linha in enumerate(linhas) if linha and len(linha) >= 14][:12]


def referencia(tabelas: dict[str, list[list[Any]]], papel: dict[str, str], mes_ref: int) -> dict[str, Any]:
    """Valores esperados de cada colecao do contrato, com a celula de origem e o resultado das identidades."""
    ref: dict[str, Any] = {}
    celulas: dict[tuple[str, int, int], Celula] = {}

    def cel(arquivo: str, i: int, j: int) -> Celula:
        k = (arquivo, i, j)
        if k not in celulas:
            linha = tabelas[arquivo][i]
            celulas[k] = Celula(arquivo, i, j, linha[j] if j < len(linha) else None)
        return celulas[k]

    # tabela 2: ano corrente = colunas 7 (unidades no mes), 8 (no ano), 10 (R$ no mes), 11 (no ano)
    fin = papel.get("financiamentos")
    serie = []
    if fin:
        idx = linhas_de_mes(tabelas[fin])[:mes_ref]
        ant_u = ant_v = 0.0
        for n, i in enumerate(idx):
            u, ua, v, va = cel(fin, i, 7), cel(fin, i, 8), cel(fin, i, 10), cel(fin, i, 11)
            # R$ vem arredondado ao milhao em cada coluna, entao o acumulado pode diferir de 1 da soma
            for mes_c, acum_c, anterior, tolerancia in ((u, ua, ant_u, 0.15), (v, va, ant_v, 1.01)):
                if igual((mes_c.valor or 0) + anterior, acum_c.valor, tolerancia):
                    mes_c.confere.append("acumulado")
                    acum_c.confere.append("acumulado")
                else:
                    mes_c.falha.append("acumulado")
            ant_u, ant_v = ua.valor or 0.0, va.valor or 0.0
            serie.append({"mes": MESES[n], "unidades_financiadas": u, "volume_financiado_milhoes": v})
    ref["serie_mensal_sbpe"] = serie

    # tabela 1: ano anterior col. 1 (saldo); ano corrente col. 7 (saldo), 8 (variacao no mes), 11 (captacao), 13 (captacao no ano)
    pou = papel.get("poupanca")
    saldos, capt = [], []
    if pou:
        todas = linhas_de_mes(tabelas[pou])
        idx = todas[:mes_ref]
        saldo_ant = numero(tabelas[pou][todas[11]][1]) if len(todas) == 12 else None
        capt_ant = 0.0
        for n, i in enumerate(idx):
            s, var, c, ca = cel(pou, i, 7), cel(pou, i, 8), cel(pou, i, 11), cel(pou, i, 13)
            if igual((s.valor or 0) - (saldo_ant or 0), var.valor, 1.01) and saldo_ant is not None:
                s.confere.append("saldo-variacao")
            else:
                s.falha.append("saldo-variacao")
            if igual((c.valor or 0) + capt_ant, ca.valor, 1.01):
                c.confere.append("acumulado")
            else:
                c.falha.append("acumulado")
            saldo_ant, capt_ant = s.valor, ca.valor or 0.0
            saldos.append({"mes": MESES[n], "saldo_milhoes": s})
            capt.append({"mes": MESES[n], "captacao_liquida_milhoes": c})
    ref["saldos_mensais"], ref["captacoes_liquidas_mensais"] = saldos, capt

    # tabela 3: anos fechados; os meses do ano corrente repetem a tabela 2
    anu = papel.get("anual")
    anual = []
    if anu:
        for i, lin in enumerate(tabelas[anu]):
            # em alguns meses o Docling abre uma coluna vazia depois do ano: unidades e R$ sao as duas primeiras
            # celulas numericas que nao sao percentual
            numericas = [j for j in range(1, len(lin)) if "%" not in str(lin[j]) and numero(lin[j]) is not None]
            if len(numericas) < 2:
                continue
            ju, jv = numericas[0], numericas[1]
            rotulos = [chave(c) for c in lin[: numericas[0]]]
            if re.fullmatch(r"20\d\d", str(lin[0]).strip()):
                anual.append({"ano": str(lin[0]).strip(), "unidades_financiadas": cel(anu, i, ju), "volume_financiado_milhoes": cel(anu, i, jv)})
            elif serie and any(r[:3] in MESES for r in rotulos):
                n = MESES.index(next(r[:3] for r in rotulos if r[:3] in MESES))
                if n < len(serie):
                    for campo, j in (("unidades_financiadas", ju), ("volume_financiado_milhoes", jv)):
                        a, b = cel(anu, i, j), serie[n][campo]
                        if igual(a.valor, b.valor, 0.6):
                            b.confere.append("tabela3")
    ref["serie_historica_anual"] = anual

    # tabelas 4 a 6: [agente, R$ mes, unidades mes, R$ ano, unidades ano]
    campos = ["volume_mensal_milhoes", "unidades_mensais", "volume_acumulado_ano_milhoes", "unidades_acumuladas_ano"]
    por_inst: dict[str, dict[str, dict[str, Celula]]] = {}
    for modalidade, papel_t in (("construcao", "inst_c"), ("aquisicao", "inst_a"), ("aquisicao_e_construcao", "inst_ac")):
        arq = papel.get(papel_t)
        if not arq:
            continue
        linhas = tabelas[arq]
        dados = {
            chave(lin[0]): {campos[j - 1]: cel(arq, i, j) for j in range(1, 5)}
            for i, lin in enumerate(linhas)
            if lin and chave(lin[0]) and chave(lin[0]) != "total" and len(lin) >= 5
        }
        total = next(({campos[j - 1]: numero(lin[j]) for j in range(1, 5)} for lin in linhas if lin and chave(lin[0]) == "total"), {})
        for campo in campos:
            soma = sum((d[campo].valor or 0.0) for d in dados.values())
            if igual(soma, total.get(campo), 0.6):
                for d in dados.values():
                    d[campo].confere.append("soma=total")
            else:
                for d in dados.values():
                    d[campo].falha.append("soma=total")
        por_inst[modalidade] = dados
    if len(por_inst) == 3:
        for inst, d_ac in por_inst["aquisicao_e_construcao"].items():
            for campo in campos:
                c = por_inst["construcao"].get(inst, {}).get(campo)
                a = por_inst["aquisicao"].get(inst, {}).get(campo)
                soma = (c.valor or 0.0 if c else 0.0) + (a.valor or 0.0 if a else 0.0)
                if igual(soma, d_ac[campo].valor, 0.15):
                    for x in (c, a, d_ac[campo]):
                        if x is not None:
                            x.confere.append("c+a=ac")
    ref["por_modalidade_e_instituicao"] = por_inst
    ref["_celulas"] = celulas
    return ref


def celulas_do_contrato(ref: dict[str, Any]) -> list[Celula]:
    """So as celulas que o contrato publica; as auxiliares (acumulados, variacao) servem de prova, nao de saida."""
    saida = []
    for colecao in ("serie_mensal_sbpe", "saldos_mensais", "captacoes_liquidas_mensais", "serie_historica_anual"):
        for item in ref.get(colecao) or []:
            saida += [v for v in item.values() if isinstance(v, Celula)]
    for dados in (ref.get("por_modalidade_e_instituicao") or {}).values():
        for campos in dados.values():
            saida += list(campos.values())
    return saida


def achar(obj: Any, nome: str) -> Any:
    return sim.achar(obj, nome)


def comparar(ref: dict[str, Any], schema: dict[str, Any], tabelas: dict[str, list[list[Any]]]) -> dict[str, Any]:
    todos_valores = Counter(numero(c) for linhas in tabelas.values() for lin in linhas for c in lin if numero(c) is not None)
    resultado: dict[str, Any] = {}

    def julgar(publicado: Any, esperado: Celula | None) -> tuple[str, str]:
        if esperado is None:
            return "a_mais", ""
        if publicado is None:
            return ("ausente", esperado.onde()) if esperado.valor is not None or esperado.bruto not in ("-", "", None) else ("certo", "")
        if not isinstance(publicado, (int, float)) or isinstance(publicado, bool):
            return "tipo", f"publicado {publicado!r} (o contrato pede number); esperado {esperado.valor} ({esperado.onde()})"
        if igual(float(publicado), esperado.valor, 0.001):
            return ("certo" if esperado.confere else "certo_nao_conferido"), esperado.onde()
        if esperado.valor is None:
            return "leitura", f"publicado {publicado}; celula {esperado.onde()} fora do formato"
        if todos_valores.get(float(publicado)):
            return "mapeamento", f"publicado {publicado}; esperado {esperado.valor} ({esperado.onde()})"
        return "leitura", f"publicado {publicado}; esperado {esperado.valor} ({esperado.onde()})"

    def periodo(item: dict[str, Any]) -> str:
        p = item.get("periodo") or {}
        return chave(p.get("rotulo_publicado") if isinstance(p, dict) else p)

    for colecao, campos in (
        ("serie_mensal_sbpe", ("unidades_financiadas", "volume_financiado_milhoes")),
        ("saldos_mensais", ("saldo_milhoes",)),
        ("captacoes_liquidas_mensais", ("captacao_liquida_milhoes",)),
    ):
        esperados = ref.get(colecao) or []
        publicados = achar(schema, colecao) or []
        achados = []
        for n, esp in enumerate(esperados):
            pub = publicados[n] if n < len(publicados) else {}
            rot = periodo(pub)
            if pub and rot[:3] != esp["mes"]:
                achados.append(("rotulo", f"{esp['mes']}: rotulo publicado '{(pub.get('periodo') or {}).get('rotulo_publicado')}'"))
            for campo in campos:
                achados.append(julgar(pub.get(campo) if pub else None, esp[campo]))
        for _ in publicados[len(esperados):]:
            achados.append(("a_mais", colecao))
        resultado[colecao] = achados

    esperados = {e["ano"]: e for e in ref.get("serie_historica_anual") or []}
    achados = []
    publicados = achar(schema, "serie_historica_anual") or []
    vistos = set()
    for pub in publicados:
        ano = re.sub(r"\D", "", str((pub.get("periodo") or {}).get("rotulo_publicado")))
        esp = esperados.get(ano)
        if esp is None or "*" in str((pub.get("periodo") or {}).get("rotulo_publicado")):
            achados.append(("a_mais", f"anual '{(pub.get('periodo') or {}).get('rotulo_publicado')}'"))
            continue
        vistos.add(ano)
        for campo in ("unidades_financiadas", "volume_financiado_milhoes"):
            achados.append(julgar(pub.get(campo), esp[campo]))
    for ano in esperados:
        if ano not in vistos:
            achados.append(("ausente", f"ano {ano}"))
    resultado["serie_historica_anual"] = achados

    achados = []
    por_inst = ref.get("por_modalidade_e_instituicao") or {}
    vistos = set()
    for pub in achar(schema, "por_modalidade_e_instituicao") or []:
        mod = chave(pub.get("modalidade"))
        # no contrato a tabela "Aquisicao e Construcao" e a modalidade `total`
        mod = {"construcao": "construcao", "aquisicao": "aquisicao", "total": "aquisicao_e_construcao"}.get(mod, mod)
        inst = chave(pub.get("instituicao_financeira"))
        esp = por_inst.get(mod, {}).get(inst)
        if esp is None:
            parecido = next((k for k in por_inst.get(mod, {}) if k.replace("do", "") == inst.replace("do", "")), None)
            esp = por_inst.get(mod, {}).get(parecido) if parecido else None
            if esp is None:
                achados.append(("a_mais", f"{mod}/{pub.get('instituicao_financeira')}"))
                continue
            inst = parecido
        vistos.add((mod, inst))
        for campo, celula in esp.items():
            achados.append(julgar(pub.get(campo), celula))
    for mod, dados in por_inst.items():
        for inst in dados:
            if (mod, inst) not in vistos:
                achados.append(("ausente", f"{mod}/{inst}"))
    resultado["por_modalidade_e_instituicao"] = achados
    return resultado


def main() -> int:
    analisador = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analisador.add_argument("--execucao", action="append", required=True, help="MES=run_id (ex.: 2026-05=exp-x__abecip__abecip__2026-05)")
    analisador.add_argument("--saida")
    args = analisador.parse_args()

    minio, bucket = _lote.cliente_minio()
    contrato = json.loads(sim.CONTRATO.read_text(encoding="utf-8"))
    uso = ResolveSchemaUseCase()
    relatorio: dict[str, Any] = {}
    anuais: dict[str, dict[str, list[tuple[str, float | None, Celula]]]] = {}
    for par in args.execucao:
        mes, run = par.split("=", 1)
        prefixo = next(
            (
                o.object_name.rsplit("layout_signature_candidato.json", 1)[0]
                for o in minio.list_objects(bucket, prefix=PREFIXO_FALLBACK, recursive=True)
                if o.object_name.endswith(f"execution_id=dag_valida_e_fallback_llm__{run}/layout_signature_candidato.json")
            ),
            None,
        )
        if prefixo is None:
            # o Airflow marca o run como success mesmo quando o fallback falha por dentro
            print(f"\n=== {mes}  ({run})  SEM CANDIDATO: o fallback nao gerou layout")
            continue
        candidato = json.loads(minio.get_object(bucket, prefixo + "layout_signature_candidato.json").read())
        document_id = prefixo.split("document_id=")[1].split("/")[0]
        execucao = str(candidato.get("execution_id_origem"))
        with tempfile.TemporaryDirectory() as temporaria:
            raiz = sim.baixar_extracao(minio, bucket, document_id, execucao, Path(temporaria))
            manifesto = json.loads((raiz / "manifesto_execucao.json").read_text(encoding="utf-8"))
            schema = sim.resolver(uso, contrato, candidato.get("mapeamento_canonico") or {}, raiz, manifesto)
            tabelas, nomes = {}, {}
            for f in sorted((raiz / "tables").glob("table*.json")):
                t = json.loads(f.read_text(encoding="utf-8"))
                tabelas[f.name] = t.get("rows") or []
                nomes[f.name] = t.get("name") or ""
        papel = classificar_tabelas(tabelas, nomes)
        mes_ref = int(mes.split("-")[1])
        ref = referencia(tabelas, papel, mes_ref)
        for e in ref["serie_historica_anual"]:
            for campo in ("unidades_financiadas", "volume_financiado_milhoes"):
                anuais.setdefault(e["ano"], {}).setdefault(campo, []).append((mes, e[campo].valor, e[campo]))
        relatorio[mes] = {"run": run, "execucao": execucao, "papel": papel, "ref": ref, "schema": schema, "tabelas": tabelas}

    # consenso da serie anual entre os PDFs: valor igual ao da maioria confere
    for ano, campos in anuais.items():
        for campo, lista in campos.items():
            votos = Counter(round(v, 2) for _, v, _ in lista if v is not None)
            if not votos:
                continue
            maioria, n = votos.most_common(1)[0]
            for _, v, c in lista:
                if v is not None and round(v, 2) == maioria and n >= 2:
                    c.confere.append(f"consenso {n}/{len(lista)}")
                else:
                    c.falha.append(f"consenso: maioria {maioria} ({n}/{len(lista)})")

    saida = {}
    total = Counter()
    for mes, r in sorted(relatorio.items()):
        res = comparar(r["ref"], r["schema"], r["tabelas"])
        faltam = [k for k in ("financiamentos", "poupanca", "anual", "inst_c", "inst_a", "inst_ac") if k not in r["papel"]]
        nao_fecham = [c.onde() + " " + ",".join(c.falha) for c in celulas_do_contrato(r["ref"]) if not c.confere]
        print(f"\n=== {mes}  ({r['run']})  tabelas: {r['papel']}" + (f"  FALTAM {faltam}" if faltam else ""))
        for colecao, achados in res.items():
            cont = Counter(a[0] for a in achados)
            total.update(cont)
            print(f"  {colecao:30s} " + "  ".join(f"{k}={v}" for k, v in sorted(cont.items())))
            for tipo, detalhe in achados:
                if tipo not in ("certo", "certo_nao_conferido"):
                    print(f"      [{tipo}] {detalhe}")
        if nao_fecham:
            print(f"  celulas usadas que nao fecham em nenhuma identidade ({len(nao_fecham)}):")
            for x in nao_fecham:
                print(f"      {x}")
        saida[mes] = {"run": r["run"], "papel": r["papel"], "achados": res, "nao_fecham": nao_fecham}
    print("\nTOTAL:", dict(total))
    if args.saida:
        Path(args.saida).write_text(json.dumps(saida, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

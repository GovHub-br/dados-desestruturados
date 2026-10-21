"""Verifica a consistencia das colecoes da ABECIP geradas pelo fallback, sem gabarito lido no PDF.

Para cada execucao da DAG 3 de uma release, cruza o layout gerado (`layout_signature_candidato.json`) com as
tabelas da extracao em que ele foi gerado e confere o que o proprio documento garante:

1. cobertura de linhas: a faixa de cada tabela comeca na primeira linha de dados, nao inclui a linha de total e
   nao deixa de fora linha de dados de uma colecao de varias tabelas; tabelas escolhidas e sem uso;
2. soma = TOTAL: a soma das instituicoes de cada faixa bate com a linha TOTAL da mesma tabela (digito errado de
   OCR ou linha perdida);
3. identidade entre tabelas: Aquisicao e Construcao = Construcao + Aquisicao, por instituicao;
4. semantica da coluna: campo de unidades sai de coluna cujo cabecalho fala de unidades, campo de volume de coluna
   em R$, mensal x acumulado no ano coincide com o cabecalho, series leem o ano mais recente;
5. itens vazios: item publicado em que todos os campos numericos vieram nulos (mes futuro lido como se tivesse dado).

Mede consistencia, nao verdade absoluta: um erro que o PDF repete de forma coerente nao aparece aqui. O gabarito
curado (`eval/gabaritos/`) continua sendo a medida de verdade, so para maio/2026.

Roda no contêiner do Airflow (tem o cliente do MinIO e o PYTHONPATH do projeto):

    docker exec -w /opt/project/dados-desestruturados ocr_airflow_scheduler python \\
        eval/abecip/verificar_colecoes.py --release exp-abecip-varios-meses [--saida relatorio.json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docling" / "scripts"))
import _lote  # noqa: E402

from document_processing.domain.fallback.table_structure import celula_parece_numerica  # noqa: E402
from document_processing.domain.observability import (
    selection_mapping_coverage_metrics,  # noqa: E402
)
from document_processing.domain.resolution.numbers import parse_flexible_number  # noqa: E402

RAIZ_FALLBACK = "fallback/abecip/abecip/"
RAIZ_EXTRACAO = "execucoes/abecip/extracao/abecip/"
POR_MODALIDADE = "financiamentos_imobiliarios.por_modalidade_e_instituicao"
ALERTA, INFO, OK = "ALERTA", "info", "ok"


def normalizar(texto: Any) -> str:
    """Minusculas, sem acento nem espaco: `BANCO DOBRASIL` e `BANCO DO BRASIL` viram a mesma chave."""
    base = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", base.lower())


def celula(linha: list[Any], indice: int) -> str:
    return str(linha[indice]).strip() if 0 <= indice < len(linha) and linha[indice] is not None else ""


def numero(valor: str) -> float:
    """Numero da celula; vazio ou traco contam como zero (o PDF usa `-` para sem operacao)."""
    if not valor or valor in {"-", "–", "—"}:
        return 0.0
    convertido = parse_flexible_number(valor)
    return float(convertido) if convertido is not None else 0.0


def eh_total(linha: list[Any]) -> bool:
    return normalizar(celula(linha, 0)).startswith("total")


def eh_dado(linha: list[Any]) -> bool:
    """Linha de dados: rotulo na primeira coluna e algum numero nas outras; total nao conta."""
    if eh_total(linha) or not celula(linha, 0):
        return False
    return any(celula_parece_numerica(celula(linha, i)) for i in range(1, len(linha)) if celula(linha, i))


def casas_decimais(valores: list[str]) -> bool:
    return any(re.search(r",\d", v) for v in valores)


class Tabela:
    def __init__(self, arquivo: str, conteudo: dict[str, Any]) -> None:
        self.arquivo = arquivo
        self.nome = str(conteudo.get("name") or "")
        self.cabecalhos = [str(c) for c in (conteudo.get("schema") or [])]
        self.linhas = [list(linha) for linha in (conteudo.get("rows") or [])]

    def cabecalho(self, coluna: int) -> str | None:
        generico = all(re.fullmatch(r"(column_\d+|\d+)?", normalizar(c) or "") for c in self.cabecalhos)
        if generico or not (0 <= coluna < len(self.cabecalhos)):
            return None
        return self.cabecalhos[coluna]

    def dados(self) -> list[int]:
        return [i for i, linha in enumerate(self.linhas) if eh_dado(linha)]

    def total_depois(self, fim: int) -> int | None:
        """Linha de total logo depois da faixa (pulando linhas vazias), se houver."""
        for i in range(fim + 1, min(fim + 3, len(self.linhas))):
            if eh_total(self.linhas[i]):
                return i
            if celula(self.linhas[i], 0) and eh_dado(self.linhas[i]):
                return None
        return None


class Unidade:
    """Um trecho do layout que le linhas de uma tabela: uma fonte, um segmento ou a instrucao inteira."""

    def __init__(self, caminho: str, arquivo: str, faixas: list[tuple[int, int]], campos: list[dict[str, Any]], valores: dict[str, Any]) -> None:
        self.caminho, self.arquivo, self.faixas, self.campos, self.valores = caminho, arquivo, faixas, campos, valores

    @property
    def modalidade(self) -> str:
        return normalizar(self.valores.get("modalidade"))


def faixas_de(trecho: dict[str, Any], n_linhas: int) -> list[tuple[int, int]]:
    brutas = trecho.get("segmentos") or trecho.get("faixas_linhas")
    if not isinstance(brutas, list) or not brutas:
        brutas = [trecho]
    faixas = []
    for b in brutas:
        ini = int(b.get("linha_inicial", 0))
        fim = int(b.get("linha_final", n_linhas - 1))
        faixas.append((ini, fim))
    return faixas


def unidades_do_layout(mapeamento: dict[str, Any], tabelas: dict[str, Tabela]) -> list[Unidade]:
    saida: list[Unidade] = []
    for caminho, entrada in mapeamento.items():
        tipo = entrada.get("tipo_origem")
        if tipo == "linhas_de_tabelas":
            for fonte in entrada.get("fontes") or []:
                tabela = tabelas.get(str(fonte.get("arquivo_origem")))
                n = len(tabela.linhas) if tabela else 0
                saida.append(Unidade(caminho, str(fonte.get("arquivo_origem")), faixas_de(fonte, n), fonte.get("campos") or [], fonte.get("valores_por_segmento") or {}))
        elif tipo == "linhas_de_tabela":
            arquivo = str(entrada.get("arquivo_origem"))
            tabela = tabelas.get(arquivo)
            n = len(tabela.linhas) if tabela else 0
            segmentos = entrada.get("segmentos")
            if isinstance(segmentos, list) and segmentos:
                for seg in segmentos:
                    campos = seg.get("campos") or entrada.get("campos") or []
                    saida.append(Unidade(caminho, arquivo, [(int(seg.get("linha_inicial", 0)), int(seg.get("linha_final", n - 1)))], campos, seg.get("valores_por_segmento") or {}))
            else:
                saida.append(Unidade(caminho, arquivo, faixas_de(entrada, n), entrada.get("campos") or [], entrada.get("valores_por_segmento") or {}))
    return saida


def achado(nivel: str, verificacao: str, onde: str, texto: str) -> dict[str, str]:
    return {"nivel": nivel, "verificacao": verificacao, "onde": onde, "texto": texto}


def verificar_cobertura(unidades: list[Unidade], tabelas: dict[str, Tabela]) -> list[dict[str, str]]:
    achados: list[dict[str, str]] = []
    por_tabela: dict[tuple[str, str], list[Unidade]] = {}
    for u in unidades:
        por_tabela.setdefault((u.caminho, u.arquivo), []).append(u)
    for (caminho, arquivo), grupo in por_tabela.items():
        tabela = tabelas.get(arquivo)
        colecao = caminho.rsplit(".", 1)[-1]
        if tabela is None:
            achados.append(achado(ALERTA, "cobertura", f"{colecao} {arquivo}", "a tabela citada nao existe na extracao"))
            continue
        dados = set(tabela.dados())
        mapeadas = {i for u in grupo for ini, fim in u.faixas for i in range(ini, fim + 1) if 0 <= i < len(tabela.linhas)}
        if not dados:
            achados.append(achado(INFO, "cobertura", f"{colecao} {arquivo}", "tabela sem linha de dados reconhecivel"))
            continue
        primeira = min(dados)
        if primeira not in mapeadas:
            inicio = min(mapeadas) if mapeadas else None
            achados.append(achado(ALERTA, "cobertura", f"{colecao} {arquivo}", f"a faixa pula a primeira linha de dados (linha {primeira}: '{celula(tabela.linhas[primeira], 0)}'); comeca em {inicio}"))
        totais_dentro = [i for i in mapeadas if i < len(tabela.linhas) and eh_total(tabela.linhas[i])]
        if totais_dentro:
            achados.append(achado(ALERTA, "cobertura", f"{colecao} {arquivo}", f"a faixa inclui linha de total ({totais_dentro})"))
        fora_inicio = sorted(i for i in dados if i < min(mapeadas, default=0) and i not in mapeadas)
        fora_fim = sorted(i for i in dados if mapeadas and i > max(mapeadas))
        if fora_fim:
            colunas = [int(c.get("indice_coluna")) for u in grupo for c in u.campos if c.get("tipo") == "numero" and isinstance(c.get("indice_coluna"), int)]
            com_valor = [i for i in fora_fim if any(celula(tabela.linhas[i], c) for c in colunas)]
            nivel = ALERTA if (caminho == POR_MODALIDADE and com_valor) else INFO
            texto = f"{len(fora_fim)} linha(s) de dados depois da faixa, {len(com_valor)} com valor nas colunas mapeadas"
            achados.append(achado(nivel, "cobertura", f"{colecao} {arquivo}", texto))
        if not fora_inicio and not fora_fim and primeira in mapeadas and not totais_dentro:
            achados.append(achado(OK, "cobertura", f"{colecao} {arquivo}", f"faixa cobre as {len(dados)} linhas de dados"))
    return achados


def colunas_numericas(u: Unidade) -> dict[str, int]:
    return {str(c.get("caminho_saida")): int(c["indice_coluna"]) for c in u.campos if c.get("tipo") == "numero" and isinstance(c.get("indice_coluna"), int)}


def verificar_somas(unidades: list[Unidade], tabelas: dict[str, Tabela]) -> list[dict[str, str]]:
    achados: list[dict[str, str]] = []
    for u in unidades:
        tabela = tabelas.get(u.arquivo)
        if tabela is None or u.caminho != POR_MODALIDADE:
            continue
        for ini, fim in u.faixas:
            total = tabela.total_depois(fim)
            if total is None:
                total = next((i for i in range(len(tabela.linhas) - 1, -1, -1) if eh_total(tabela.linhas[i])), None)
            rotulo = f"{u.modalidade or tabela.nome} {u.arquivo}"
            if total is None:
                achados.append(achado(INFO, "soma=total", rotulo, "tabela sem linha TOTAL"))
                continue
            linhas = [tabela.linhas[i] for i in range(ini, fim + 1) if i < len(tabela.linhas) and eh_dado(tabela.linhas[i])]
            ruins = []
            for campo, coluna in colunas_numericas(u).items():
                alvo = numero(celula(tabela.linhas[total], coluna))
                soma = sum(numero(celula(linha, coluna)) for linha in linhas)
                decimais = casas_decimais([celula(linha, coluna) for linha in linhas])
                tolerancia = 0.06 * max(len(linhas), 1) if decimais else 0.5
                if abs(soma - alvo) > tolerancia:
                    ruins.append(f"{campo}: soma {soma:g} x TOTAL {alvo:g} (dif {soma - alvo:+g})")
            if ruins:
                achados.append(achado(ALERTA, "soma=total", rotulo, "; ".join(ruins)))
            else:
                achados.append(achado(OK, "soma=total", rotulo, f"{len(linhas)} instituicoes somam o TOTAL em todas as colunas"))
    return achados


def verificar_identidade(unidades: list[Unidade], tabelas: dict[str, Tabela]) -> list[dict[str, str]]:
    por_modalidade: dict[str, dict[str, dict[str, float]]] = {}
    for u in unidades:
        tabela = tabelas.get(u.arquivo)
        if tabela is None or u.caminho != POR_MODALIDADE or not u.modalidade:
            continue
        campos = colunas_numericas(u)
        destino = por_modalidade.setdefault(u.modalidade, {})
        for ini, fim in u.faixas:
            for i in range(ini, fim + 1):
                if i < len(tabela.linhas) and eh_dado(tabela.linhas[i]):
                    instituicao = normalizar(celula(tabela.linhas[i], 0))
                    for campo, coluna in campos.items():
                        destino.setdefault(instituicao, {})[campo] = numero(celula(tabela.linhas[i], coluna))
    if not {"construcao", "aquisicao", "total"} <= set(por_modalidade):
        return [achado(INFO, "identidade", "modalidades", f"nao ha as tres modalidades no layout ({sorted(por_modalidade)})")]
    ruins = []
    for instituicao, campos in por_modalidade["total"].items():
        for campo, valor in campos.items():
            esperado = por_modalidade["construcao"].get(instituicao, {}).get(campo, 0.0) + por_modalidade["aquisicao"].get(instituicao, {}).get(campo, 0.0)
            if abs(valor - esperado) > (0.11 if valor != int(valor) or esperado != int(esperado) else 0.5):
                ruins.append(f"{instituicao} {campo}: total {valor:g} x construcao+aquisicao {esperado:g}")
    if ruins:
        return [achado(ALERTA, "identidade", "total = construcao + aquisicao", "; ".join(ruins[:8]) + (f" (+{len(ruins) - 8})" if len(ruins) > 8 else ""))]
    return [achado(OK, "identidade", "total = construcao + aquisicao", f"{len(por_modalidade['total'])} instituicoes conferem")]


def verificar_colunas(unidades: list[Unidade], tabelas: dict[str, Tabela]) -> list[dict[str, str]]:
    achados: list[dict[str, str]] = []
    anos_por_tabela = {a: {int(y) for c in t.cabecalhos for y in re.findall(r"20\d\d", c)} for a, t in tabelas.items()}
    for u in unidades:
        tabela = tabelas.get(u.arquivo)
        if tabela is None:
            continue
        for campo, coluna in colunas_numericas(u).items():
            cabecalho = tabela.cabecalho(coluna)
            if cabecalho is None:
                continue
            h, f = normalizar(cabecalho), campo.lower()
            colecao = u.caminho.rsplit(".", 1)[-1]
            problemas = []
            if "unidades" in f and "unidad" not in h:
                problemas.append("campo de unidades, cabecalho sem unidades")
            if f.startswith(("saldo", "captacao")):
                palavra = "saldo" if f.startswith("saldo") else "captacao"
                if palavra not in h:
                    problemas.append(f"campo de {palavra}, cabecalho sem {palavra}")
            elif ("volume" in f or "milhoes" in f) and not any(k in h for k in ("milh", "r$", "rs")):
                problemas.append("campo de volume, cabecalho sem R$/milhoes")
            if f.endswith("_mensais") and re.search(r"ano\d", h) and "mes" not in h:
                problemas.append("campo mensal lendo coluna de acumulado no ano")
            if "acumulad" in f and "ano" not in h:
                problemas.append("campo acumulado lendo coluna que nao e do ano")
            anos = anos_por_tabela.get(u.arquivo) or set()
            if anos and colecao not in {"por_modalidade_e_instituicao"}:
                ano_do_cabecalho = [int(y) for y in re.findall(r"20\d\d", cabecalho)]
                if ano_do_cabecalho and max(ano_do_cabecalho) < max(anos):
                    problemas.append(f"le o ano {max(ano_do_cabecalho)} e a tabela tem {max(anos)}")
            if problemas:
                achados.append(achado(ALERTA, "coluna", f"{colecao}.{campo} <- col {coluna} '{cabecalho}'", "; ".join(problemas)))
    if not achados:
        achados.append(achado(OK, "coluna", "campos", "cabecalhos coerentes com o nome dos campos"))
    return achados


def verificar_celulas(unidades: list[Unidade], tabelas: dict[str, Tabela]) -> list[dict[str, str]]:
    """Celulas numericas que o OCR provavelmente leu errado: ponto no lugar da virgula, letra no meio do numero."""
    suspeitas: list[str] = []
    vistos: set[tuple[str, int, int]] = set()
    for u in unidades:
        tabela = tabelas.get(u.arquivo)
        if tabela is None:
            continue
        colunas = colunas_numericas(u)
        for ini, fim in u.faixas:
            for i in range(ini, fim + 1):
                if i >= len(tabela.linhas) or (u.arquivo, i, -1) in vistos:
                    continue
                for campo, coluna in colunas.items():
                    texto = celula(tabela.linhas[i], coluna)
                    if not texto or texto in {"-", "–", "—"} or (u.arquivo, i, coluna) in vistos:
                        continue
                    vistos.add((u.arquivo, i, coluna))
                    motivo = None
                    if re.fullmatch(r"\d{1,3}(\.\d{3})*\.\d{1,2}", texto) and texto.count(".") >= 1 and not re.fullmatch(r"\d{1,3}(\.\d{3})+", texto):
                        motivo = "ponto no lugar da virgula decimal"
                    elif re.search(r"[A-Za-z]", texto):
                        motivo = "letra dentro do numero"
                    elif parse_flexible_number(texto) is None:
                        motivo = "nao e numero"
                    if motivo:
                        lido = parse_flexible_number(texto)
                        suspeitas.append(f"{tabela.arquivo} linha {i} '{celula(tabela.linhas[i], 0)}' col {coluna} ({campo}): '{texto}' -> {lido}  [{motivo}]")
    if not suspeitas:
        return [achado(OK, "celulas", "colunas numericas", "nenhuma celula suspeita de erro de OCR")]
    return [achado(ALERTA, "celulas", "OCR", "; ".join(suspeitas[:6]) + (f" (+{len(suspeitas) - 6})" if len(suspeitas) > 6 else ""))]


def itens_de_colecao(resolvido: Any, nome: str) -> list[dict[str, Any]]:
    """Itens da colecao ``nome`` onde ela estiver no schema resolvido."""
    if isinstance(resolvido, dict):
        for chave, valor in resolvido.items():
            if chave == nome and isinstance(valor, list):
                return [i for i in valor if isinstance(i, dict)]
            achados = itens_de_colecao(valor, nome)
            if achados:
                return achados
    return []


def item_sem_valor(item: dict[str, Any]) -> bool:
    """Todos os campos numericos do item vieram nulos (ha ao menos um campo numerico/nulo, e nenhum com numero)."""
    campos = [v for v in item.values() if v is None or (isinstance(v, (int, float)) and not isinstance(v, bool))]
    return bool(campos) and all(v is None for v in campos)


COLECOES_PUBLICADAS = (
    "por_modalidade_e_instituicao",
    "serie_historica_anual",
    "serie_mensal_sbpe",
    "saldos_mensais",
    "captacoes_liquidas_mensais",
)


def verificar_itens_vazios(resolvido: Any) -> list[dict[str, str]]:
    achados: list[dict[str, str]] = []
    for nome in COLECOES_PUBLICADAS:
        itens = itens_de_colecao(resolvido, nome)
        vazios = [i for i in itens if item_sem_valor(i)]
        if vazios:
            rotulos = [str((i.get("periodo") or {}).get("rotulo_publicado") or i.get("instituicao_financeira") or "?") for i in vazios]
            achados.append(achado(ALERTA, "itens-vazios", nome, f"{len(vazios)} de {len(itens)} item(ns) sem nenhum valor numerico ({', '.join(rotulos[:6])}{'...' if len(rotulos) > 6 else ''})"))
    return achados


def execucoes_da_release(minio: Any, bucket: str, release: str) -> dict[str, str]:
    """Prefixo de cada execucao do fallback de uma release: {execution_id: prefixo}."""
    achadas: dict[str, str] = {}
    for obj in minio.list_objects(bucket, prefix=RAIZ_FALLBACK, recursive=True):
        match = re.match(rf"({re.escape(RAIZ_FALLBACK)}document_id=[^/]+/execution_id=(dag_valida_e_fallback_llm__{re.escape(release)}__[^/]+)/)", obj.object_name)
        if match:
            achadas[match.group(2)] = match.group(1)
    return dict(sorted(achadas.items()))


def ler(minio: Any, bucket: str, chave: str) -> Any:
    try:
        return json.loads(minio.get_object(bucket, chave).read())
    except Exception:  # noqa: BLE001 - artefato ausente vira None
        return None


def carregar_tabelas(minio: Any, bucket: str, document_id: str, execution_id: str) -> dict[str, Tabela]:
    raiz = next(
        (o.object_name.split("/tables/")[0] + "/" for o in minio.list_objects(bucket, prefix=RAIZ_EXTRACAO, recursive=True) if f"document_id={document_id}/execution_id={execution_id}/extraction/tables/" in o.object_name),
        None,
    )
    tabelas: dict[str, Tabela] = {}
    if raiz is None:
        return tabelas
    for obj in minio.list_objects(bucket, prefix=raiz + "tables/", recursive=True):
        match = re.search(r"/tables/(table\d+)\.json$", obj.object_name)
        if match:
            conteudo = ler(minio, bucket, obj.object_name)
            if isinstance(conteudo, dict):
                tabelas[f"tables/{match.group(1)}.json"] = Tabela(f"tables/{match.group(1)}.json", conteudo)
    return tabelas


def verificar_execucao(minio: Any, bucket: str, execucao: str, prefixo: str) -> dict[str, Any]:
    candidato = ler(minio, bucket, prefixo + "layout_signature_candidato.json") or {}
    mapeamento = candidato.get("mapeamento_canonico") or {}
    document_id = prefixo.split("document_id=")[1].split("/")[0]
    tabelas = carregar_tabelas(minio, bucket, document_id, str(candidato.get("execution_id_origem")))
    unidades = unidades_do_layout(mapeamento, tabelas)
    achados = verificar_cobertura(unidades, tabelas) + verificar_somas(unidades, tabelas) + verificar_identidade(unidades, tabelas) + verificar_colunas(unidades, tabelas) + verificar_celulas(unidades, tabelas)
    escolhidas = []
    for obj in minio.list_objects(bucket, prefix=prefixo + "unidades/", recursive=True):
        if obj.object_name.endswith("selecao_artefatos_layout.json"):
            escolhidas += [str(i.get("path")) for i in (ler(minio, bucket, obj.object_name) or {}).get("artifact_paths", []) if isinstance(i, dict)]
    sem_uso = []
    for metrica in selection_mapping_coverage_metrics(escolhidas, mapeamento):
        if metrica.name == "selecao_tabelas_sem_mapeamento" and metrica.value:
            sem_uso = metrica.metadata.get("tabelas_sem_mapeamento", [])
            achados.append(achado(ALERTA, "cobertura", "selecao", f"tabelas escolhidas e sem mapeamento: {sem_uso}"))
    rotulos = sorted({str(v) for u in unidades for k, v in u.valores.items() if k.endswith("rotulo_publicado")})
    if rotulos:
        achados.append(achado(INFO, "periodo", "layout", f"rotulo de periodo fixo no layout: {rotulos}"))
    resolvido = ler(minio, bucket, prefixo + "revalidation/schema_saida_resolvido.json") or {}
    itens = ((resolvido.get("financiamentos_imobiliarios") or {}).get("por_modalidade_e_instituicao")) or []
    achados += verificar_itens_vazios(resolvido)
    return {
        "execucao": execucao,
        "document_id": document_id,
        "extracao": candidato.get("execution_id_origem"),
        "tabelas": len(tabelas),
        "itens_por_modalidade": len(itens),
        "alertas": sum(1 for a in achados if a["nivel"] == ALERTA),
        "achados": achados,
    }


def main() -> int:
    analisador = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analisador.add_argument("--release", required=True, help="rotulo da release (ATLAS_RELEASE) cujas execucoes do fallback serao verificadas")
    analisador.add_argument("--saida", help="grava o relatorio completo neste JSON")
    analisador.add_argument("--so-alertas", action="store_true", help="mostra so os alertas")
    args = analisador.parse_args()
    minio, bucket = _lote.cliente_minio()
    execucoes = execucoes_da_release(minio, bucket, args.release)
    if not execucoes:
        print(f"nenhuma execucao do fallback da ABECIP para a release '{args.release}'")
        return 1
    relatorio = [verificar_execucao(minio, bucket, e, p) for e, p in execucoes.items()]
    for r in relatorio:
        print(f"\n=== {r['execucao'].split('__', 1)[1]}  extracao={str(r['extracao'])[-18:]}  tabelas={r['tabelas']}  itens por_modalidade={r['itens_por_modalidade']}  ALERTAS={r['alertas']}")
        for a in r["achados"]:
            if args.so_alertas and a["nivel"] != ALERTA:
                continue
            print(f"  [{a['nivel']:<6}] {a['verificacao']:<10} {a['onde']}: {a['texto']}")
    if args.saida:
        Path(args.saida).write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

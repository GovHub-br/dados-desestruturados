"""Simula, sem LLM, o que muda quando o CODIGO decide as faixas de linhas das tabelas inteiras da ABECIP.

Para cada execucao do fallback de uma release, pega o layout que a LLM gerou e troca so as faixas de
`linhas_de_tabela(s)` pelas de `data_row_ranges` (src/.../table_row_ranges.py): a tabela, as colunas e os
valores fixos continuam os que a LLM escolheu. Resolve os dois layouts (o original e o simulado) com o
resolvedor real, sobre a extracao em que foram gerados, e compara:

- alertas do verificador (`verificar_colecoes.py`), por tipo, antes e depois;
- itens publicados em cada colecao, antes e depois;
- no mes com gabarito curado (maio/2026), `assinatura_resolvido_observacoes_*`.

Nao grava nada no MinIO nem aciona o Airflow. Roda no contêiner do Airflow:

    docker exec -w /opt/project/dados-desestruturados ocr_airflow_scheduler python \\
        eval/abecip/simular_faixas_por_codigo.py --release exp-abecip-varios-meses [--detalhe]
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docling" / "scripts"))
import _lote  # noqa: E402
import verificar_colecoes as v  # noqa: E402

from document_processing.application.use_cases.resolution.resolve_schema import (
    ResolveSchemaUseCase,  # noqa: E402
)
from document_processing.domain.fallback.table_row_ranges import (  # noqa: E402
    data_row_ranges,
    is_aggregate_label,
)
from document_processing.domain.observability.signature_evaluation import (
    resolved_observation_metrics,  # noqa: E402
)

RAIZ = Path(__file__).resolve().parents[2]
CONTRATO = RAIZ / "infra/minio-bootstrap/contracts/abecip/v2.3.0/contrato_semantico_abecip.json"
GABARITOS = RAIZ / "eval/gabaritos"
COLECOES = ("por_modalidade_e_instituicao", "serie_historica_anual", "serie_mensal_sbpe", "saldos_mensais", "captacoes_liquidas_mensais")


def achar(obj: Any, chave: str) -> Any:
    if isinstance(obj, dict):
        for k, valor in obj.items():
            if k == chave:
                return valor
            encontrado = achar(valor, chave)
            if encontrado is not None:
                return encontrado
    elif isinstance(obj, list):
        for valor in obj:
            encontrado = achar(valor, chave)
            if encontrado is not None:
                return encontrado
    return None


def baixar_extracao(minio: Any, bucket: str, document_id: str, execution_id: str, destino: Path) -> Path | None:
    raiz = next(
        (
            o.object_name.split("/extraction/")[0] + "/extraction/"
            for o in minio.list_objects(bucket, prefix=v.RAIZ_EXTRACAO, recursive=True)
            if f"document_id={document_id}/execution_id={execution_id}/extraction/" in o.object_name
        ),
        None,
    )
    if raiz is None:
        return None
    for obj in minio.list_objects(bucket, prefix=raiz, recursive=True):
        alvo = destino / obj.object_name[len(raiz):]
        alvo.parent.mkdir(parents=True, exist_ok=True)
        minio.fget_object(bucket, obj.object_name, str(alvo))
    return destino


def trocar_faixa(trecho: dict[str, Any], faixa: tuple[int, int]) -> dict[str, Any] | None:
    """Copia do trecho (fonte ou entrada) com a faixa trocada; ``None`` quando ha mais de uma faixa ou segmento."""
    novo = copy.deepcopy(trecho)
    chave = "segmentos" if trecho.get("segmentos") else "faixas_linhas" if trecho.get("faixas_linhas") else None
    if chave:
        if len(trecho[chave]) != 1:
            return None
        novo[chave][0]["linha_inicial"], novo[chave][0]["linha_final"] = faixa
        return novo
    novo["linha_inicial"], novo["linha_final"] = faixa
    return novo


def colunas_numericas_do_trecho(trecho: dict[str, Any]) -> list[int]:
    """Indices das colunas numericas que o mapeamento le (campos da fonte ou do primeiro segmento)."""
    campos = trecho.get("campos") or next((s["campos"] for s in (trecho.get("segmentos") or trecho.get("faixas_linhas") or []) if s.get("campos")), [])
    return [int(c["indice_coluna"]) for c in campos if c.get("tipo") == "numero" and isinstance(c.get("indice_coluna"), int)]


def aplicar_faixas_do_codigo(mapeamento: dict[str, Any], tabelas: dict[str, v.Tabela]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Layout com as faixas das tabelas inteiras decididas pelo codigo, e o registro de cada troca."""
    novo = copy.deepcopy(mapeamento)
    registro: list[dict[str, Any]] = []

    def processar(caminho: str, trecho: dict[str, Any], arquivo: str) -> dict[str, Any]:
        tabela = tabelas.get(arquivo)
        if tabela is None:
            return trecho
        antes = v.faixas_de(trecho, len(tabela.linhas))
        codigo = data_row_ranges({"schema": tabela.cabecalhos, "rows": tabela.linhas}, colunas=colunas_numericas_do_trecho(trecho))
        item = {"caminho": caminho, "arquivo": arquivo, "layout": antes, "codigo": list(codigo or ()), "n_linhas": len(tabela.linhas)}
        if not codigo or len(codigo) != 1:
            item["acao"] = "mantido (codigo nao deu uma faixa unica)"
            registro.append(item)
            return trecho
        trocado = trocar_faixa(trecho, codigo[0])
        item["acao"] = "trocado" if trocado is not None else "mantido (varias faixas ou segmentos no layout)"
        registro.append(item)
        return trocado or trecho

    for caminho, entrada in novo.items():
        tipo = entrada.get("tipo_origem")
        if tipo == "linhas_de_tabelas":
            entrada["fontes"] = [processar(caminho, f, str(f.get("arquivo_origem"))) for f in entrada.get("fontes") or []]
        elif tipo == "linhas_de_tabela" and str(entrada.get("arquivo_origem", "")).startswith("tables/"):
            novo[caminho] = processar(caminho, entrada, str(entrada.get("arquivo_origem")))
    return novo, registro


def classificar(item: dict[str, Any], tabela: v.Tabela) -> str:
    """Por que a faixa da LLM difere da do codigo."""
    if not item["codigo"]:
        return "-"
    n = item["n_linhas"]
    layout = {i for ini, fim in item["layout"] for i in range(ini, fim + 1)}
    codigo = {i for ini, fim in item["codigo"] for i in range(ini, fim + 1)}
    if layout == codigo:
        return "igual"
    motivos = []
    if any(fim >= n for _, fim in item["layout"]):
        motivos.append(f"passa do fim (fim={max(f for _, f in item['layout'])}, a tabela tem {n} linhas)")
    if any(i < n and is_aggregate_label(tabela.linhas[i][0] if tabela.linhas[i] else "") for i in layout):
        motivos.append("inclui linha de total")
    if min(layout, default=0) > min(codigo):
        motivos.append(f"pula a primeira linha de dados (comeca em {min(layout)}, o codigo em {min(codigo)})")
    if layout - codigo and not motivos:
        motivos.append(f"le linhas que o codigo nao le: {sorted(layout - codigo)[:6]}")
    if codigo - layout and not any("pula" in m for m in motivos):
        motivos.append(f"deixa de ler linhas de dados: {sorted(codigo - layout)[:6]}")
    return "; ".join(motivos) or "diferente"


def resolver(uso: ResolveSchemaUseCase, contrato: dict[str, Any], mapeamento: dict[str, Any], raiz: Path, manifesto: dict[str, Any]) -> dict[str, Any]:
    loaded = {"contrato_semantico": contrato, "layout_signature": {"mapeamento_canonico": mapeamento}, "extraction_root": str(raiz), "manifest": manifesto}
    validacao = {"status_compatibilidade": {"status": "compativel"}}
    return uso.resolve_canonical_mapping(loaded, validacao)["schema_saida"]


def alertas(mapeamento: dict[str, Any], tabelas: dict[str, v.Tabela]) -> dict[str, int]:
    unidades = v.unidades_do_layout(mapeamento, tabelas)
    achados = v.verificar_cobertura(unidades, tabelas) + v.verificar_somas(unidades, tabelas) + v.verificar_identidade(unidades, tabelas) + v.verificar_colunas(unidades, tabelas)
    contagem: dict[str, int] = {}
    for a in achados:
        if a["nivel"] == v.ALERTA:
            contagem[a["verificacao"]] = contagem.get(a["verificacao"], 0) + 1
    return contagem


def contar(schema: dict[str, Any]) -> dict[str, int]:
    return {c: len(achar(schema, c) or []) for c in COLECOES}


def main() -> int:
    analisador = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analisador.add_argument("--release", required=True)
    analisador.add_argument("--detalhe", action="store_true", help="lista cada faixa trocada")
    analisador.add_argument("--saida", help="grava o relatorio em JSON")
    args = analisador.parse_args()

    minio, bucket = _lote.cliente_minio()
    contrato = json.loads(CONTRATO.read_text(encoding="utf-8"))
    gabaritos = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in GABARITOS.glob("*.json")}
    uso = ResolveSchemaUseCase()
    relatorio = []
    for execucao, prefixo in v.execucoes_da_release(minio, bucket, args.release).items():
        candidato = v.ler(minio, bucket, prefixo + "layout_signature_candidato.json") or {}
        document_id = prefixo.split("document_id=")[1].split("/")[0]
        mapeamento = candidato.get("mapeamento_canonico") or {}
        tabelas = v.carregar_tabelas(minio, bucket, document_id, str(candidato.get("execution_id_origem")))
        mes = execucao.rsplit("__", 1)[-1]
        with tempfile.TemporaryDirectory() as temporaria:
            raiz = baixar_extracao(minio, bucket, document_id, str(candidato.get("execution_id_origem")), Path(temporaria))
            if raiz is None or not tabelas:
                print(f"{mes}: extracao nao encontrada")
                continue
            manifesto = json.loads((raiz / "manifesto_execucao.json").read_text(encoding="utf-8")) if (raiz / "manifesto_execucao.json").exists() else {}
            simulado, trocas = aplicar_faixas_do_codigo(mapeamento, tabelas)
            antes = resolver(uso, contrato, mapeamento, raiz, manifesto)
            depois = resolver(uso, contrato, simulado, raiz, manifesto)
        gabarito = gabaritos.get(document_id)
        notas = {}
        if gabarito:
            for rotulo, schema in (("antes", antes), ("depois", depois)):
                notas[rotulo] = {m.name: round(float(m.value), 3) for m in resolved_observation_metrics(schema, gabarito)}
        item = {
            "mes": mes,
            "alertas_antes": alertas(mapeamento, tabelas),
            "alertas_depois": alertas(simulado, tabelas),
            "itens_antes": contar(antes),
            "itens_depois": contar(depois),
            "gabarito": notas,
            "trocas": [{**t, "motivo": classificar(t, tabelas[t["arquivo"]])} for t in trocas],
        }
        relatorio.append(item)
        print(f"\n=== {mes}")
        print(f"  alertas  antes {item['alertas_antes']}  ->  depois {item['alertas_depois']}")
        print(f"  itens    antes {list(item['itens_antes'].values())}  ->  depois {list(item['itens_depois'].values())}   ({', '.join(COLECOES)})")
        if notas:
            print(f"  gabarito {notas}")
        for t in item["trocas"]:
            if args.detalhe or t["motivo"] not in {"igual", "-"}:
                print(f"  - {t['caminho'].rsplit('.', 1)[-1]:32} {t['arquivo']}: layout {t['layout']} codigo {t['codigo']} [{t['acao']}] {t['motivo']}")
    if args.saida:
        Path(args.saida).write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Baixa do MinIO a extração antiga mais recente de cada PDF de `documentos-origem/`.

Somente leitura no MinIO. Grava em `eval/docling_tabelas/extracoes/antigo/<slug>/extraction/`.

A ligação PDF → execução vem do `manifesto_execucao.json` de cada execução
(`input_pdf_uri`), não do nome da pasta. Havendo mais de uma execução para o mesmo PDF,
vale a de `execution_id` mais recente; todas ficam registradas em `meta.json`.

Rodar dentro do contêiner do Airflow:

    docker exec ocr_airflow_scheduler python \
        /opt/project/dados-desestruturados/eval/docling_tabelas/scripts/baixar_extracoes_antigas.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _lote  # noqa: E402


def _carimbo(execution_id: str) -> str:
    achado = re.search(r"(\d{8}T\d{6}Z)$", execution_id)
    return achado.group(1) if achado else ""


def main() -> None:
    analisador = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analisador.add_argument("--refazer", action="store_true", help="baixa de novo mesmo se já existir")
    args = analisador.parse_args()

    cliente, bucket = _lote.cliente_minio()
    pdfs = _lote.listar_pdfs(cliente, bucket)
    por_pdf: dict[str, list[dict]] = defaultdict(list)

    for obj in cliente.list_objects(bucket, prefix=_lote.PREFIXO_EXECUCOES, recursive=True):
        if not obj.object_name.endswith("/extraction/manifesto_execucao.json"):
            continue
        resposta = cliente.get_object(bucket, obj.object_name)
        try:
            manifesto = json.loads(resposta.read())
        finally:
            resposta.close()
            resposta.release_conn()
        uri = str(manifesto.get("input_pdf_uri", ""))
        chave_pdf = uri.removeprefix(f"minio://{bucket}/")
        por_pdf[chave_pdf].append(
            {
                "execution_id": manifesto.get("execution_id", ""),
                "prefixo_extraction": obj.object_name.removesuffix("manifesto_execucao.json"),
                "comando": manifesto.get("command", ""),
            }
        )

    sem_extracao: list[str] = []
    for object_name, _ in pdfs:
        slug = _lote.slug_do_pdf(object_name)
        execucoes = sorted(por_pdf.get(object_name, []), key=lambda e: _carimbo(e["execution_id"]))
        if not execucoes:
            sem_extracao.append(slug)
            print(f"[sem extração antiga] {slug}")
            continue
        escolhida = execucoes[-1]
        destino = _lote.RAIZ_SAIDA / "antigo" / slug
        if (destino / "meta.json").exists() and not args.refazer:
            print(f"[ja existe] {slug}")
            continue
        raiz = destino / "extraction"
        baixados = 0
        for item in cliente.list_objects(bucket, prefix=escolhida["prefixo_extraction"], recursive=True):
            relativo = item.object_name.removeprefix(escolhida["prefixo_extraction"])
            alvo = (raiz / relativo).resolve()
            if raiz.resolve() not in alvo.parents:
                raise SystemExit(f"caminho fora da pasta de destino: {item.object_name}")
            alvo.parent.mkdir(parents=True, exist_ok=True)
            cliente.fget_object(bucket, item.object_name, str(alvo))
            baixados += 1
        meta = {
            "slug": slug,
            "pdf": object_name,
            "execution_id": escolhida["execution_id"],
            "comando": escolhida["comando"],
            "arquivos": baixados,
            "todas_as_execucoes": [e["execution_id"] for e in execucoes],
        }
        (destino / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[baixado] {slug}: {baixados} arquivos de {escolhida['execution_id']} ({len(execucoes)} execução(ões))")

    print(f"\n{len(pdfs)} PDFs; sem extração antiga: {len(sem_extracao)}")


if __name__ == "__main__":
    main()

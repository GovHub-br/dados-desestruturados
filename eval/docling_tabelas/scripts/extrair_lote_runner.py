"""Envia os PDFs de `documentos-origem/` ao runner Docling e guarda a extração em disco local.

Faz o mesmo que a DAG de extração: usa o `DoclingPipelineClient` do projeto, que chama
`POST /extract-file` com os mesmos headers e as mesmas flags (`DOCLING_DO_OCR`,
`DOCLING_DO_CHART_EXTRACTION`, `DOCLING_ENABLE_LLM_TEXT_EXTRACTION` do ambiente).

O que este script NÃO faz, de propósito: não grava nada no MinIO (só lê os PDFs), não
aciona o Airflow e portanto não dispara a DAG de resolução nem a de fallback.

Saída: `eval/docling_tabelas/extracoes/<rotulo>/<slug>/{extraction/,extraction.tar.gz,meta.json}`.
Retomável: PDF com `meta.json` de sucesso é pulado (use `--refazer` para repetir).

Rodar dentro do contêiner do Airflow:

    docker exec ocr_airflow_scheduler python \
        /opt/project/dados-desestruturados/eval/docling_tabelas/scripts/extrair_lote_runner.py \
        --rotulo novo [--filtro abecip] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _lote  # noqa: E402

from document_processing.infrastructure.docling.docling_gateway import DoclingPipelineClient  # noqa: E402


def _healthz(base_url: str) -> str:
    with urllib.request.urlopen(f"{base_url.rstrip('/')}/healthz", timeout=10) as resposta:  # noqa: S310
        return resposta.read().decode("utf-8")


def main() -> None:
    analisador = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analisador.add_argument("--rotulo", required=True, help="nome da pasta de saída, ex.: novo ou controle")
    analisador.add_argument("--filtro", action="append", default=[], help="só PDFs cujo caminho contém o texto (repetível)")
    analisador.add_argument("--dry-run", action="store_true", help="lista o que enviaria e testa o /healthz; não extrai")
    analisador.add_argument("--refazer", action="store_true", help="repete PDFs já extraídos com sucesso")
    args = analisador.parse_args()

    cliente_docling = DoclingPipelineClient()
    config = cliente_docling.config
    flags = {
        "do_ocr": config.docling_do_ocr,
        "do_chart_extraction": config.docling_do_chart_extraction,
        "enable_llm_text_extraction": config.docling_enable_llm_text_extraction,
    }
    print(f"runner: {config.docling_runner_base_url}  flags: {flags}")
    print(f"runner /healthz: {_healthz(config.docling_runner_base_url)}")

    minio, bucket = _lote.cliente_minio()
    pdfs = [
        (nome, tamanho)
        for nome, tamanho in _lote.listar_pdfs(minio, bucket)
        if not args.filtro or any(texto in nome for texto in args.filtro)
    ]
    print(f"{len(pdfs)} PDF(s) selecionado(s), {sum(t for _, t in pdfs) / 1e6:.1f} MB")

    saida = _lote.RAIZ_SAIDA / args.rotulo
    falhas: list[str] = []
    for posicao, (object_name, tamanho) in enumerate(pdfs, start=1):
        slug = _lote.slug_do_pdf(object_name)
        destino = saida / slug
        meta_path = destino / "meta.json"
        if args.dry_run:
            print(f"[dry-run {posicao}/{len(pdfs)}] {slug}  ({tamanho // 1000} KB)  <- {object_name}")
            continue
        if meta_path.exists() and json.loads(meta_path.read_text(encoding="utf-8")).get("status") == "success" and not args.refazer:
            print(f"[{posicao}/{len(pdfs)}] {slug}: já extraído, pulando")
            continue

        carimbo = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        execution_id = f"comparacao-docling-{args.rotulo}-{slug}-{carimbo}"
        meta = {
            "slug": slug,
            "pdf": object_name,
            "rotulo": args.rotulo,
            "execution_id": execution_id,
            "runner": config.docling_runner_base_url,
            "flags": flags,
            "iniciado_em": datetime.now(UTC).isoformat(),
        }
        print(f"[{posicao}/{len(pdfs)}] {slug}: enviando ({tamanho // 1000} KB) execution_id={execution_id}", flush=True)
        inicio = time.monotonic()
        try:
            with tempfile.TemporaryDirectory() as temporaria:
                pdf_local = Path(temporaria) / Path(object_name).name
                minio.fget_object(bucket, object_name, str(pdf_local))
                destino.mkdir(parents=True, exist_ok=True)
                resultado = cliente_docling.run_extract_file_command(
                    input_path=str(pdf_local),
                    output_dir=str(destino / "extraction"),
                    execution_id=execution_id,
                    **flags,
                )
            meta.update(status="success", resultado=resultado)
        except Exception as erro:  # noqa: BLE001 - uma falha não deve parar o lote
            meta.update(status="failed", erro=str(erro)[:3000])
            falhas.append(slug)
        meta["segundos"] = round(time.monotonic() - inicio, 1)
        destino.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[{posicao}/{len(pdfs)}] {slug}: {meta['status']} em {meta['segundos']}s", flush=True)

    if not args.dry_run:
        print(f"\nconcluído: {len(pdfs) - len(falhas)} ok, {len(falhas)} com falha {falhas or ''}")


if __name__ == "__main__":
    main()

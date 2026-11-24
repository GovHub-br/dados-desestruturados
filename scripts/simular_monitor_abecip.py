"""Mostra o que o monitor da ABECIP faria agora, sem gravar nada.

Execute dentro do container Airflow:
docker exec -w /opt/project/dados-desestruturados ocr_airflow_scheduler \
    python scripts/simular_monitor_abecip.py

Baixa os PDFs listados no site (so leitura) e os compara com o MinIO pelo checksum.
Util antes de despausar ``dag_detecta_e_baixa_pdfs_abecip``: o que aparece como
``novo`` ou ``duplicado`` com ``extrair=True`` e o que a DAG enviaria para extracao.
"""
from __future__ import annotations

from dags._shared.dependencies import build_abecip_monitor_use_case


def main() -> int:
    use_case = build_abecip_monitor_use_case()
    candidates = use_case.detect_candidates()
    print(f"{'periodo':8} {'status':18} {'extrair':8} {'documento':14} onde")
    to_extract = 0
    for candidate in candidates:
        inspected = use_case.inspect_candidate(candidate)
        to_extract += int(inspected.should_extract)
        print(
            f"{candidate['period_label']:8} {inspected.status:18} "
            f"{str(inspected.should_extract):8} {inspected.document_id[:12]:14} "
            f"{inspected.existing_pdf_key or '(sera gravado) ' + inspected.pdf_key}"
        )
    print(f"\n{to_extract} documento(s) seguiriam para extracao.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .models import PipelineBundle


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_dataframe(path: Path, rows: list[dict[str, Any]]) -> None:
    pd.DataFrame(rows).to_csv(path, index=False)


def persist_bundle(bundle: PipelineBundle, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    write_json(output_dir / "bundle.json", bundle.model_dump(mode="json"))
    write_json(output_dir / "document.json", bundle.document.model_dump(mode="json"))
    write_json(output_dir / "sections.json", [x.model_dump(mode="json") for x in bundle.sections])
    write_json(output_dir / "metrics.json", [x.model_dump(mode="json") for x in bundle.metrics])
    write_json(output_dir / "tables.json", [x.model_dump(mode="json") for x in bundle.tables])
    write_json(output_dir / "charts.json", [x.model_dump(mode="json") for x in bundle.charts])
    write_json(
        output_dir / "normalized_rows.json",
        [x.model_dump(mode="json") for x in bundle.normalized_rows],
    )

    write_dataframe(output_dir / "sections.csv", [x.model_dump(mode="json") for x in bundle.sections])
    write_dataframe(output_dir / "metrics.csv", [x.model_dump(mode="json") for x in bundle.metrics])
    write_dataframe(output_dir / "charts.csv", [x.model_dump(mode="json") for x in bundle.charts])
    write_dataframe(
        output_dir / "normalized_rows.csv",
        [x.model_dump(mode="json") for x in bundle.normalized_rows],
    )

    flat_cells: list[dict[str, Any]] = []
    for table in bundle.tables:
        base = {
            "table_id": table.table_id,
            "document_id": table.document_id,
            "page_number": table.page_number,
            "section_id": table.section_id,
            "section_title": table.section_title,
            "title_raw": table.title_raw,
            "title_canonical": table.title_canonical,
        }
        for cell in table.cells:
            flat_cells.append({**base, **cell.model_dump(mode="json")})
    write_dataframe(output_dir / "table_cells.csv", flat_cells)

    if bundle.semantic_markdown:
        (output_dir / "semantic_markdown.md").write_text(bundle.semantic_markdown, encoding="utf-8")

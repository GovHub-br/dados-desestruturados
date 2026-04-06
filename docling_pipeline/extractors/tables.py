from __future__ import annotations

from typing import Any

import pandas as pd

try:
    from docling_core.types.doc import TableItem
except Exception:  # pragma: no cover
    TableItem = object  # type: ignore[assignment]

from ..helpers import dataframe_to_cell_records, item_bbox, item_page_number, slugify, stable_id
from ..models import NormalizedRowRecord, SectionRecord, TableRecord
from .common import dataframe_to_normalized_rows, resolve_section_for_item


def extract_tables(
    document_id: str,
    conv_res: Any,
    sections: list[SectionRecord],
) -> tuple[list[TableRecord], list[NormalizedRowRecord]]:
    tables: list[TableRecord] = []
    normalized_rows: list[NormalizedRowRecord] = []

    for idx, (item, _level) in enumerate(conv_res.document.iterate_items()):
        if not isinstance(item, TableItem):
            continue

        page_number = item_page_number(item)
        bbox = item_bbox(item)
        section = resolve_section_for_item(
            sections,
            item=item,
            page_number=page_number,
            anchor_bbox=bbox,
            order_index=idx,
        )
        table_id = stable_id(document_id, "table", page_number, idx)

        try:
            df = item.export_to_dataframe()
        except Exception:
            df = pd.DataFrame()

        columns_raw, cells = dataframe_to_cell_records(df)
        title_raw = section.title_raw if section else None
        title_canonical = slugify(title_raw) if title_raw else None

        tables.append(
            TableRecord(
                table_id=table_id,
                document_id=document_id,
                page_number=page_number,
                section_id=section.section_id if section else None,
                section_title=section.title_raw if section else None,
                title_raw=title_raw,
                title_canonical=title_canonical,
                bbox=bbox,
                columns_raw=columns_raw,
                cells=cells,
                row_count=len(df.index),
                column_count=len(df.columns),
            )
        )
        normalized_rows.extend(
            dataframe_to_normalized_rows(
                df=df,
                document_id=document_id,
                page_number=page_number,
                source_kind="table",
                source_id=table_id,
                section=section,
                domain_hint=title_raw,
            )
        )
    return tables, normalized_rows

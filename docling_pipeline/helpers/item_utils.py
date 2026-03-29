from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from ..models import BoundingBox, TableCellRecord
from .text_utils import normalize_space


def item_text(item: Any) -> str:
    for attr in ("text", "orig", "orig_text"):
        value = getattr(item, attr, None)
        if isinstance(value, str) and value.strip():
            return normalize_space(value)

    if hasattr(item, "export_to_markdown"):
        try:
            value = item.export_to_markdown()
            if isinstance(value, str) and value.strip():
                return normalize_space(value)
        except Exception:
            pass

    return ""


def item_label(item: Any) -> str:
    label = getattr(item, "label", None)
    if label is None:
        return item.__class__.__name__.lower()
    if hasattr(label, "value"):
        return str(label.value).lower()
    return str(label).lower()


def item_page_number(item: Any) -> Optional[int]:
    prov = getattr(item, "prov", None)
    if prov:
        page_no = getattr(prov[0], "page_no", None)
        if page_no is not None:
            return int(page_no)
    return None


def item_bbox(item: Any) -> Optional[BoundingBox]:
    prov = getattr(item, "prov", None)
    if not prov:
        return None

    first = prov[0]
    bbox = getattr(first, "bbox", None)
    if bbox is None:
        return BoundingBox(page_number=getattr(first, "page_no", None))

    return BoundingBox(
        page_number=getattr(first, "page_no", None),
        left=getattr(bbox, "l", None),
        top=getattr(bbox, "t", None),
        right=getattr(bbox, "r", None),
        bottom=getattr(bbox, "b", None),
        coord_origin=getattr(bbox, "coord_origin", None),
    )


def dataframe_to_cell_records(df: pd.DataFrame) -> tuple[list[str], list[TableCellRecord]]:
    columns_raw = [normalize_space(str(col)) for col in df.columns.tolist()]
    cells: list[TableCellRecord] = []
    for row_idx, row in enumerate(df.fillna("").values.tolist()):
        for col_idx, value in enumerate(row):
            cells.append(
                TableCellRecord(
                    row_index=row_idx,
                    column_index=col_idx,
                    value_raw=normalize_space(str(value)),
                )
            )
    return columns_raw, cells


def chart_grid_to_dataframe(chart_data: Any) -> pd.DataFrame:
    grid = [["" for _ in range(chart_data.num_cols)] for _ in range(chart_data.num_rows)]
    for cell in getattr(chart_data, "table_cells", []) or []:
        row_idx = getattr(cell, "start_row_offset_idx", 0)
        col_idx = getattr(cell, "start_col_offset_idx", 0)
        if row_idx < chart_data.num_rows and col_idx < chart_data.num_cols:
            grid[row_idx][col_idx] = normalize_space(getattr(cell, "text", ""))

    if not grid:
        return pd.DataFrame()

    header = grid[0]
    body = grid[1:] if len(grid) > 1 else []

    if any(h.strip() for h in header):
        return pd.DataFrame(body, columns=header)
    return pd.DataFrame(grid)

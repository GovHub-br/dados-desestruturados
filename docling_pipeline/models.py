from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    page_number: Optional[int] = None
    left: Optional[float] = None
    top: Optional[float] = None
    right: Optional[float] = None
    bottom: Optional[float] = None
    coord_origin: Optional[str] = None


class DocumentRecord(BaseModel):
    document_id: str
    source_file: str
    source_stem: str
    pipeline_mode: str
    num_pages: Optional[int] = None
    semantic_markdown_available: bool = False


class SectionRecord(BaseModel):
    section_id: str
    document_id: str
    page_number: Optional[int] = None
    title_raw: str
    title_canonical: str
    level_hint: Optional[int] = None
    bbox: Optional[BoundingBox] = None
    provenance_kind: str = "layout"


class MetricRecord(BaseModel):
    metric_id: str
    document_id: str
    page_number: Optional[int] = None
    section_id: Optional[str] = None
    section_title: Optional[str] = None
    label_raw: str
    label_canonical: str
    value_numeric: Optional[float] = None
    value_text: Optional[str] = None
    unit_hint: Optional[str] = None
    bbox: Optional[BoundingBox] = None
    extraction_method: str = "text_heuristic"


class TableCellRecord(BaseModel):
    row_index: int
    column_index: int
    value_raw: str


class TableRecord(BaseModel):
    table_id: str
    document_id: str
    page_number: Optional[int] = None
    section_id: Optional[str] = None
    section_title: Optional[str] = None
    title_raw: Optional[str] = None
    title_canonical: Optional[str] = None
    bbox: Optional[BoundingBox] = None
    columns_raw: list[str] = Field(default_factory=list)
    cells: list[TableCellRecord] = Field(default_factory=list)
    row_count: int = 0
    column_count: int = 0


class ChartPointRecord(BaseModel):
    point_id: str
    document_id: str
    chart_id: str
    page_number: Optional[int] = None
    section_id: Optional[str] = None
    section_title: Optional[str] = None
    chart_type: Optional[str] = None
    chart_title_raw: Optional[str] = None
    chart_title_canonical: Optional[str] = None
    series_name: Optional[str] = None
    category_name: Optional[str] = None
    value_numeric: Optional[float] = None
    value_text: Optional[str] = None
    raw_row: dict[str, Any] = Field(default_factory=dict)


class NormalizedRowRecord(BaseModel):
    record_id: str
    document_id: str
    page_number: Optional[int] = None
    source_kind: str
    source_id: str
    section_id: Optional[str] = None
    section_title: Optional[str] = None
    domain: str
    grain: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    measures: dict[str, Any] = Field(default_factory=dict)


class PipelineBundle(BaseModel):
    document: DocumentRecord
    sections: list[SectionRecord] = Field(default_factory=list)
    metrics: list[MetricRecord] = Field(default_factory=list)
    tables: list[TableRecord] = Field(default_factory=list)
    charts: list[ChartPointRecord] = Field(default_factory=list)
    normalized_rows: list[NormalizedRowRecord] = Field(default_factory=list)
    semantic_markdown: Optional[str] = None

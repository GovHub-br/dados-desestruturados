from __future__ import annotations

from typing import Any

from ..helpers import infer_unit_hint, item_bbox, item_page_number, item_text, maybe_metric_from_text, slugify, stable_id
from ..models import MetricRecord, SectionRecord
from .common import nearest_section


def extract_metrics(
    document_id: str,
    conv_res: Any,
    sections: list[SectionRecord],
) -> list[MetricRecord]:
    metrics: list[MetricRecord] = []
    seen: set[str] = set()

    for idx, (item, _level) in enumerate(conv_res.document.iterate_items()):
        text = item_text(item)
        if not text:
            continue
        parsed = maybe_metric_from_text(text)
        if parsed is None:
            continue

        label_raw, value_numeric, value_text = parsed
        page_number = item_page_number(item)
        bbox = item_bbox(item)
        section = nearest_section(sections, page_number=page_number, anchor_bbox=bbox)
        metric_id = stable_id(document_id, "metric", page_number, idx, label_raw, value_text)
        if metric_id in seen:
            continue
        seen.add(metric_id)

        metrics.append(
            MetricRecord(
                metric_id=metric_id,
                document_id=document_id,
                page_number=page_number,
                section_id=section.section_id if section else None,
                section_title=section.title_raw if section else None,
                label_raw=label_raw,
                label_canonical=slugify(label_raw),
                value_numeric=value_numeric,
                value_text=value_text,
                unit_hint=infer_unit_hint(text),
                bbox=bbox,
            )
        )
    return metrics

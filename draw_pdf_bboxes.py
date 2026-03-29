#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from PIL import Image
from reportlab.lib.colors import Color
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


DEFAULT_PDF = Path("docling_pipeline/dados.pdf")
DEFAULT_SECTIONS = Path("saida/sections.json")
DEFAULT_TABLES = Path("saida/tables.json")
DEFAULT_METRICS = Path("saida/metrics.json")
DEFAULT_CHARTS = Path("saida/charts.json")
DEFAULT_OUTPUT = Path("saida/sections_annotated.pdf")
PAGE_SIZE = (960, 540)
RECT_COLOR = Color(1, 0, 0, alpha=0.85)
LABEL_COLOR = Color(1, 0, 0, alpha=1)
SOURCE_COLORS = {
    "sections": Color(1, 0, 0, alpha=0.85),
    "tables": Color(0, 0.45, 1, alpha=0.85),
    "metrics": Color(0, 0.65, 0.2, alpha=0.85),
    "charts": Color(1, 0.55, 0, alpha=0.85),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Desenha retangulos dos bboxes de sections, tables, metrics e charts sobre um PDF."
    )
    parser.add_argument(
        "--pdf",
        type=Path,
        default=DEFAULT_PDF,
        help=f"PDF de entrada. Padrao: {DEFAULT_PDF}",
    )
    parser.add_argument(
        "--sections",
        type=Path,
        default=DEFAULT_SECTIONS,
        help=f"JSON de sections. Padrao: {DEFAULT_SECTIONS}",
    )
    parser.add_argument(
        "--tables",
        type=Path,
        default=DEFAULT_TABLES,
        help=f"JSON de tables. Padrao: {DEFAULT_TABLES}",
    )
    parser.add_argument(
        "--metrics",
        type=Path,
        default=DEFAULT_METRICS,
        help=f"JSON de metrics. Padrao: {DEFAULT_METRICS}",
    )
    parser.add_argument(
        "--charts",
        type=Path,
        default=DEFAULT_CHARTS,
        help=f"JSON de charts. Padrao: {DEFAULT_CHARTS}",
    )
    parser.add_argument(
        "--json",
        dest="json_paths",
        type=Path,
        action="append",
        default=[],
        help=(
            "JSON adicional com bboxes. Pode repetir a flag para combinar "
            "ou complementar as fontes padrao."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"PDF anotado de saida. Padrao: {DEFAULT_OUTPUT}",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=144,
        help="Resolucao usada para rasterizar o PDF antes de anotar.",
    )
    parser.add_argument(
        "--no-labels",
        action="store_true",
        help="Nao desenha o titulo da secao ao lado do retangulo.",
    )
    return parser.parse_args()


def infer_source_name(path: Path) -> str:
    name = path.stem.lower()
    if name.endswith("_annotated"):
        name = name.removesuffix("_annotated")
    return name


def infer_label(item: dict) -> str:
    for key in (
        "title_raw",
        "section_title",
        "label_raw",
        "title_canonical",
        "section_id",
        "table_id",
        "metric_id",
    ):
        value = item.get(key)
        if value:
            return str(value)
    return "bbox"


def load_bbox_records(json_paths: Iterable[Path]) -> dict[int, list[dict]]:
    grouped: dict[int, list[dict]] = defaultdict(list)
    for json_path in json_paths:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        source_name = infer_source_name(json_path)
        for item in data:
            bbox = item.get("bbox") or {}
            page_number = int(item.get("page_number") or bbox.get("page_number") or 0)
            if page_number < 1:
                continue
            if bbox.get("left") is None or bbox.get("right") is None:
                continue
            if bbox.get("top") is None or bbox.get("bottom") is None:
                continue
            if bbox.get("coord_origin") != "BOTTOMLEFT":
                raise ValueError(
                    f"Origem de coordenadas nao suportada na pagina {page_number}: "
                    f"{bbox.get('coord_origin')!r}"
                )
            enriched = dict(item)
            enriched["_source_name"] = source_name
            enriched["_label"] = infer_label(item)
            grouped[page_number].append(enriched)
    return grouped


def rasterize_pdf(pdf_path: Path, dpi: int, tmp_dir: Path) -> list[Path]:
    prefix = tmp_dir / "page"
    command = [
        "pdftoppm",
        "-png",
        "-r",
        str(dpi),
        str(pdf_path),
        str(prefix),
    ]
    subprocess.run(command, check=True)
    return sorted(tmp_dir.glob("page-*.png"))


def draw_page(
    pdf_canvas: canvas.Canvas,
    image_path: Path,
    sections: list[dict],
    show_labels: bool,
) -> None:
    with Image.open(image_path) as img:
        width, height = img.size
        page_size = (float(width), float(height))
        pdf_canvas.setPageSize(page_size)
        pdf_canvas.drawImage(ImageReader(img.copy()), 0, 0, width=width, height=height)

    scale_x = width / PAGE_SIZE[0]
    scale_y = height / PAGE_SIZE[1]

    pdf_canvas.setStrokeColor(RECT_COLOR)
    pdf_canvas.setLineWidth(max(1.0, min(scale_x, scale_y) * 1.5))

    for item in sections:
        bbox = item.get("bbox") or {}
        left = float(bbox.get("left", 0)) * scale_x
        right = float(bbox.get("right", 0)) * scale_x
        top = float(bbox.get("top", 0)) * scale_y
        bottom = float(bbox.get("bottom", 0)) * scale_y

        x = min(left, right)
        y = min(bottom, top)
        rect_width = abs(right - left)
        rect_height = abs(top - bottom)

        if rect_width <= 0 or rect_height <= 0:
            continue

        pdf_canvas.setStrokeColor(SOURCE_COLORS.get(item.get("_source_name", ""), RECT_COLOR))
        pdf_canvas.rect(x, y, rect_width, rect_height, stroke=1, fill=0)

        if not show_labels:
            continue

        label = f"{item.get('_source_name', 'bbox')}: {item.get('_label', 'bbox')}"
        label_x = x
        label_y = min(height - 10, max(10, y + rect_height + 4))
        pdf_canvas.setFillColor(SOURCE_COLORS.get(item.get("_source_name", ""), LABEL_COLOR))
        pdf_canvas.setFont("Helvetica", 8)
        pdf_canvas.drawString(label_x, label_y, str(label))

    pdf_canvas.showPage()


def main() -> None:
    args = parse_args()

    if not args.pdf.exists():
        raise FileNotFoundError(f"PDF nao encontrado: {args.pdf}")

    json_paths = [
        args.sections,
        args.tables,
        args.metrics,
        args.charts,
        *args.json_paths,
    ]
    for json_path in json_paths:
        if not json_path.exists():
            raise FileNotFoundError(f"JSON nao encontrado: {json_path}")

    grouped_sections = load_bbox_records(json_paths)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="pdf_bbox_") as tmp:
        image_paths = rasterize_pdf(args.pdf, args.dpi, Path(tmp))

        pdf_canvas = canvas.Canvas(str(args.output))
        for page_index, image_path in enumerate(image_paths, start=1):
            draw_page(
                pdf_canvas,
                image_path,
                grouped_sections.get(page_index, []),
                show_labels=not args.no_labels,
            )
        pdf_canvas.save()

    print(f"PDF anotado gerado em: {args.output}")


if __name__ == "__main__":
    main()

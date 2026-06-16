from __future__ import annotations

import importlib.util
from pathlib import Path


def _find_module_file(module_name: str) -> Path:
    spec = importlib.util.find_spec(module_name)
    if spec is None or spec.origin is None:
        raise RuntimeError(f"Modulo nao encontrado para patch: {module_name}")
    return Path(spec.origin)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _replace_once(content: str, old: str, new: str, *, file_label: str) -> str:
    if new in content:
        return content
    if old not in content:
        raise RuntimeError(f"Trecho esperado nao encontrado em {file_label}")
    return content.replace(old, new, 1)


def _patch_transformers_masking_utils() -> str:
    module_name = "transformers.masking_utils"
    path = _find_module_file(module_name)
    content = _read_text(path)

    content = _replace_once(
        content,
        "    past_key_values: Cache | None,\n    position_ids: torch.Tensor | None = None,\n",
        (
            "    past_key_values: Cache | None,\n"
            "    cache_position: torch.Tensor | None = None,\n"
            "    position_ids: torch.Tensor | None = None,\n"
        ),
        file_label=module_name,
    )

    _write_text(path, content)
    return str(path)


def _patch_transformers_rt_detr_v2() -> str:
    module_name = "transformers.models.rt_detr_v2.modeling_rt_detr_v2"
    path = _find_module_file(module_name)
    content = _read_text(path)

    original_block = """    pos_dim = embed_dim // 4
    omega = torch.arange(pos_dim, dtype=torch.float64, device=device) / pos_dim
    omega = 1.0 / temperature**omega  # (D/4,)

    grid_h = torch.arange(height, dtype=torch.float64, device=device)
    grid_w = torch.arange(width, dtype=torch.float64, device=device)
    grid_h, grid_w = torch.meshgrid(grid_h, grid_w, indexing="ij")  # (H, W) each
"""
    patched_block = """    pos_dim = embed_dim // 4
    device_type = torch.device(device).type if device is not None else None
    arange_dtype = torch.float32 if device_type == "mps" else torch.float64
    omega = torch.arange(pos_dim, dtype=arange_dtype, device=device) / pos_dim
    omega = 1.0 / temperature**omega  # (D/4,)

    grid_h = torch.arange(height, dtype=arange_dtype, device=device)
    grid_w = torch.arange(width, dtype=arange_dtype, device=device)
    grid_h, grid_w = torch.meshgrid(grid_h, grid_w, indexing="ij")  # (H, W) each
"""
    content = _replace_once(content, original_block, patched_block, file_label=module_name)
    content = _replace_once(
        content,
        "        pos_embed = torch.cat([torch.zeros(1, embed_dim, dtype=torch.float64, device=device), pos_embed], dim=0)\n",
        "        pos_embed = torch.cat([torch.zeros(1, embed_dim, dtype=arange_dtype, device=device), pos_embed], dim=0)\n",
        file_label=module_name,
    )

    _write_text(path, content)
    return str(path)


def _patch_docling_chart_extraction() -> str:
    module_name = "docling.models.stages.chart_extraction.granite_vision"
    path = _find_module_file(module_name)
    content = _read_text(path)

    helper = """

def _safe_model_max_length(raw_value: Any, default: int = 1024) -> int:
    \"\"\"Clamp tokenizer sentinel values before using them as generation limits.\"\"\"
    try:
        value = int(raw_value)
    except (TypeError, ValueError, OverflowError):
        return default
    if value <= 0 or value > default:
        return default
    return value
"""
    content = _replace_once(
        content,
        "_log = logging.getLogger(__name__)\n",
        f"_log = logging.getLogger(__name__)\n{helper}",
        file_label=module_name,
    )
    content = _replace_once(
        content,
        "                supported_devices=[AcceleratorDevice.CPU, AcceleratorDevice.CUDA],\n",
        (
            "                supported_devices=[\n"
            "                    AcceleratorDevice.CPU,\n"
            "                    AcceleratorDevice.CUDA,\n"
            "                    AcceleratorDevice.MPS,\n"
            "                ],\n"
        ),
        file_label=module_name,
    )
    content = _replace_once(
        content,
        "            self._load_model(artifacts_path)\n",
        "            self._load_model(artifacts_path)\n            if self.device == \"mps\":\n                self.elements_batch_size = 1\n",
        file_label=module_name,
    )
    content = _replace_once(
        content,
        "        self._model_max_length = self._processor.tokenizer.model_max_length\n",
        "        self._model_max_length = _safe_model_max_length(self._processor.tokenizer.model_max_length, default=1024)\n",
        file_label=module_name,
    )
    content = _replace_once(
        content,
        "            self._model_max_length = self._processor.tokenizer.model_max_length\n",
        "            self._model_max_length = _safe_model_max_length(self._processor.tokenizer.model_max_length, default=4096)\n",
        file_label=module_name,
    )

    _write_text(path, content)
    return str(path)


def _patch_docling_table_structure() -> str:
    module_name = "docling.models.stages.table_structure.table_structure_model_granite_vision"
    path = _find_module_file(module_name)
    content = _read_text(path)

    helper = """

def _safe_model_max_length(raw_value: Any, default: int = 4096) -> int:
    \"\"\"Clamp tokenizer sentinel values before using them as generation limits.\"\"\"
    try:
        value = int(raw_value)
    except (TypeError, ValueError, OverflowError):
        return default
    if value <= 0 or value > default:
        return default
    return value
"""
    content = _replace_once(
        content,
        "_log = logging.getLogger(__name__)\n",
        f"_log = logging.getLogger(__name__)\n{helper}",
        file_label=module_name,
    )
    content = _replace_once(
        content,
        "                supported_devices=[AcceleratorDevice.CPU, AcceleratorDevice.CUDA],\n",
        (
            "                supported_devices=[\n"
            "                    AcceleratorDevice.CPU,\n"
            "                    AcceleratorDevice.CUDA,\n"
            "                    AcceleratorDevice.MPS,\n"
            "                ],\n"
        ),
        file_label=module_name,
    )
    content = _replace_once(
        content,
        "            self._model_max_length = self._processor.tokenizer.model_max_length\n",
        "            self._model_max_length = _safe_model_max_length(self._processor.tokenizer.model_max_length, default=4096)\n",
        file_label=module_name,
    )

    _write_text(path, content)
    return str(path)


def main() -> None:
    patched_files = [
        _patch_transformers_masking_utils(),
        _patch_transformers_rt_detr_v2(),
        _patch_docling_chart_extraction(),
        _patch_docling_table_structure(),
    ]
    print("Applied VLM compatibility patches:")
    for patched in patched_files:
        print(f" - {patched}")


if __name__ == "__main__":
    main()

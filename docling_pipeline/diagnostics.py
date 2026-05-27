from __future__ import annotations

import os
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional


class Diagnostics:
    def __init__(self, output_dir: Path, enabled: bool, interval_seconds: float = 5.0):
        self.enabled = enabled
        self.interval_seconds = max(1.0, interval_seconds)
        self.log_path = output_dir / "diagnostics.log"
        self._stop_event = threading.Event()
        self._monitor_thread: Optional[threading.Thread] = None
        self._started_at = time.monotonic()

        if self.enabled:
            output_dir.mkdir(parents=True, exist_ok=True)
            os.environ["DOCLING_INTERNAL_DIAGNOSTICS"] = "1"

    def log(self, message: str) -> None:
        if not self.enabled:
            return

        elapsed = time.monotonic() - self._started_at
        line = f"[diag +{elapsed:8.2f}s pid={os.getpid()}] {message}"
        print(line, file=sys.stderr, flush=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def log_environment(self) -> None:
        if not self.enabled:
            return

        self.log(f"python={sys.version.split()[0]} executable={sys.executable}")
        self.log(f"platform={platform.platform()} machine={platform.machine()}")
        for key in (
            "DOCLING_DEVICE",
            "PYTORCH_ENABLE_MPS_FALLBACK",
            "PYTORCH_MPS_HIGH_WATERMARK_RATIO",
            "PYTORCH_MPS_LOW_WATERMARK_RATIO",
            "OMP_NUM_THREADS",
        ):
            self.log(f"env {key}={os.getenv(key)!r}")

        try:
            import torch

            self.log(
                "torch="
                f"{torch.__version__} "
                f"mps_built={torch.backends.mps.is_built()} "
                f"mps_available={torch.backends.mps.is_available()}"
            )
        except Exception as exc:
            self.log(f"torch diagnostics failed: {exc!r}")

    def start_monitor(self, label: str) -> None:
        if not self.enabled or self._monitor_thread is not None:
            return

        self.log(f"monitor start: {label}")
        self._stop_event.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            args=(label,),
            daemon=True,
        )
        self._monitor_thread.start()

    def stop_monitor(self, label: str) -> None:
        if not self.enabled or self._monitor_thread is None:
            return

        self._stop_event.set()
        self._monitor_thread.join(timeout=self.interval_seconds + 1.0)
        self._monitor_thread = None
        self.log(f"monitor stop: {label}")

    def _monitor_loop(self, label: str) -> None:
        while not self._stop_event.wait(self.interval_seconds):
            self.log(f"monitor {label}: {self._process_snapshot()}")

    def _process_snapshot(self) -> str:
        try:
            output = subprocess.check_output(
                [
                    "ps",
                    "-o",
                    "rss=,vsz=,%cpu=,%mem=,etime=",
                    "-p",
                    str(os.getpid()),
                ],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            if output:
                return "rss_kb vsz_kb cpu mem etime = " + " ".join(output.split())
        except Exception as exc:
            return f"ps snapshot failed: {exc!r}"
        return "ps snapshot unavailable"

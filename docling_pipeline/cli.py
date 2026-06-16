from __future__ import annotations

import logging
import warnings

from .config import parse_args
from .diagnostics import Diagnostics
from .persistence import persist_bundle
from .pipeline import run_pipeline


def configure_runtime_messages() -> None:
    # Granite Vision and some remote-code model loaders still emit this warning even
    # when the underlying libraries already support the newer `dtype` argument.
    warnings.filterwarnings(
        "ignore",
        message=r".*torch_dtype.*deprecated.*dtype.*",
        category=UserWarning,
    )

    # Public HF Hub downloads work without a token, but the auth reminder is noisy
    # for local runs where public artifacts are expected.
    logging.getLogger("huggingface_hub").setLevel(logging.ERROR)


def main() -> None:
    configure_runtime_messages()
    config = parse_args()
    diagnostics = Diagnostics(
        config.output_dir,
        enabled=config.diagnostics,
        interval_seconds=config.diagnostics_interval,
    )
    diagnostics.log_environment()
    bundle = run_pipeline(config, diagnostics=diagnostics)
    diagnostics.log("persist bundle: starting")
    persist_bundle(bundle, config.output_dir)
    diagnostics.log("persist bundle: finished")
    print(f"OK - outputs written to {config.output_dir}")


if __name__ == "__main__":
    main()

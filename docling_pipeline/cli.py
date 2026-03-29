from __future__ import annotations

from .config import parse_args
from .persistence import persist_bundle
from .pipeline import run_pipeline


def main() -> None:
    config = parse_args()
    bundle = run_pipeline(config)
    persist_bundle(bundle, config.output_dir)
    print(f"OK - outputs written to {config.output_dir}")


if __name__ == "__main__":
    main()

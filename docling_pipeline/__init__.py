from .config import RuntimeConfig


def run_pipeline(*args, **kwargs):
    from .pipeline import run_pipeline as _run_pipeline

    return _run_pipeline(*args, **kwargs)


def persist_bundle(*args, **kwargs):
    from .persistence import persist_bundle as _persist_bundle

    return _persist_bundle(*args, **kwargs)

__all__ = ["RuntimeConfig", "run_pipeline", "persist_bundle"]

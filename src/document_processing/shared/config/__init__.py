"""Configuração compartilhada da plataforma."""
"""Configuração e caminhos independentes de orquestrador."""

from .project_paths import PROJECT_PATHS, ProjectPaths
from .runtime import RUNTIME_CONFIG_LOADER, LocalPlatformConfig, RuntimeConfigLoader

__all__ = [
    "PROJECT_PATHS",
    "ProjectPaths",
    "RUNTIME_CONFIG_LOADER",
    "LocalPlatformConfig",
    "RuntimeConfigLoader",
]

"""
Plugin interfaces and execution helpers.
"""

from .base import SimulationPlugin
from .executor import PluginExecutor
from .registry import PluginRegistry, build_default_registry

__all__ = ["PluginExecutor", "PluginRegistry", "SimulationPlugin", "build_default_registry"]

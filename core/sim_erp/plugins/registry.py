"""
Plugin registry for built-in and future external plugins.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Type

from .base import SimulationPlugin
from .builtin import FactoryBreakPolicyPlugin, JohnsonGlobalStandardPlugin, VNLabor2024Plugin


class PluginRegistry:
    def __init__(self):
        self._plugins: Dict[str, Type[SimulationPlugin]] = {}

    def register(self, plugin_cls: Type[SimulationPlugin]) -> None:
        plugin = plugin_cls()
        self._plugins[plugin.manifest.plugin_name] = plugin_cls

    def get(self, plugin_name: str) -> SimulationPlugin:
        plugin_cls = self._plugins[plugin_name]
        return plugin_cls()

    def create_many(self, plugin_names: Iterable[str]) -> List[SimulationPlugin]:
        return [self.get(plugin_name) for plugin_name in plugin_names]

    def list_manifests(self) -> List[dict]:
        manifests = [plugin_cls().manifest.model_dump(mode="json") for plugin_cls in self._plugins.values()]
        return sorted(manifests, key=lambda item: item["plugin_name"])


def build_default_registry() -> PluginRegistry:
    registry = PluginRegistry()
    registry.register(VNLabor2024Plugin)
    registry.register(JohnsonGlobalStandardPlugin)
    registry.register(FactoryBreakPolicyPlugin)
    return registry

"""
Sandbox-oriented plugin executor.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from hashlib import sha256
from typing import Any, Dict, Iterable, List

from ..models import PhysicalSnapshot, PluginExecutionRecord
from .base import SimulationPlugin


class PluginExecutor:
    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers

    def execute_plugins(
        self,
        snapshot: PhysicalSnapshot,
        plugins: Iterable[SimulationPlugin],
        legislation_catalog: Dict[str, Dict[str, Any]],
    ) -> List[PluginExecutionRecord]:
        records: List[PluginExecutionRecord] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = []
            for plugin in plugins:
                manifest = plugin.manifest
                self._validate_manifest(manifest)
                legislation_pack = legislation_catalog.get(manifest.legislation_pack or "", {})
                futures.append((plugin, legislation_pack, pool.submit(plugin.evaluate, snapshot, legislation_pack)))

            for plugin, _, future in futures:
                started = time.perf_counter()
                try:
                    decisions = future.result(timeout=plugin.manifest.timeout_ms / 1000)
                    duration_ms = (time.perf_counter() - started) * 1000
                    records.append(
                        PluginExecutionRecord(
                            manifest=plugin.manifest,
                            duration_ms=round(duration_ms, 3),
                            decisions=decisions,
                            status="ok",
                        )
                    )
                except TimeoutError:
                    duration_ms = (time.perf_counter() - started) * 1000
                    records.append(
                        PluginExecutionRecord(
                            manifest=plugin.manifest,
                            duration_ms=round(duration_ms, 3),
                            status="timeout",
                            error="Plugin execution exceeded timeout.",
                        )
                    )
                except Exception as exc:
                    duration_ms = (time.perf_counter() - started) * 1000
                    records.append(
                        PluginExecutionRecord(
                            manifest=plugin.manifest,
                            duration_ms=round(duration_ms, 3),
                            status="error",
                            error=str(exc),
                        )
                    )
        return records

    @staticmethod
    def hash_manifests(plugins: Iterable[SimulationPlugin]) -> str:
        payload = [
            plugin.manifest.model_dump(mode="json")
            for plugin in sorted(plugins, key=lambda item: item.manifest.plugin_name)
        ]
        body = str(payload).encode("utf-8")
        return sha256(body).hexdigest()

    def _validate_manifest(self, manifest) -> None:
        if manifest.allow_database:
            raise ValueError(f"{manifest.plugin_name} cannot request database access.")
        if manifest.allow_network:
            raise ValueError(f"{manifest.plugin_name} cannot request network access.")
        if manifest.allow_state_mutation:
            raise ValueError(f"{manifest.plugin_name} cannot request state mutation.")

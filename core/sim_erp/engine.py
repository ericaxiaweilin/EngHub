"""
High-level orchestration entrypoint for Sim-ERP evaluations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List

from .arbiter import DecisionArbiter
from .audit import AuditTrail
from .legislation import LegislationCatalog
from .models import AuditRecord, PhysicalInput
from .physics import PhysicsCore
from .plugins.base import SimulationPlugin
from .plugins.executor import PluginExecutor


class SimERPEngine:
    def __init__(
        self,
        physics_core: PhysicsCore | None = None,
        plugin_executor: PluginExecutor | None = None,
        arbiter: DecisionArbiter | None = None,
        audit_trail: AuditTrail | None = None,
        legislation_catalog: LegislationCatalog | None = None,
    ):
        self.physics_core = physics_core or PhysicsCore()
        self.plugin_executor = plugin_executor or PluginExecutor()
        self.arbiter = arbiter or DecisionArbiter()
        self.audit_trail = audit_trail or AuditTrail(
            storage_path=Path(__file__).resolve().parents[2] / "logs" / "sim_erp_audit.jsonl"
        )
        self.legislation_catalog = legislation_catalog or LegislationCatalog()

    def evaluate(self, physical_input: PhysicalInput, plugins: Iterable[SimulationPlugin]) -> AuditRecord:
        plugin_list = list(plugins)
        legislation_catalog = self._load_legislation_packs(plugin_list)
        snapshot = self.physics_core.simulate_step(physical_input)
        plugin_records = self.plugin_executor.execute_plugins(snapshot, plugin_list, legislation_catalog)
        arbiter_result = self.arbiter.resolve(plugin_records)
        plugin_manifest_hash = self.plugin_executor.hash_manifests(plugin_list)
        legislation_pack_hash = self._hash_legislation_catalog(legislation_catalog)
        return self.audit_trail.create_record(
            physical_input=physical_input,
            snapshot=snapshot,
            plugin_records=plugin_records,
            arbiter_result=arbiter_result,
            physics_core_version=self.physics_core.VERSION,
            plugin_manifest_hash=plugin_manifest_hash,
            legislation_pack_hash=legislation_pack_hash,
            arbiter_version=self.arbiter.VERSION,
        )

    def _load_legislation_packs(self, plugins: List[SimulationPlugin]):
        catalog = {}
        for plugin in plugins:
            pack_name = plugin.manifest.legislation_pack
            if not pack_name or pack_name in catalog:
                continue
            catalog[pack_name] = self.legislation_catalog.load_pack(pack_name)
        return catalog

    def _hash_legislation_catalog(self, legislation_catalog) -> str:
        if not legislation_catalog:
            return ""
        hashes = [
            self.legislation_catalog.hash_pack(pack_name)
            for pack_name in sorted(legislation_catalog.keys())
        ]
        return "".join(hashes)

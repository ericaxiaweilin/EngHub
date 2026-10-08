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
        # 高温线只在法规包里写一次：物理层与规则层共用同一个阈值，
        # 否则会出现"规则按 35℃ 判、疲劳按另一个数放大"这种两边都自洽的假象
        heat_gt = next(
            (pack.get("heat_allowance", {}).get("temperature_c_gt")
             for pack in legislation_catalog.values()
             if isinstance(pack.get("heat_allowance"), dict)), None)
        heat_pack = next((pack for pack in legislation_catalog.values()
                          if isinstance(pack, dict) and pack.get("metabolic_levels")), None)
        thermal = None
        if heat_pack:
            from .thermal import assess

            thermal = assess(temperature_c=physical_input.environment.temperature_c,
                             humidity_percent=physical_input.environment.humidity_percent,
                             task_type=physical_input.work_context.task_type, pack=heat_pack)
            if not thermal.get("available"):
                thermal = None
            else:
                # 假设跟着数走：Tg≈Td 这类简化必须在读数里看得见
                thermal["basis"] = {**(thermal.get("basis") or {}),
                                    "assumptions": thermal.get("assumptions") or []}
        snapshot = self.physics_core.simulate_step(physical_input, heat_threshold_c=heat_gt,
                                                   thermal=thermal)
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

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


# 热应力包的名字：物理层（WBGT/工休/出勤）与法规层（超限判定）共用同一份系数
HEAT_PACK_NAME = "iso7243_jsoh_heat"


def _workload(physical_input: PhysicalInput) -> dict:
    """反推强度档要的过程量：步数/距离/时长/负重/姿势/地形/坡度，全来自输入本身。"""
    env = physical_input.environment
    return {
        "step_count": physical_input.step_count,
        "distance_meters": physical_input.distance_meters,
        "continuous_work_minutes": physical_input.continuous_work_minutes,
        "load_weight_kg": physical_input.load_weight_kg,
        "posture_angle_deg": physical_input.posture_angle_deg,
        "terrain": getattr(env.terrain, "value", str(env.terrain)),
        "floor_incline_percent": env.floor_incline_percent,
    }


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

    def evaluate(self, physical_input: PhysicalInput, plugins: Iterable[SimulationPlugin], *,
                 attendance_baseline: dict | None = None) -> AuditRecord:
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
        physics_only = False
        if not heat_pack:
            # WBGT 是物理量，不是插件选项：没有插件声明热应力包时物理层照样折算，
            # 否则取消勾选一个插件就退化成"30℃ 与 40℃ 一个能耗"那种假读数。
            # 少了这个插件只是没人做"超限判定"，读数里必须把这两件事分开写。
            try:
                candidate = self.legislation_catalog.load_pack(HEAT_PACK_NAME)
            except Exception:  # noqa: BLE001  包缺失时照样出数，走 mechanical 兜底
                candidate = None
            if isinstance(candidate, dict) and candidate.get("metabolic_levels"):
                heat_pack = candidate
                legislation_catalog[HEAT_PACK_NAME] = candidate  # 进包哈希，保证可复现
                physics_only = True
        thermal = None
        if heat_pack:
            from .thermal import assess

            thermal = assess(temperature_c=physical_input.environment.temperature_c,
                             humidity_percent=physical_input.environment.humidity_percent,
                             task_type=physical_input.work_context.task_type, pack=heat_pack,
                             absence_baseline=attendance_baseline,
                             workload=_workload(physical_input))
            if not thermal.get("available"):
                thermal = None
            else:
                # 假设跟着数走：Tg≈Td 这类简化必须在读数里看得见
                thermal["basis"] = {**(thermal.get("basis") or {}),
                                    "assumptions": thermal.get("assumptions") or [],
                                    "rule_route": ("physics_only" if physics_only else "plugin")}
                if physics_only:
                    thermal["basis"]["rule_route_note"] = (
                        "所选插件里没有声明热应力包的插件 → WBGT、所需工休、效率与出勤率照折算（物理量），"
                        "但**没有规则插件做超限判定**，arbiter 里不会出现 ISO7243.WBGT.TLV —— "
                        "「没判违规」不等于「没超线」")
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

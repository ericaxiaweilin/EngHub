"""
Physics core for step-based fatigue and energy estimation.
"""

from __future__ import annotations

from .models import PhysicalInput, PhysicalSnapshot


class PhysicsCore:
    VERSION = "2.0.0"

    def simulate_step(self, physical_input: PhysicalInput) -> PhysicalSnapshot:
        fatigue_score = self._calculate_fatigue(physical_input)
        energy_kcal = self._calculate_energy(physical_input)
        context = physical_input.work_context

        return PhysicalSnapshot(
            timestamp=physical_input.timestamp,
            worker_ref=context.worker_ref,
            shift_id=context.shift_id,
            task_type=context.task_type,
            zone_id=context.zone_id,
            action_type=context.action_type,
            x_position_m=physical_input.x_position_m,
            y_position_m=physical_input.y_position_m,
            distance_meters=physical_input.distance_meters,
            step_count=physical_input.step_count,
            load_weight_kg=physical_input.load_weight_kg,
            posture_angle_deg=physical_input.posture_angle_deg,
            continuous_work_minutes=physical_input.continuous_work_minutes,
            fatigue_score=round(fatigue_score, 4),
            energy_kcal=round(energy_kcal, 2),
            environment=physical_input.environment,
            skill_level=context.skill_level,
            ppe_status=context.ppe_status,
            machine_risk_level=context.machine_risk_level,
        )

    def _calculate_fatigue(self, physical_input: PhysicalInput) -> float:
        steps = physical_input.step_count
        load = physical_input.load_weight_kg
        temp = physical_input.environment.temperature_c

        fatigue = steps * 0.001
        if load > 15.0:
            fatigue *= 1.0 + ((load - 15.0) / 10.0)
        if temp > 35.0:
            fatigue *= 1.3

        posture_penalty = max(0.0, (physical_input.posture_angle_deg - 45.0) / 90.0)
        continuous_penalty = physical_input.continuous_work_minutes / 480.0

        return fatigue + posture_penalty + continuous_penalty

    def _calculate_energy(self, physical_input: PhysicalInput) -> float:
        terrain_multiplier = {
            "flat": 1.0,
            "slope": 1.15,
            "stairs": 1.3,
            "uneven": 1.1,
        }[physical_input.environment.terrain.value]

        step_energy = physical_input.step_count * 0.04
        load_energy = physical_input.load_weight_kg * 0.08
        incline_energy = physical_input.environment.floor_incline_percent * 0.02

        return (step_energy + load_energy + incline_energy) * terrain_multiplier

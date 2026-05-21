# Sim-ERP API

## Endpoints

- `GET /api/v1/sim-erp/status`
- `GET /api/v1/sim-erp/plugins`
- `GET /api/v1/sim-erp/audits`
- `GET /api/v1/sim-erp/audits/latest`
- `GET /api/v1/sim-erp/audits/{simulation_id}`
- `POST /api/v1/sim-erp/simulate`
- `POST /api/v1/sim-erp/scenarios/high-heat-overtime`

## Example: generic simulation request

```json
{
  "time_step_minutes": 30,
  "step_count": 12000,
  "load_weight_kg": 20,
  "posture_angle_deg": 50,
  "continuous_work_minutes": 300,
  "distance_meters": 2500,
  "x_position_m": 0,
  "y_position_m": 0,
  "environment": {
    "temperature_c": 38,
    "humidity_percent": 70,
    "terrain": "flat",
    "floor_incline_percent": 0
  },
  "work_context": {
    "worker_ref": "worker-001",
    "shift_id": "shift-day",
    "task_type": "assembly",
    "zone_id": "line-a",
    "action_type": "walk"
  },
  "plugin_names": [
    "VN_Legal_2024",
    "Johnson_Global_Standard",
    "Factory_Policy_Default"
  ]
}
```

## Example response

```json
{
  "simulation_id": "3d4c1c54-7f6c-4d0c-b3be-87d8241e9d5a",
  "final_status": "rejected",
  "legal_blocked": true,
  "fatigue_score": 20.0917,
  "energy_kcal": 498.0,
  "total_cost_delta": 30000.0,
  "max_required_break_minutes": 30,
  "blocking_rules": [
    "VN.CONTINUOUS.WORK"
  ],
  "warnings": [
    "JOHNSON.FATIGUE.WARNING"
  ]
}
```

## Audit query examples

- `GET /api/v1/sim-erp/audits?page=1&page_size=20`
- `GET /api/v1/sim-erp/audits?worker_ref=worker-001&final_status=rejected`
- `GET /api/v1/sim-erp/audits?created_from=2026-05-20T00:00:00Z&created_to=2026-05-20T23:59:59Z`
- `GET /api/v1/sim-erp/audits/latest`
- `GET /api/v1/sim-erp/audits/{simulation_id}`

## Audit list response

```json
{
  "items": [
    {
      "simulation_id": "f894734e-5cd8-4492-bafd-f922872e1ffc",
      "final_status": "rejected",
      "legal_blocked": true,
      "created_at": "2026-05-20T05:34:07.994122",
      "total_cost_delta": 30000.0,
      "max_required_break_minutes": 30,
      "blocking_rules": ["VN.CONTINUOUS.WORK"],
      "warnings": ["JOHNSON.FATIGUE.WARNING"]
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

## Audit storage

Audit records are appended to:

- `logs/sim_erp_audit.jsonl`

Persisted database records can also be stored in:

- `sim_erp_audit_logs`

For local SQLite development, initialize the table with:

```bash
/Users/thanhhuyennguyen/Desktop/EngHub/.venv/bin/python scripts/init_sim_erp_audit_table.py
```

Each line is a full JSON record with:

- input hash
- plugin manifest hash
- legislation pack hash
- physics snapshot
- plugin execution records
- arbitration result

-- Sim-ERP audit log persistence
-- Created: 2026-05-20

CREATE TABLE IF NOT EXISTS sim_erp_audit_logs (
    id VARCHAR(36) PRIMARY KEY,
    simulation_id VARCHAR(36) NOT NULL UNIQUE,
    worker_ref VARCHAR(50) NOT NULL,
    shift_id VARCHAR(50) NOT NULL,
    task_type VARCHAR(100) NOT NULL,
    zone_id VARCHAR(50) NOT NULL,
    final_status VARCHAR(20) NOT NULL,
    legal_blocked BOOLEAN NOT NULL DEFAULT FALSE,
    total_cost_delta DECIMAL(12, 2) DEFAULT 0,
    max_required_break_minutes INTEGER DEFAULT 0,
    total_penalty_score INTEGER DEFAULT 0,
    simulation_input_hash VARCHAR(64) NOT NULL,
    physics_core_version VARCHAR(20) NOT NULL,
    plugin_manifest_hash VARCHAR(256) NOT NULL,
    legislation_pack_hash VARCHAR(256) NOT NULL,
    arbiter_version VARCHAR(20) NOT NULL,
    optimizer_version VARCHAR(50) DEFAULT 'manual',
    snapshot_payload JSONB NOT NULL,
    plugin_records_payload JSONB NOT NULL,
    arbiter_result_payload JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sim_erp_simulation_id ON sim_erp_audit_logs(simulation_id);
CREATE INDEX IF NOT EXISTS idx_sim_erp_status_created ON sim_erp_audit_logs(final_status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sim_erp_worker_shift ON sim_erp_audit_logs(worker_ref, shift_id);

-- =============================================================================
-- Migration: 047_aps_request_queue.sql
-- Description: Create APS schedule request queue table for event-driven decoupling
-- Implements #11 PS事件解耦 - 将 APS 重算从同步 task 改为异步队列模式
-- Author: EngHub Audit Optimization
-- Date: 2026-07-28
-- =============================================================================

-- APS 调度请求队列表
CREATE TABLE IF NOT EXISTS aps_schedule_requests (
    id VARCHAR(36) PRIMARY KEY DEFAULT generate_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    mode VARCHAR(20) DEFAULT 'hybrid',          -- scheduling mode: hybrid/simulative/optimization
    horizon_days INTEGER DEFAULT 7,              -- scheduling horizon in days
    optimize_for VARCHAR(20) DEFAULT 'delivery', -- optimization target: delivery/cost/throughput
    source_type VARCHAR(30) NOT NULL,            -- 'report_created', 'report_modified', 'manual'
    source_id VARCHAR(50),                       -- triggered report ID or manual request ID
    status VARCHAR(20) DEFAULT 'pending',        -- pending, in_progress, completed, failed
    retry_count INTEGER DEFAULT 0,               -- failed retry count
    max_retries INTEGER DEFAULT 3,               -- max retry attempts before DLQ
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    completed_at TIMESTAMP NULL,
    error_message TEXT NULL,

    INDEX idx_factory_status (factory_id, status),
    INDEX idx_source (source_type, source_id),
    INDEX idx_retry (status, retry_count)
);

-- Dead Letter Queue table for failed requests
CREATE TABLE IF NOT EXISTS aps_dlq_requests (
    id VARCHAR(36) PRIMARY KEY,
    factory_id VARCHAR(50) NOT NULL,
    mode VARCHAR(20),
    horizon_days INTEGER,
    optimize_for VARCHAR(20),
    source_type VARCHAR(30) NOT NULL,
    source_id VARCHAR(50),
    retry_count INTEGER,
    last_error_message TEXT,
    failed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_factory (factory_id),
    INDEX idx_failed (failed_at)
);

-- =============================================================================
-- Downgrade script (if needed)
-- DROP TABLE IF EXISTS aps_schedule_requests;
-- DROP TABLE IF EXISTS aps_dlq_requests;
-- =============================================================================

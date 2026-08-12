-- Migration: 063_quality_red_tag.sql
-- Description: Add Quality Red Tag (质量红单) tables for defect management
-- Created: 2026-08-02

-- Quality Red Tag table
CREATE TABLE IF NOT EXISTS quality_red_tag (
    id VARCHAR(36) PRIMARY KEY,
    factory_id VARCHAR(36) NOT NULL,
    red_tag_no VARCHAR(50) UNIQUE NOT NULL,
    defect_id VARCHAR(36) NOT NULL,
    inspection_id VARCHAR(36),
    red_tag_type VARCHAR(20) NOT NULL,
    defect_description TEXT,
    nonconforming_qty DECIMAL(12,4) NOT NULL,
    batch_no VARCHAR(100),
    work_order_id VARCHAR(36),
    station_id VARCHAR(36),
    discovered_by VARCHAR(36),
    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    severity VARCHAR(20) DEFAULT 'MINOR',
    quarantine_status VARCHAR(20) DEFAULT 'SEATED',
    disposition VARCHAR(20),
    disposition_by VARCHAR(36),
    disposition_date TIMESTAMP,
    disposition_notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE,
    created_by VARCHAR(36),
    
    CONSTRAINT fk_red_tag_defect FOREIGN KEY (defect_id) REFERENCES defect_records(id) ON DELETE CASCADE,
    CONSTRAINT fk_red_tag_inspection FOREIGN KEY (inspection_id) REFERENCES inspections(id) ON DELETE SET NULL,
    CONSTRAINT fk_red_tag_workorder FOREIGN KEY (work_order_id) REFERENCES work_orders(id) ON DELETE SET NULL,
    CONSTRAINT fk_red_tag_station FOREIGN KEY (station_id) REFERENCES stations(id) ON DELETE SET NULL
);

-- Quality Red Tag attachments table
CREATE TABLE IF NOT EXISTS quality_red_tag_attachments (
    id VARCHAR(36) PRIMARY KEY,
    red_tag_id VARCHAR(36) NOT NULL,
    file_id VARCHAR(36) NOT NULL,
    attachment_type VARCHAR(20) DEFAULT 'PHOTO',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT fk_red_tag_attachment FOREIGN KEY (red_tag_id) REFERENCES quality_red_tag(id) ON DELETE CASCADE,
    CONSTRAINT fk_red_tag_file FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
);

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_red_tag_factory ON quality_red_tag(factory_id);
CREATE INDEX IF NOT EXISTS idx_red_tag_defect ON quality_red_tag(defect_id);
CREATE INDEX IF NOT EXISTS idx_red_tag_no ON quality_red_tag(red_tag_no);
CREATE INDEX IF NOT EXISTS idx_red_tag_status ON quality_red_tag(quarantine_status);
CREATE INDEX IF NOT EXISTS idx_red_tag_disposition ON quality_red_tag(disposition);
CREATE INDEX IF NOT EXISTS idx_red_tag_type ON quality_red_tag(red_tag_type);
CREATE INDEX IF NOT EXISTS idx_red_tag_created_at ON quality_red_tag(created_at);
CREATE INDEX IF NOT EXISTS idx_red_tag_attachment_red_tag ON quality_red_tag_attachments(red_tag_id);
CREATE INDEX IF NOT EXISTS idx_red_tag_attachment_file ON quality_red_tag_attachments(file_id);

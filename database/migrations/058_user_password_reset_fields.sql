-- =============================================================================
-- Migration: 058_user_password_reset_fields.sql
-- Description: Add password reset token fields to users table (model 已定义但缺迁移)
-- Fixes: login 500 -> UndefinedColumnError: column users.password_reset_token does not exist
-- =============================================================================

ALTER TABLE users ADD COLUMN IF NOT EXISTS password_reset_token VARCHAR(255);
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_reset_expires TIMESTAMP;

CREATE INDEX IF NOT EXISTS idx_user_password_reset_token ON users(password_reset_token);

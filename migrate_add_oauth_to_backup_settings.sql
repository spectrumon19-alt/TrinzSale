-- Migration: Add OAuth support to backup_settings table
-- Purpose: Store OAuth tokens for Google Drive backups

-- Add OAuth columns to backup_settings table
ALTER TABLE backup_settings
ADD COLUMN IF NOT EXISTS oauth_enabled BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS oauth_tokens TEXT,
ADD COLUMN IF NOT EXISTS oauth_user_email VARCHAR(255);

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS idx_backup_settings_oauth_enabled
ON backup_settings(oauth_enabled);

-- Add comment for documentation
COMMENT ON COLUMN backup_settings.oauth_enabled IS 'Whether OAuth is enabled for Google Drive backups';
COMMENT ON COLUMN backup_settings.oauth_tokens IS 'JSON containing access_token, refresh_token, expires_at, user_email, user_id';
COMMENT ON COLUMN backup_settings.oauth_user_email IS 'Email of the Google account authorized for backups';

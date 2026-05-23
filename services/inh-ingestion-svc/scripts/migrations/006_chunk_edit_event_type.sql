-- Migration 006: Add 'chunk_edited' event type to version_events
-- Allows tracking chunk-level edits as version events.
-- Idempotent: safe to run multiple times.

-- Drop the existing constraint if it exists
ALTER TABLE version_events
    DROP CONSTRAINT IF EXISTS chk_event_type;

-- Re-add with 'chunk_edited' included
ALTER TABLE version_events
    ADD CONSTRAINT chk_event_type
    CHECK (event_type IN ('created', 'activated', 'superseded', 'restored', 'chunk_edited'));

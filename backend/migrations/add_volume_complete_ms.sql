-- Progressive 3D volume loading measurement (progressive-loading, option A).
-- first image render (load_ms, existing) vs full volume loaded (volume_complete_ms):
-- the gap is the progressive-loading benefit — radiologist sees a usable MPR/3D
-- well before all slices arrive. Idempotent.
ALTER TABLE viewer_open_events ADD COLUMN IF NOT EXISTS volume_complete_ms INT;

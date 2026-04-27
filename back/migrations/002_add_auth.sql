-- authentication migration: add password_hash to players

ALTER TABLE players
  ADD COLUMN IF NOT EXISTS password_hash TEXT NOT NULL DEFAULT '';

ALTER TABLE players
  ALTER COLUMN password_hash DROP DEFAULT;

CREATE INDEX IF NOT EXISTS idx_players_username ON players(username);
BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Players
CREATE TABLE IF NOT EXISTS players (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  username     TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  elo          INT  NOT NULL DEFAULT 1000,
  password_hash TEXT NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Matches 1v1
CREATE TABLE IF NOT EXISTS matches_1v1 (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  player_red_id  UUID NOT NULL REFERENCES players(id) ON DELETE RESTRICT,
  player_blue_id UUID NOT NULL REFERENCES players(id) ON DELETE RESTRICT,
  score_red      INT  NOT NULL CHECK (score_red >= 0),
  score_blue     INT  NOT NULL CHECK (score_blue >= 0),
  elo_delta_red  INT  NOT NULL DEFAULT 0,
  elo_delta_blue INT  NOT NULL DEFAULT 0,
  played_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT different_players_1v1 CHECK (player_red_id <> player_blue_id)
);

-- Matches 2v2
CREATE TABLE IF NOT EXISTS matches_2v2 (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  player_red_1     UUID NOT NULL REFERENCES players(id) ON DELETE RESTRICT,
  player_red_2     UUID NOT NULL REFERENCES players(id) ON DELETE RESTRICT,
  player_blue_1    UUID NOT NULL REFERENCES players(id) ON DELETE RESTRICT,
  player_blue_2    UUID NOT NULL REFERENCES players(id) ON DELETE RESTRICT,
  score_red        INT  NOT NULL CHECK (score_red >= 0),
  score_blue       INT  NOT NULL CHECK (score_blue >= 0),
  elo_delta_red_1  INT  NOT NULL DEFAULT 0,
  elo_delta_red_2  INT  NOT NULL DEFAULT 0,
  elo_delta_blue_1 INT  NOT NULL DEFAULT 0,
  elo_delta_blue_2 INT  NOT NULL DEFAULT 0,
  played_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT different_players_2v2 CHECK (
    player_red_1 <> player_red_2
    AND player_blue_1 <> player_blue_2
    AND player_red_1 NOT IN (player_blue_1, player_blue_2)
    AND player_red_2 NOT IN (player_blue_1, player_blue_2)
  )
);

-- Player stats 1v1
CREATE TABLE IF NOT EXISTS match_player_stats_1v1 (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  match_id        UUID NOT NULL REFERENCES matches_1v1(id) ON DELETE CASCADE,
  player_id       UUID NOT NULL REFERENCES players(id) ON DELETE RESTRICT,
  role            TEXT NOT NULL CHECK (role = 'solo'),
  goals_scored    INT  NOT NULL DEFAULT 0 CHECK (goals_scored >= 0),
  shots_total     INT  NOT NULL DEFAULT 0 CHECK (shots_total >= 0),
  shots_on_target INT  NOT NULL DEFAULT 0 CHECK (shots_on_target >= 0),
  saves           INT  NOT NULL DEFAULT 0 CHECK (saves >= 0),
  possession_pct  FLOAT NOT NULL DEFAULT 0 CHECK (possession_pct BETWEEN 0 AND 100),
  max_ball_speed  FLOAT NOT NULL DEFAULT 0 CHECK (max_ball_speed >= 0),
  UNIQUE (match_id, player_id)
);

-- Player stats 2v2
CREATE TABLE IF NOT EXISTS match_player_stats_2v2 (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  match_id        UUID NOT NULL REFERENCES matches_2v2(id) ON DELETE CASCADE,
  player_id       UUID NOT NULL REFERENCES players(id) ON DELETE RESTRICT,
  role            TEXT NOT NULL CHECK (role IN ('attacker', 'defender')),
  goals_scored    INT  NOT NULL DEFAULT 0 CHECK (goals_scored >= 0),
  shots_total     INT  NOT NULL DEFAULT 0 CHECK (shots_total >= 0),
  shots_on_target INT  NOT NULL DEFAULT 0 CHECK (shots_on_target >= 0),
  saves           INT  NOT NULL DEFAULT 0 CHECK (saves >= 0),
  possession_pct  FLOAT NOT NULL DEFAULT 0 CHECK (possession_pct BETWEEN 0 AND 100),
  max_ball_speed  FLOAT NOT NULL DEFAULT 0 CHECK (max_ball_speed >= 0),
  UNIQUE (match_id, player_id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_players_username     ON players(username);
CREATE INDEX IF NOT EXISTS idx_matches_1v1_red      ON matches_1v1(player_red_id, played_at DESC);
CREATE INDEX IF NOT EXISTS idx_matches_1v1_blue     ON matches_1v1(player_blue_id, played_at DESC);
CREATE INDEX IF NOT EXISTS idx_matches_2v2_red_1    ON matches_2v2(player_red_1, played_at DESC);
CREATE INDEX IF NOT EXISTS idx_matches_2v2_red_2    ON matches_2v2(player_red_2, played_at DESC);
CREATE INDEX IF NOT EXISTS idx_matches_2v2_blue_1   ON matches_2v2(player_blue_1, played_at DESC);
CREATE INDEX IF NOT EXISTS idx_matches_2v2_blue_2   ON matches_2v2(player_blue_2, played_at DESC);
CREATE INDEX IF NOT EXISTS idx_stats_1v1_player     ON match_player_stats_1v1(player_id);
CREATE INDEX IF NOT EXISTS idx_stats_1v1_match      ON match_player_stats_1v1(match_id);
CREATE INDEX IF NOT EXISTS idx_stats_2v2_player     ON match_player_stats_2v2(player_id);
CREATE INDEX IF NOT EXISTS idx_stats_2v2_match      ON match_player_stats_2v2(match_id);

-- Trigger 2v2 roles
CREATE OR REPLACE FUNCTION check_roles_2v2()
RETURNS TRIGGER AS $$
DECLARE
  role_count INT;
BEGIN
  SELECT COUNT(*) INTO role_count
  FROM match_player_stats_2v2
  WHERE match_id = NEW.match_id
    AND role = NEW.role;

  IF role_count >= 2 THEN
    RAISE EXCEPTION 'Role % already filled for this 2v2 match', NEW.role;
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_check_roles_2v2 ON match_player_stats_2v2;
CREATE TRIGGER trg_check_roles_2v2
BEFORE INSERT OR UPDATE ON match_player_stats_2v2
FOR EACH ROW
EXECUTE FUNCTION check_roles_2v2();

COMMIT;
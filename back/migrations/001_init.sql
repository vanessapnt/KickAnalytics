-- The pgcrypto module provides cryptographic functions, can generate UUIDs using gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE players (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    username     TEXT        NOT NULL UNIQUE,
    -- if not specified or already taken -> ERROR
    display_name TEXT        NOT NULL,
    elo          INT         NOT NULL DEFAULT 1000,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE matches_1v1 (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    player_red_id  UUID        NOT NULL REFERENCES players(id) ON DELETE RESTRICT,
    -- we can't delete a player if they already played a match, to keep the history consistent
    player_blue_id UUID        NOT NULL REFERENCES players(id) ON DELETE RESTRICT,
    score_red      INT         NOT NULL CHECK (score_red >= 0),
    score_blue     INT         NOT NULL CHECK (score_blue >= 0),
    elo_delta_red  INT         NOT NULL DEFAULT 0,
    -- elo change (+12 or -12)
    elo_delta_blue INT         NOT NULL DEFAULT 0,
    played_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT different_players_1v1 CHECK (player_red_id <> player_blue_id) -- <> : !=
);

CREATE TABLE matches_2v2 (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    player_red_1    UUID        NOT NULL REFERENCES players(id) ON DELETE RESTRICT,
    player_red_2    UUID        NOT NULL REFERENCES players(id) ON DELETE RESTRICT,
    player_blue_1   UUID        NOT NULL REFERENCES players(id) ON DELETE RESTRICT,
    player_blue_2   UUID        NOT NULL REFERENCES players(id) ON DELETE RESTRICT,
    score_red       INT         NOT NULL CHECK (score_red >= 0),
    score_blue      INT         NOT NULL CHECK (score_blue >= 0),
    elo_delta_red_1  INT        NOT NULL DEFAULT 0,
    elo_delta_red_2  INT        NOT NULL DEFAULT 0,
    elo_delta_blue_1 INT        NOT NULL DEFAULT 0,
    elo_delta_blue_2 INT        NOT NULL DEFAULT 0,
    played_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT different_players_2v2 CHECK (
        player_red_1 <> player_red_2
        AND player_blue_1 <> player_blue_2
        AND player_red_1 NOT IN (player_blue_1, player_blue_2)
        AND player_red_2 NOT IN (player_blue_1, player_blue_2)
    )
);

CREATE TABLE match_player_stats_1v1 (
    id              UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    match_id        UUID    NOT NULL REFERENCES matches_1v1(id) ON DELETE CASCADE,
    player_id       UUID    NOT NULL REFERENCES players(id) ON DELETE RESTRICT,
    role            TEXT    NOT NULL CHECK (role = 'solo'),
    goals_scored    INT     NOT NULL DEFAULT 0 CHECK (goals_scored >= 0),
    shots_total     INT     NOT NULL DEFAULT 0 CHECK (shots_total >= 0),
    shots_on_target INT     NOT NULL DEFAULT 0 CHECK (shots_on_target >= 0),
    saves           INT     NOT NULL DEFAULT 0 CHECK (saves >= 0),
    possession_pct  FLOAT   NOT NULL DEFAULT 0 CHECK (
                          possession_pct BETWEEN 0
                          AND 100
                      ),
    max_ball_speed  FLOAT   NOT NULL DEFAULT 0 CHECK (max_ball_speed >= 0),
    heatmap         JSONB,
    UNIQUE (match_id, player_id) -- can be together in a stat table only one time
);

CREATE TABLE match_player_stats_2v2 (
    id              UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    match_id        UUID    NOT NULL REFERENCES matches_2v2(id) ON DELETE CASCADE,
    player_id       UUID    NOT NULL REFERENCES players(id) ON DELETE RESTRICT,
    role            TEXT    NOT NULL CHECK (role IN ('attacker', 'defender')),
    goals_scored    INT     NOT NULL DEFAULT 0 CHECK (goals_scored >= 0),
    shots_total     INT     NOT NULL DEFAULT 0 CHECK (shots_total >= 0),
    shots_on_target INT     NOT NULL DEFAULT 0 CHECK (shots_on_target >= 0),
    saves           INT     NOT NULL DEFAULT 0 CHECK (saves >= 0),
    possession_pct  FLOAT   NOT NULL DEFAULT 0 CHECK (
                          possession_pct BETWEEN 0
                          AND 100
                      ),
    max_ball_speed  FLOAT   NOT NULL DEFAULT 0 CHECK (max_ball_speed >= 0),
    heatmap         JSONB,
    UNIQUE (match_id, player_id)
);

-- use hashing to speed up queries filtering by player and sorting by date : SELECT * FROM matches_1v1 WHERE player_red_id = ? 
CREATE INDEX idx_matches_1v1_red    ON matches_1v1(player_red_id, played_at DESC);
CREATE INDEX idx_matches_1v1_blue   ON matches_1v1(player_blue_id, played_at DESC);
CREATE INDEX idx_matches_2v2_red_1  ON matches_2v2(player_red_1, played_at DESC);
CREATE INDEX idx_matches_2v2_red_2  ON matches_2v2(player_red_2, played_at DESC);
CREATE INDEX idx_matches_2v2_blue_1 ON matches_2v2(player_blue_1, played_at DESC);
CREATE INDEX idx_matches_2v2_blue_2 ON matches_2v2(player_blue_2, played_at DESC);
CREATE INDEX idx_stats_1v1_player   ON match_player_stats_1v1(player_id);
CREATE INDEX idx_stats_1v1_match    ON match_player_stats_1v1(match_id);
CREATE INDEX idx_stats_2v2_player   ON match_player_stats_2v2(player_id);
CREATE INDEX idx_stats_2v2_match    ON match_player_stats_2v2(match_id);

-- This view (leaderboard) shows dynamically the ranking of players based on their elo, number of matches, wins, winrate, average possession and average precision
CREATE VIEW leaderboard AS
SELECT
    p.id,
    p.username,
    p.display_name,
    p.elo,
    COUNT(DISTINCT m.id) AS matches_played,
    COUNT(DISTINCT m.id) FILTER (
        WHERE (
                  m.player_red_id  = p.id AND m.score_red  > m.score_blue
              )
              OR (
                  m.player_blue_id = p.id AND m.score_blue > m.score_red
              )
    ) AS wins,
    ROUND(
        100.0 * COUNT(DISTINCT m.id) FILTER (
            WHERE (
                      m.player_red_id  = p.id AND m.score_red  > m.score_blue
                  )
                  OR (
                      m.player_blue_id = p.id AND m.score_blue > m.score_red
                  )
        ) / NULLIF(COUNT(DISTINCT m.id), 0),
        1
    ) AS winrate_pct,
    ROUND(AVG(s.possession_pct) :: NUMERIC, 1) AS avg_possession,
    ROUND(
        AVG(
            CASE
                WHEN s.shots_total > 0 THEN 100.0 * s.shots_on_target / s.shots_total
            END
        ) :: NUMERIC,
        1
    ) AS avg_precision_pct
FROM players p
LEFT JOIN (
    SELECT * FROM matches_1v1
    UNION ALL
    SELECT * FROM matches_2v2
) m ON p.id IN (
    m.player_red_id,
    m.player_blue_id,
    m.player_red_1,
    m.player_red_2,
    m.player_blue_1,
    m.player_blue_2
)
LEFT JOIN (
    SELECT * FROM match_player_stats_1v1
    UNION ALL
    SELECT * FROM match_player_stats_2v2
) s ON s.match_id = m.id
   AND s.player_id = p.id
GROUP BY p.id
ORDER BY p.elo DESC;

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

CREATE TRIGGER trg_check_roles_2v2 
BEFORE INSERT OR UPDATE ON match_player_stats_2v2
FOR EACH ROW
EXECUTE FUNCTION check_roles_2v2();

-- DROP TABLE IF EXISTS match_player_stats_1v1, match_player_stats_2v2, matches_1v1, matches_2v2, players CASCADE;
-- DROP VIEW IF EXISTS leaderboard;
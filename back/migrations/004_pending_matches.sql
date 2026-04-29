CREATE TABLE pending_matches (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    created_by   TEXT        NOT NULL REFERENCES players(username) ON DELETE CASCADE,
    red_players  TEXT[]      NOT NULL,
    blue_players TEXT[]      NOT NULL,
    status       TEXT        NOT NULL DEFAULT 'pending'
                             CHECK (status IN ('pending', 'playing', 'cancelled')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE match_invites (
    match_id  UUID NOT NULL REFERENCES pending_matches(id) ON DELETE CASCADE,
    username  TEXT NOT NULL REFERENCES players(username) ON DELETE CASCADE,
    status    TEXT NOT NULL DEFAULT 'pending'
              CHECK (status IN ('pending', 'accepted')),
    PRIMARY KEY (match_id, username)
);

CREATE INDEX idx_match_invites_username ON match_invites(username, status);
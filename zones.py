import math
from config import FIELD_Y0, FIELD_Y1, FIELD_H_PX, CANVAS_W, FIELD_W, GOAL_W

N_RODS = 8
ROD_Y_PX = [FIELD_Y0 + i * FIELD_H_PX / (N_RODS - 1) for i in range(N_RODS)]

RODS = [
    {"team": "blue", "name": "blue_goalkeeper", "2v2_role": "defender"},
    {"team": "blue", "name": "blue_defense",     "2v2_role": "defender"},
    {"team": "red",  "name": "red_midfield",     "2v2_role": "attacker"},
    {"team": "blue", "name": "blue_midfield",    "2v2_role": "attacker"},
    {"team": "red",  "name": "red_midfield2",    "2v2_role": "attacker"},
    {"team": "blue", "name": "blue_attack",      "2v2_role": "attacker"},
    {"team": "red",  "name": "red_defense",      "2v2_role": "defender"},
    {"team": "red",  "name": "red_goalkeeper",   "2v2_role": "defender"},
]

GOALKEEPER_RODS = {0, 7}

_goal_offset_x = (FIELD_W - GOAL_W) / 2
GOAL_X1 = int(CANVAS_W * _goal_offset_x / FIELD_W)
GOAL_X2 = int(CANVAS_W * (_goal_offset_x + GOAL_W) / FIELD_W)

CONTACT_DEVIATION_PX = 20
DEV_AXIS_PX          = 8
WALL_MARGIN_PX       = 15

MAX_GAP_S         = 0.5
GOAL_APPROACH_PX  = 100

MIDFIELD_Y = FIELD_Y0 + FIELD_H_PX / 2.0

def _nearest_rod(y):
    return min(range(N_RODS), key=lambda i: abs(ROD_Y_PX[i] - y))

def detect_contacts(ball_history):
    contacts = []
    h = ball_history
    for i in range(1, len(h) - 1):
        p0, p1, p2 = h[i - 1], h[i], h[i + 1]

        dt0 = (p1["t"] - p0["t"]) / 1000.0
        dt1 = (p2["t"] - p1["t"]) / 1000.0

        if dt0 > MAX_GAP_S or dt1 > MAX_GAP_S:
            continue
        dt0 = max(dt0, 0.001)
        dt1 = max(dt1, 0.001)

        vx0 = (p1["x"] - p0["x"]) / dt0
        vy0 = (p1["y"] - p0["y"]) / dt0
        vx1 = (p2["x"] - p1["x"]) / dt1
        vy1 = (p2["y"] - p1["y"]) / dt1

        near_side_wall = (p1["x"] < WALL_MARGIN_PX or
                          p1["x"] > CANVAS_W - WALL_MARGIN_PX)
        if near_side_wall and vx0 * vx1 < 0:
            continue

        scale = dt1 / dt0
        pred_x = p1["x"] + (p1["x"] - p0["x"]) * scale
        pred_y = p1["y"] + (p1["y"] - p0["y"]) * scale

        dev_x = p2["x"] - pred_x
        dev_y = p2["y"] - pred_y
        deviation = math.sqrt(dev_x * dev_x + dev_y * dev_y)

        if deviation < CONTACT_DEVIATION_PX and \
                abs(dev_x) < DEV_AXIS_PX and abs(dev_y) < DEV_AXIS_PX:
            continue

        rod_idx = _nearest_rod(p1["y"])

        if rod_idx in GOALKEEPER_RODS and not (GOAL_X1 <= p1["x"] <= GOAL_X2):
            continue

        rod = RODS[rod_idx]

        contacts.append({
            "hist_idx": i,
            "x": p1["x"],
            "y": p1["y"],
            "t": p1["t"],
            "rod_idx":   rod_idx,
            "team":      rod["team"],
            "name":      rod["name"],
            "role_2v2":  rod["2v2_role"],
            "vx0": vx0, "vy0": vy0,
            "vx1": vx1, "vy1": vy1,
            "deviation": round(deviation, 1),
        })
    return contacts


def _possession(ball_history):
    if len(ball_history) < 2:
        return 50.0, 50.0
    blue_ms = red_ms = 0
    for i in range(1, len(ball_history)):
        p1, p2 = ball_history[i - 1], ball_history[i]
        dt = p2["t"] - p1["t"]
        avg_y = (p1["y"] + p2["y"]) / 2.0
        if avg_y < MIDFIELD_Y:
            blue_ms += dt
        else:
            red_ms += dt
    total = blue_ms + red_ms or 1
    blue_pct = round(100.0 * blue_ms / total, 1)
    return blue_pct, round(100.0 - blue_pct, 1)

def compute_attributed_stats(ball_history, goal_events, match_mode):
    roles = ("solo",) if match_mode == "1v1" else ("attacker", "defender")
    stats = {
        (t, r): {"goals": 0, "shots_total": 0, "shots_on_target": 0, "saves": 0}
        for t in ("blue", "red") for r in roles
    }

    def key(team, role_2v2):
        return (team, "solo" if match_mode == "1v1" else role_2v2)

    contacts   = detect_contacts(ball_history)
    possession = _possession(ball_history)

    for goal in goal_events:
        last = last_scorer_contact(contacts, goal["ts"], goal["team"])
        if last:
            k = key(last["team"], last["role_2v2"])
        else:
            k = key(goal["team"], "attacker")
        stats[k]["goals"] += 1

    for i, c in enumerate(contacts):
        k    = key(c["team"], c["role_2v2"])
        team = c["team"]
        vy1  = c["vy1"]

        toward_opp = (vy1 > 0) if team == "blue" else (vy1 < 0)

        near_own_goal = (
            (team == "blue" and c["y"] <= FIELD_Y0 + GOAL_APPROACH_PX) or
            (team == "red"  and c["y"] >= FIELD_Y1 - GOAL_APPROACH_PX)
        )
        if near_own_goal and toward_opp:
            stats[k]["saves"] += 1
            continue

        if not toward_opp:
            continue

        end_idx = contacts[i + 1]["hist_idx"] if i + 1 < len(contacts) else len(ball_history)
        segment = ball_history[c["hist_idx"]:end_idx]

        crosses_mid = any(
            (p["y"] > MIDFIELD_Y if team == "blue" else p["y"] < MIDFIELD_Y)
            for p in segment
        )
        if not crosses_mid:
            continue

        stats[k]["shots_total"] += 1

        on_target = any(
            (p["y"] >= FIELD_Y1 - GOAL_APPROACH_PX if team == "blue"
             else p["y"] <= FIELD_Y0 + GOAL_APPROACH_PX)
            for p in segment
        )
        if on_target:
            stats[k]["shots_on_target"] += 1

    return stats, possession

def last_scorer_contact(contacts, goal_ts, scoring_team):
    prev = sorted(
        [c for c in contacts if c["t"] < goal_ts],
        key=lambda c: c["t"], reverse=True,
    )
    for c in prev:
        if c["rod_idx"] in GOALKEEPER_RODS and c["team"] != scoring_team:
            continue
        return c
    return prev[0] if prev else None

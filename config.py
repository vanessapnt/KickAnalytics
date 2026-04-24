import os

ENV = os.environ.get('ENV', 'production').strip().lower()
IS_PROD = ENV in ('prod', 'production')

FIELD_W = 68
FIELD_H = 119
GOAL_W = 18
GOAL_DEPTH_CM = 5

MAX_CONNECTIONS_PER_IP     = 5
MAX_MESSAGES_PER_SEC_CAM   = 60
MAX_MESSAGES_PER_SEC_SPECT = 5
MAX_SPECTATORS             = 20

PORT     = int(os.environ.get('PORT', 8080))

SPECTATOR_PUBLIC = os.environ.get('SPECTATOR_PUBLIC', '0').strip().lower() in ('1', 'true', 'yes', 'on')

CANVAS_W      = 450
FIELD_H_PX    = 800
GOAL_DEPTH_PX = 40
CANVAS_H      = FIELD_H_PX + 2 * GOAL_DEPTH_PX

FIELD_Y0 = GOAL_DEPTH_PX
FIELD_Y1 = FIELD_Y0 + FIELD_H_PX

ADMIN_USERNAMES = set(os.environ.get("ADMIN_USERNAMES", "").split(","))
ENABLE_DEBUG_STATE_DUMP = os.environ.get('ENABLE_DEBUG_STATE_DUMP', '1' if not IS_PROD else '0').strip().lower() in ('1', 'true', 'yes', 'on')
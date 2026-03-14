import os

FIELD_W        = None
FIELD_H        = None
GOAL_W         = None
GOAL_OFFSET_X  = None
GOAL_OFFSET_Y  = None

MAX_CONNECTIONS_PER_IP     = 2
MAX_MESSAGES_PER_SEC_CAM   = 60
MAX_MESSAGES_PER_SEC_SPECT = 5
MAX_SPECTATORS             = 20

PORT     = int(os.environ.get('PORT', 8080))
CANVAS_W = 450
CANVAS_H = 800
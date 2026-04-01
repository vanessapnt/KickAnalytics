import asyncio

GOALS_TO_WIN = 5
REPLAY_BUFFER_SIZE = 30

match_over: bool = False
match_paused: bool = False
ball_history: list = []
frame_replay_buffer: list = []
replay_in_progress: bool = False

current_match: dict = {
    "mode": "1v1",
    "red": [],
    "blue": [],
    "roles": {"red": [], "blue": []},
}
cameras: set = set()
controllers: set = set()
spectators: set = set()

camera_pool: dict = {}

active_camera_ws = None
active_camera_username = None
prevalidated_camera_username = None

table_state: str = "idle"
matchmaking_room: dict = None
ws_players: dict = {}

frame_queue: asyncio.Queue = None
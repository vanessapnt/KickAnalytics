import asyncio

GOALS_TO_WIN = 5
REPLAY_BUFFER_SIZE = 30

match_over: bool = False
ball_history: list = []
goal_events: list = []
frame_replay_buffer: list = []
replay_in_progress: bool = False

current_match: dict = {
    "mode": "1v1",
    "red": [],
    "blue": [],
    "roles": {"red": [], "blue": []},
}

cameras: set = set()
camera_ws = None
controllers: set = set()
spectators: set = set()
spectator_users: dict = {}

table_state: str = "free"

frame_queue: asyncio.Queue = None
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
cameras: set = set() # set of all the camera websocket connections (validated or not)
controllers: set = set()
spectators: set = set()

camera_pool: dict = {} # for ux purposes and selection (only 3)

validated_camera_ws = None # only one, if closed we stop the game
validated_camera_username = None

table_state: str = "free"
matchmaking_room: dict = None
ws_players: dict = {}

frame_queue: asyncio.Queue = None
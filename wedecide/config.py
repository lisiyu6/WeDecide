from pathlib import Path
import os
import sysconfig
from .prompts import PRESETS

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
if not WEB_DIR.is_dir():
    WEB_DIR = Path(sysconfig.get_path("data")) / "share" / "wedecide" / "web"
DEFAULT_DATA = ROOT / "data" if (ROOT / "web").is_dir() else Path.cwd() / "data"
DATA_DIR = Path(os.environ.get("WEDECIDE_DATA_DIR", str(DEFAULT_DATA))).expanduser().resolve()
DB_PATH = DATA_DIR / "wedecide.sqlite3"
TIMEZONE = os.environ.get("WEDECIDE_TIMEZONE", "Asia/Shanghai")
HOST = os.environ.get("WEDECIDE_HOST", "0.0.0.0")
PORT = int(os.environ.get("WEDECIDE_PORT", "8000"))
PUBLIC_URL = os.environ.get("WEDECIDE_PUBLIC_URL", "").rstrip("/")
SECURE_COOKIE = os.environ.get("WEDECIDE_SECURE_COOKIE", "false").lower() == "true"
ALLOWED_ORIGINS = {s.rstrip("/") for s in os.environ.get("WEDECIDE_ALLOWED_ORIGINS", PUBLIC_URL).split(",") if s}
DEFAULT_SETTINGS = {
    "revision": 1,
    "max_rooms": 16, "max_members": 8, "ai_concurrency": 4, "ai_queue_limit": 32,
    "room_idle_hours": 48, "retention_days": 7, "providers": [], "default_provider": "",
    "prompts": {key: "" for key in PRESETS},
}

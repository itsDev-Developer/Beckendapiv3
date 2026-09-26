from os import getenv
from dotenv import load_dotenv
from pathlib import Path

if Path("config.env").exists():
    load_dotenv("config.env")

class Telegram:
    API_ID = int(getenv("API_ID", "0"))
    API_HASH = getenv("API_HASH", "")
    BOT_TOKEN = getenv("BOT_TOKEN", "")
    PORT = int(getenv("PORT", 8080))
    SESSION_STRING = getenv("SESSION_STRING", "")
    BASE_URL = getenv("BASE_URL", "").rstrip('/')
    DATABASE_URL = getenv("DATABASE_URL", "")
    AUTH_CHANNEL = [channel.strip() for channel in getenv("AUTH_CHANNEL", "").split(",") if channel.strip()]
    THEME = getenv("THEME", "vapor").lower()
    USERNAME = getenv("USERNAME", "admin")
    PASSWORD = getenv("PASSWORD", "admin")
    ADMIN_USERNAME = getenv("ADMIN_USERNAME", "surfTG")
    ADMIN_PASSWORD = getenv("ADMIN_PASSWORD", "surfTG")
    SLEEP_THRESHOLD = int(getenv('SLEEP_THRESHOLD', '60'))
    WORKERS = int(getenv('WORKERS', '10'))
    MULTI_CLIENT = getenv('MULTI_CLIENT', 'False').strip().lower() == 'true'
    HIDE_CHANNEL = getenv('HIDE_CHANNEL', 'False').strip().lower() == 'true'

    # Comma-separated list of frontend origins allowed to call this API from
    # a browser, for example "https://app.example.com,https://staging.example.com".
    # Leave empty to disable origin restriction (default: no CORS headers are
    # added, matching the previous behaviour).
    FRONTEND_URLS = [u.strip().rstrip('/') for u in getenv("FRONTEND_URL", "").split(",") if u.strip()]

    # General API rate limiting, per client IP. Set either *_REQUESTS to 0 to disable.
    RATE_LIMIT_REQUESTS = int(getenv("RATE_LIMIT_REQUESTS", "120"))
    RATE_LIMIT_WINDOW = int(getenv("RATE_LIMIT_WINDOW", "60"))
    # Stricter limiting on POST /login to slow down credential brute-forcing.
    LOGIN_RATE_LIMIT_REQUESTS = int(getenv("LOGIN_RATE_LIMIT_REQUESTS", "10"))
    LOGIN_RATE_LIMIT_WINDOW = int(getenv("LOGIN_RATE_LIMIT_WINDOW", "60"))

    # Optional Redis URL, e.g. "redis://localhost:6379/0". When set, worker-bot
    # load balancing and rate limiting are shared across every instance of this
    # service instead of being tracked per-process. Safe to leave empty for a
    # single-instance deployment -- everything falls back to in-memory state.
    REDIS_URL = getenv("REDIS_URL", "").strip()

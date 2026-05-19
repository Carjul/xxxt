import os
from dotenv import load_dotenv

load_dotenv()

FB_ACCESS_TOKEN = os.getenv("FB_ACCESS_TOKEN", "")
FB_API_VERSION = os.getenv("FB_API_VERSION", "v21.0")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:5000")
SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-secret-change-me")
MONGODB_URI = os.getenv("MONGODB_URI", "")
MONGODB_DB = os.getenv("MONGODB_DB_NAME") or os.getenv("MONGODB_DB", "fb_catalog_dashboard")
TRICK_RUNNER_INTERVAL = int(os.getenv("TRICK_RUNNER_INTERVAL", "3600"))

FB_GRAPH_BASE = f"https://graph.facebook.com/{FB_API_VERSION}"

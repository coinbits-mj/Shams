import os
from dotenv import load_dotenv

load_dotenv()

# PostgreSQL
DATABASE_URL = os.environ["DATABASE_URL"]
TABLE_PREFIX = "shams_"

# Claude
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-20250514")

# Telegram
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")  # MJ's chat ID — bot only responds to this

# OpenAI (Whisper for voice transcription)
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# Rumi (coffee-pl-bot internal API)
RUMI_BASE_URL = os.environ.get("RUMI_BASE_URL", "http://localhost:8080")

# Mercury Banking (multi-account)
MERCURY_API_KEY_CLIFTON = os.environ.get("MERCURY_API_KEY_CLIFTON", os.environ.get("MERCURY_API_KEY", ""))
MERCURY_API_KEY_PLAINFIELD = os.environ.get("MERCURY_API_KEY_PLAINFIELD", "")
MERCURY_API_KEY_PERSONAL = os.environ.get("MERCURY_API_KEY_PERSONAL", "")
MERCURY_API_KEY_COINBITS = os.environ.get("MERCURY_API_KEY_COINBITS", "")

# Google
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "")

# Resend (email for magic links)
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
RESEND_FROM_EMAIL = os.environ.get("RESEND_FROM_EMAIL", "shams@updates.qcitycoffee.com")

# Flask
FLASK_SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")

# Scheduling
BRIEFING_HOUR_UTC = int(os.environ.get("BRIEFING_HOUR_UTC", "11"))  # 6am ET
EVENING_HOUR_UTC = int(os.environ.get("EVENING_HOUR_UTC", "1"))     # 8pm ET

# Flask
FLASK_PORT = int(os.environ.get("PORT", "8081"))

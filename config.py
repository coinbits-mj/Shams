import os
from dotenv import load_dotenv

load_dotenv()

# PostgreSQL
DATABASE_URL = os.environ.get("DATABASE_URL", "")
TABLE_PREFIX = "shams_"

# Claude
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-20250514")

# Telegram
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")  # MJ's chat ID — bot only responds to this

# OpenAI (Whisper for voice transcription)
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# Leo (health coach API)
LEO_API_URL = os.environ.get("LEO_API_URL", "")
LEO_API_SECRET = os.environ.get("LEO_API_SECRET", "")
LEO_USER_ID = os.environ.get("LEO_USER_ID", "1")

# Rumi (coffee-pl-bot internal API)
RUMI_BASE_URL = os.environ.get("RUMI_BASE_URL", "http://localhost:8080")

# Mercury Banking (multi-account)
MERCURY_API_KEY_CLIFTON = os.environ.get("MERCURY_API_KEY_CLIFTON", os.environ.get("MERCURY_API_KEY", ""))
MERCURY_API_KEY_PLAINFIELD = os.environ.get("MERCURY_API_KEY_PLAINFIELD", "")
MERCURY_API_KEY_PERSONAL = os.environ.get("MERCURY_API_KEY_PERSONAL", "")
MERCURY_API_KEY_COINBITS = os.environ.get("MERCURY_API_KEY_COINBITS", "")

# Google OAuth (supports multiple accounts)
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")

# Accounts to connect
GOOGLE_ACCOUNTS = {
    "personal": "maher.janajri@gmail.com",
    "coinbits": "maher@coinbits.app",
    "qcc": "maher@qcitycoffee.com",
}

# GitHub (Builder agent — PR creation)
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_OWNER = os.environ.get("GITHUB_OWNER", "coinbits-mj")

GITHUB_REPOS = {
    "shams": "Shams",
    "rumi": "coffee-pl-bot",
    "leo": "leo-health-coach",
}

# DocuSeal (self-hosted e-signatures)
DOCUSEAL_API_URL = os.environ.get("DOCUSEAL_API_URL", "")
DOCUSEAL_API_TOKEN = os.environ.get("DOCUSEAL_API_TOKEN", "")

# Resend (email for magic links)
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
RESEND_FROM_EMAIL = os.environ.get("RESEND_FROM_EMAIL", "shams@updates.qcitycoffee.com")

# Flask
FLASK_SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")

# Scheduling
BRIEFING_HOUR_UTC = int(os.environ.get("BRIEFING_HOUR_UTC", "11"))  # 6am ET — legacy, used by evening briefing
EVENING_HOUR_UTC = int(os.environ.get("EVENING_HOUR_UTC", "1"))     # 8pm ET
OVERNIGHT_HOUR_UTC = int(os.environ.get("OVERNIGHT_HOUR_UTC", "7"))  # 3am ET
STANDUP_HOUR_UTC = int(os.environ.get("STANDUP_HOUR_UTC", "11"))     # 7am ET

# Recall.ai (Meeting Bot)
RECALL_API_KEY = os.environ.get("RECALL_API_KEY", "")
RECALL_REGION = os.environ.get("RECALL_REGION", "us-east-1")
RECALL_WEBHOOK_SECRET = os.environ.get("RECALL_WEBHOOK_SECRET", "")
RECALL_BASE_URL = f"https://{RECALL_REGION}.recall.ai/api/v1"

MEETING_BOT_NAME = os.environ.get("MEETING_BOT_NAME", "Shams Notetaker")
MEETING_BOT_MAX_DAILY = int(os.environ.get("MEETING_BOT_MAX_DAILY", "10"))
MEETING_MAX_DURATION_HOURS = int(os.environ.get("MEETING_MAX_DURATION_HOURS", "3"))
MEETING_EXCLUDE_PATTERNS = os.environ.get(
    "MEETING_EXCLUDE_PATTERNS",
    "lunch,dentist,personal,block,focus time,gym,doctor,dinner"
).lower().split(",")
MEETING_BOT_DISABLED = os.environ.get("MEETING_BOT_DISABLED", "").lower() in ("1", "true", "yes")

# Flask
FLASK_PORT = int(os.environ.get("PORT", "8081"))

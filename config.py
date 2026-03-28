import os
from dotenv import load_dotenv

load_dotenv()

# PostgreSQL
DATABASE_URL = os.environ["DATABASE_URL"]
TABLE_PREFIX = "shams_"

# Claude
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-20250514")

# WhatsApp (Twilio)
TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_WHATSAPP_NUMBER = os.environ["TWILIO_WHATSAPP_NUMBER"]  # e.g. whatsapp:+14155238886
MAHER_WHATSAPP_NUMBER = os.environ["MAHER_WHATSAPP_NUMBER"]    # e.g. whatsapp:+1234567890

# Rumi (coffee-pl-bot internal API)
RUMI_BASE_URL = os.environ.get("RUMI_BASE_URL", "http://localhost:8080")

# Google
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "")

# Flask
FLASK_SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")

# Scheduling
BRIEFING_HOUR_UTC = int(os.environ.get("BRIEFING_HOUR_UTC", "11"))  # 6am ET
EVENING_HOUR_UTC = int(os.environ.get("EVENING_HOUR_UTC", "1"))     # 8pm ET

# Flask
FLASK_PORT = int(os.environ.get("PORT", "8081"))

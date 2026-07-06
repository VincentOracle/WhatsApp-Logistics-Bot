"""
Central application configuration.
All values are loaded from environment variables (see .env.example).
Placeholder defaults are provided so the app can boot in a "demo" mode
without real credentials, but every external call will clearly log
that it is using placeholder credentials.
"""
import os
from dotenv import load_dotenv

load_dotenv()


def _is_placeholder(value: str) -> bool:
    return value is None or value.strip() == "" or value.strip().lower().startswith("your_")


class Config:
    # ---- Twilio ----
    TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "your_twilio_account_sid")
    TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "your_twilio_auth_token")
    TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")

    # ---- Anthropic Claude ----
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "your_anthropic_api_key")
    CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

    # ---- OpenAI Whisper ----
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "your_openai_api_key")
    WHISPER_MODEL = os.getenv("WHISPER_MODEL", "whisper-1")

    # ---- YellowBIRD Logistics API ----
    YELLOWBIRD_API_BASE_URL = os.getenv("YELLOWBIRD_API_BASE_URL", "https://sandbox-api.yellowbird.ug/v1")
    YELLOWBIRD_API_KEY = os.getenv("YELLOWBIRD_API_KEY", "your_yellowbird_api_key")
    YELLOWBIRD_MERCHANT_ID = os.getenv("YELLOWBIRD_MERCHANT_ID", "your_merchant_id")
    YELLOWBIRD_WEBHOOK_SECRET = os.getenv("YELLOWBIRD_WEBHOOK_SECRET", "your_webhook_shared_secret")

    # ---- App ----
    DATABASE_PATH = os.getenv("DATABASE_PATH", "conversations.db")
    SESSION_TIMEOUT_MINUTES = int(os.getenv("SESSION_TIMEOUT_MINUTES", "60"))
    PORT = int(os.getenv("PORT", "5000"))
    DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"

    @classmethod
    def using_placeholder_yellowbird_key(cls) -> bool:
        return _is_placeholder(cls.YELLOWBIRD_API_KEY)

    @classmethod
    def using_placeholder_anthropic_key(cls) -> bool:
        return _is_placeholder(cls.ANTHROPIC_API_KEY)

    @classmethod
    def using_placeholder_openai_key(cls) -> bool:
        return _is_placeholder(cls.OPENAI_API_KEY)

    @classmethod
    def using_placeholder_twilio_creds(cls) -> bool:
        return _is_placeholder(cls.TWILIO_ACCOUNT_SID) or _is_placeholder(cls.TWILIO_AUTH_TOKEN)

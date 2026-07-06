"""
WhatsApp messaging channel, implemented via Twilio's WhatsApp API.

Twilio was chosen for this reference implementation because it lets a
single account cover both the messaging webhook AND authenticated
media (voice note) downloads without a separate Meta Business
verification step. Swapping to the Meta WhatsApp Cloud API only
requires changing this module — see README "Alternative channel".
"""
import requests
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse

from config import Config
from utils.logger import get_logger

logger = get_logger(__name__)

_client = None


def _get_client() -> Client:
    global _client
    if _client is None:
        _client = Client(Config.TWILIO_ACCOUNT_SID, Config.TWILIO_AUTH_TOKEN)
    return _client


def build_twiml_reply(message: str) -> str:
    """Build a synchronous TwiML response for the inbound webhook."""
    response = MessagingResponse()
    response.message(message)
    return str(response)


def send_message(to: str, body: str) -> None:
    """
    Send a message outside of the synchronous webhook response cycle
    (used for follow-ups triggered by YellowBIRD status webhooks).
    """
    if Config.using_placeholder_twilio_creds():
        logger.warning("Twilio credentials are placeholders — skipping outbound send (dry run): %s", body[:40])
        return
    try:
        client = _get_client()
        client.messages.create(from_=Config.TWILIO_WHATSAPP_NUMBER, to=to, body=body)
    except Exception:
        logger.exception("Failed to send outbound WhatsApp message via Twilio.")


def download_media(media_url: str) -> bytes:
    """
    Download a media attachment (e.g. a voice note) from Twilio.
    Twilio media URLs require HTTP Basic Auth with the account
    credentials.
    """
    response = requests.get(
        media_url,
        auth=(Config.TWILIO_ACCOUNT_SID, Config.TWILIO_AUTH_TOKEN),
        timeout=20,
    )
    response.raise_for_status()
    return response.content

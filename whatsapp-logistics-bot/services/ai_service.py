"""
AI conversation & extraction engine, powered by Anthropic Claude.

Responsible for:
  - understanding user intent
  - extracting structured delivery fields from free-form text
  - merging fields across turns (conversation-context management)
  - producing the next natural-language reply
  - classifying yes/no confirmation replies
"""
import json
import re

import anthropic

from config import Config
from prompts.system_prompt import build_system_prompt, build_user_turn
from utils.logger import get_logger

logger = get_logger(__name__)

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
    return _client


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    return text


def extract_and_reply(known_fields: dict, latest_message: str) -> dict:
    """
    Send the running field state + latest message to Claude and get back
    an updated field set plus a natural-language reply.

    Returns: {"reply": str, "fields": dict}
    Falls back to a safe default if the API is unreachable or the
    response cannot be parsed, so the conversation never hard-crashes.
    """
    if Config.using_placeholder_anthropic_key():
        logger.warning("ANTHROPIC_API_KEY is a placeholder — using rule-based fallback extraction.")
        return _fallback_extract(known_fields, latest_message)

    try:
        client = _get_client()
        response = client.messages.create(
            model=Config.CLAUDE_MODEL,
            max_tokens=600,
            system=build_system_prompt(),
            messages=[
                {"role": "user", "content": build_user_turn(known_fields, latest_message)}
            ],
        )
        raw_text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        parsed = json.loads(_strip_code_fences(raw_text))
        reply = parsed.get("reply", "Could you tell me more about the delivery?")
        fields = {**known_fields, **{k: v for k, v in parsed.get("fields", {}).items() if v not in (None, "")}}
        return {"reply": reply, "fields": fields}
    except json.JSONDecodeError:
        logger.error("Claude returned non-JSON output; falling back to rule-based extraction.")
        return _fallback_extract(known_fields, latest_message)
    except anthropic.APIError:
        logger.exception("Anthropic API error during extraction.")
        return _fallback_extract(known_fields, latest_message)
    except Exception:
        logger.exception("Unexpected error calling Claude.")
        return _fallback_extract(known_fields, latest_message)


def classify_yes_no(message: str) -> str:
    """
    Lightweight local intent classifier for the confirmation step.
    Returns "yes", "no", or "unclear". Kept local (no API call) since
    this is a cheap, low-ambiguity decision on the confirmation turn.
    """
    normalized = message.strip().lower()
    yes_words = {"yes", "yeah", "yep", "confirm", "ok", "okay", "sure", "go ahead", "correct", "book it"}
    no_words = {"no", "nope", "cancel", "wrong", "change", "not yet", "wait"}
    if any(normalized == w or normalized.startswith(w + " ") for w in yes_words):
        return "yes"
    if any(normalized == w or normalized.startswith(w + " ") for w in no_words):
        return "no"
    return "unclear"


def _fallback_extract(known_fields: dict, latest_message: str) -> dict:
    """
    Minimal, dependency-free fallback so the bot remains functional
    (in a degraded mode) if the Claude API key is missing/unreachable.
    It does not attempt real NLU — it simply asks for the next missing
    field in a fixed order.
    """
    from utils.validators import REQUIRED_FIELDS, missing_required_fields

    field_prompts = {
        "pickup_location": "Where should the rider pick up the item from?",
        "delivery_location": "Where should it be delivered to?",
        "recipient_name": "What's the recipient's full name?",
        "recipient_phone": "What's the recipient's phone number?",
        "item_description": "What item(s) are you sending?",
        "quantity": "How many units/items is that?",
    }
    missing = missing_required_fields(known_fields)
    if not missing:
        return {"reply": "Got everything I need, thank you.", "fields": known_fields}
    next_field = missing[0]
    return {
        "reply": f"Thanks. {field_prompts[next_field]}",
        "fields": known_fields,
    }

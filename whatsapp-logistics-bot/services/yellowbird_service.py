"""
YellowBIRD Logistics API client.

Builds the delivery-request payload from collected conversation
fields and submits it to YellowBIRD's inbound order endpoint.

NOTE: Exact field names/endpoint paths should be confirmed against
the real YellowBIRD API documentation once sandbox access is granted
(the assignment brief describes the data model but not the literal
JSON schema/endpoint path). The payload shape below follows directly
from the brief: pickup details, delivery/recipient details, product
info, and an order reference. Adjust `_build_payload` and the
endpoint path in `create_delivery` to match the real spec — everything
else in this module (auth, error handling, response parsing) will not
need to change.
"""
import time
import uuid

import requests

from config import Config
from utils.logger import get_logger

logger = get_logger(__name__)

CREATE_DELIVERY_PATH = "/deliveries"
REQUEST_TIMEOUT_SECONDS = 15


def _build_order_reference(phone_number: str) -> str:
    digits = "".join(ch for ch in phone_number if ch.isdigit())[-6:]
    return f"WA-{digits}-{int(time.time())}-{uuid.uuid4().hex[:4]}"


def build_payload(fields: dict, sender_phone: str) -> dict:
    order_reference = _build_order_reference(sender_phone)
    payload = {
        "merchant_id": Config.YELLOWBIRD_MERCHANT_ID,
        "order_reference": order_reference,
        "pickup": {
            "location_name": fields.get("pickup_location"),
            "address": fields.get("pickup_location"),
        },
        "delivery": {
            "recipient_name": fields.get("recipient_name"),
            "recipient_phone": fields.get("recipient_phone"),
            "address": fields.get("delivery_location"),
            "delivery_window": fields.get("delivery_window"),
        },
        "items": [
            {
                "description": fields.get("item_description"),
                "quantity": int(fields.get("quantity")),
            }
        ],
        "special_instructions": fields.get("special_instructions"),
        "declared_value": fields.get("package_value"),
        "source_channel": "whatsapp_ai_chatbot",
    }
    return order_reference, payload


def create_delivery(fields: dict, sender_phone: str) -> dict:
    """
    Submit a delivery request to YellowBIRD.

    Returns a normalized result dict:
      {"success": bool, "order_reference": str, "message": str, "raw": dict|None}
    Never raises — all failure modes are converted into a structured
    result so the chatbot can always give the customer a clear answer.
    """
    order_reference, payload = build_payload(fields, sender_phone)

    if Config.using_placeholder_yellowbird_key():
        logger.warning("YELLOWBIRD_API_KEY is a placeholder — simulating a successful submission (demo mode).")
        return {
            "success": True,
            "order_reference": order_reference,
            "message": (
                "(Demo mode — no real YellowBIRD credentials configured) "
                "Your delivery request was validated and would be submitted as order "
                f"{order_reference}."
            ),
            "raw": None,
        }

    url = f"{Config.YELLOWBIRD_API_BASE_URL.rstrip('/')}{CREATE_DELIVERY_PATH}"
    headers = {
        "Authorization": f"Bearer {Config.YELLOWBIRD_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
        return {
            "success": True,
            "order_reference": data.get("order_reference", order_reference),
            "message": f"Your delivery has been booked! Order reference: {data.get('order_reference', order_reference)}.",
            "raw": data,
        }
    except requests.exceptions.Timeout:
        logger.error("YellowBIRD API request timed out.")
        return {
            "success": False,
            "order_reference": order_reference,
            "message": "YellowBIRD's system is taking too long to respond. Please try again shortly.",
            "raw": None,
        }
    except requests.exceptions.HTTPError:
        logger.error("YellowBIRD API returned an HTTP error: %s", response.status_code)
        detail = ""
        try:
            detail = response.json().get("message", "")
        except Exception:
            pass
        return {
            "success": False,
            "order_reference": order_reference,
            "message": f"YellowBIRD rejected the request ({response.status_code}). {detail}".strip(),
            "raw": None,
        }
    except requests.exceptions.RequestException:
        logger.exception("Network error calling YellowBIRD API.")
        return {
            "success": False,
            "order_reference": order_reference,
            "message": "Couldn't reach YellowBIRD's system right now. Please try again shortly.",
            "raw": None,
        }

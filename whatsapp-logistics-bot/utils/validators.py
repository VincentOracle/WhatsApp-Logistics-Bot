"""
Validation helpers: required-field checks, Uganda phone normalization,
and HMAC signature verification for inbound YellowBIRD webhooks.
"""
import hashlib
import hmac
import re

REQUIRED_FIELDS = [
    "pickup_location",
    "delivery_location",
    "recipient_name",
    "recipient_phone",
    "item_description",
    "quantity",
]

OPTIONAL_FIELDS = [
    "delivery_window",
    "special_instructions",
    "package_value",
]


def missing_required_fields(fields: dict) -> list:
    """Return the list of required field names that are still empty/missing."""
    missing = []
    for key in REQUIRED_FIELDS:
        value = fields.get(key)
        if value is None:
            missing.append(key)
        elif isinstance(value, str) and not value.strip():
            missing.append(key)
    return missing


def normalize_ug_phone(raw_phone: str) -> str:
    """
    Normalize a Ugandan phone number to E.164 (+2567XXXXXXXX).
    Falls back to returning the cleaned original if it doesn't match
    a recognizable Ugandan pattern (still allows international numbers).
    """
    if not raw_phone:
        return raw_phone
    digits = re.sub(r"[^\d+]", "", raw_phone.strip())
    if digits.startswith("+256"):
        return digits
    if digits.startswith("256"):
        return "+" + digits
    if digits.startswith("0") and len(digits) == 10:
        return "+256" + digits[1:]
    if digits.startswith("7") and len(digits) == 9:
        return "+256" + digits
    if digits.startswith("+"):
        return digits
    return raw_phone.strip()


def is_valid_quantity(value) -> bool:
    try:
        return int(value) > 0
    except (TypeError, ValueError):
        return False


def verify_hmac_signature(payload_bytes: bytes, signature_header: str, shared_secret: str) -> bool:
    """
    Verify an inbound YellowBIRD webhook's HMAC-SHA256 signature.
    Expects signature_header to be a hex digest, optionally prefixed
    with 'sha256='.
    """
    if not signature_header or not shared_secret:
        return False
    provided = signature_header.strip()
    if provided.startswith("sha256="):
        provided = provided[len("sha256="):]
    expected = hmac.new(
        shared_secret.encode("utf-8"), payload_bytes, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(provided, expected)

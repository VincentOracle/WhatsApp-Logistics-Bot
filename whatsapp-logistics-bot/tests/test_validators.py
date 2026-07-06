"""
Basic unit tests for validation helpers. Run with:
    python -m pytest tests/ -v
These do not require any API keys since they only exercise pure
functions (no network calls).
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.validators import (
    missing_required_fields,
    normalize_ug_phone,
    is_valid_quantity,
    verify_hmac_signature,
)
import hashlib
import hmac


def test_missing_required_fields_all_missing():
    assert set(missing_required_fields({})) == {
        "pickup_location", "delivery_location", "recipient_name",
        "recipient_phone", "item_description", "quantity",
    }


def test_missing_required_fields_partial():
    fields = {
        "pickup_location": "Ntinda",
        "delivery_location": "Kansanga",
        "recipient_name": "Grace",
        "recipient_phone": "",
        "item_description": None,
        "quantity": 2,
    }
    missing = missing_required_fields(fields)
    assert "recipient_phone" in missing
    assert "item_description" in missing
    assert "pickup_location" not in missing
    assert "quantity" not in missing


def test_normalize_ug_phone_local_format():
    assert normalize_ug_phone("0772123456") == "+256772123456"


def test_normalize_ug_phone_already_international():
    assert normalize_ug_phone("+256772123456") == "+256772123456"


def test_normalize_ug_phone_without_plus():
    assert normalize_ug_phone("256772123456") == "+256772123456"


def test_is_valid_quantity():
    assert is_valid_quantity(3) is True
    assert is_valid_quantity("5") is True
    assert is_valid_quantity(0) is False
    assert is_valid_quantity("two") is False
    assert is_valid_quantity(None) is False


def test_verify_hmac_signature_valid():
    secret = "test_secret"
    body = b'{"event_type": "ORDER_RECEIVED"}'
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_hmac_signature(body, sig, secret) is True
    assert verify_hmac_signature(body, f"sha256={sig}", secret) is True


def test_verify_hmac_signature_invalid():
    assert verify_hmac_signature(b"data", "bad_signature", "secret") is False
    assert verify_hmac_signature(b"data", "", "secret") is False

"""
WhatsApp AI Logistics Chatbot — Flask entrypoint.

Routes:
  POST /webhook/whatsapp   Twilio inbound message webhook (text + voice)
  POST /webhook/yellowbird Inbound YellowBIRD delivery-status webhook
  GET  /health              Liveness check

Conversation state machine (per phone number, persisted in SQLite):
  COLLECTING  -> extracting fields turn by turn until all required
                 fields are present
  CONFIRMING  -> summary shown, waiting for explicit yes/no
  SUBMITTED   -> order sent to YellowBIRD; new message starts fresh
"""
from flask import Flask, request, Response

from config import Config
from models import conversation_store as store
from services import ai_service, whatsapp_service, transcription_service, yellowbird_service
from utils.logger import get_logger
from utils.validators import (
    missing_required_fields,
    normalize_ug_phone,
    is_valid_quantity,
    verify_hmac_signature,
)
from prompts.system_prompt import build_confirmation_summary

app = Flask(__name__)
logger = get_logger(__name__)

WELCOME_MESSAGE = (
    "Hi! I'm YellowBIRD's delivery assistant. Tell me what you'd like delivered — "
    "pickup point, drop-off, recipient details, and the item — and I'll set it up. "
    "You can also send a voice note."
)


@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok"}, 200


@app.route("/webhook/whatsapp", methods=["POST"])
def whatsapp_webhook():
    sender = request.form.get("From", "").strip()
    body = (request.form.get("Body") or "").strip()
    num_media = int(request.form.get("NumMedia", "0") or "0")

    if not sender:
        return Response(whatsapp_service.build_twiml_reply("Sorry, I couldn't identify your number."),
                         mimetype="application/xml")

    # ---- Voice note handling ----
    if num_media > 0:
        content_type = request.form.get("MediaContentType0", "")
        if content_type.startswith("audio/"):
            media_url = request.form.get("MediaUrl0")
            try:
                audio_bytes = whatsapp_service.download_media(media_url)
                transcript = transcription_service.transcribe_audio(audio_bytes)
            except Exception:
                logger.exception("Failed to download/transcribe voice note.")
                transcript = ""

            if not transcript:
                reply = "Sorry, I couldn't understand that voice note. Could you type your message instead?"
                return Response(whatsapp_service.build_twiml_reply(reply), mimetype="application/xml")
            body = transcript  # process exactly like a text message from here on
        else:
            reply = "I can only process text or voice notes at the moment."
            return Response(whatsapp_service.build_twiml_reply(reply), mimetype="application/xml")

    if not body:
        return Response(whatsapp_service.build_twiml_reply(WELCOME_MESSAGE), mimetype="application/xml")

    reply_text = handle_message(sender, body)
    return Response(whatsapp_service.build_twiml_reply(reply_text), mimetype="application/xml")


def handle_message(sender: str, body: str) -> str:
    """Core conversation state machine. Returns the reply text to send."""
    convo = store.get_or_create(sender)
    stage = convo["stage"]
    fields = convo["fields"]
    history = convo["history"]

    history.append({"role": "user", "text": body})

    # A completed order: any new message starts a brand new conversation.
    if stage == store.STAGE_SUBMITTED:
        store.reset(sender)
        convo = store.get_or_create(sender)
        stage, fields, history = convo["stage"], convo["fields"], convo["history"]
        history.append({"role": "user", "text": body})

    if stage == store.STAGE_CONFIRMING:
        intent = ai_service.classify_yes_no(body)
        if intent == "yes":
            return _submit_order(sender, fields, history)
        elif intent == "no":
            store.save(sender, store.STAGE_COLLECTING, fields, history)
            reply = "No problem — what would you like to change?"
            history.append({"role": "assistant", "text": reply})
            store.save(sender, store.STAGE_COLLECTING, fields, history)
            return reply
        else:
            # Unclear reply while confirming: treat as a correction/extra info,
            # re-run extraction, then re-show the confirmation.
            result = ai_service.extract_and_reply(fields, body)
            fields = _clean_fields(result["fields"])
            summary = build_confirmation_summary(fields)
            history.append({"role": "assistant", "text": summary})
            store.save(sender, store.STAGE_CONFIRMING, fields, history)
            return summary

    # ---- STAGE_COLLECTING ----
    result = ai_service.extract_and_reply(fields, body)
    fields = _clean_fields(result["fields"])
    still_missing = missing_required_fields(fields)

    if not still_missing:
        summary = build_confirmation_summary(fields)
        history.append({"role": "assistant", "text": summary})
        store.save(sender, store.STAGE_CONFIRMING, fields, history)
        return summary

    reply = result["reply"]
    history.append({"role": "assistant", "text": reply})
    store.save(sender, store.STAGE_COLLECTING, fields, history)
    return reply


def _clean_fields(fields: dict) -> dict:
    cleaned = dict(fields)
    if cleaned.get("recipient_phone"):
        cleaned["recipient_phone"] = normalize_ug_phone(str(cleaned["recipient_phone"]))
    if cleaned.get("quantity") is not None and not is_valid_quantity(cleaned.get("quantity")):
        cleaned["quantity"] = None  # invalid quantity is treated as still-missing
    return cleaned


def _submit_order(sender: str, fields: dict, history: list) -> str:
    still_missing = missing_required_fields(fields)
    if still_missing:
        # Safety net: shouldn't normally happen since we only reach
        # CONFIRMING once all required fields are present.
        store.save(sender, store.STAGE_COLLECTING, fields, history)
        reply = "Looks like I'm still missing some details before I can book this. Let's continue."
        history.append({"role": "assistant", "text": reply})
        store.save(sender, store.STAGE_COLLECTING, fields, history)
        return reply

    result = yellowbird_service.create_delivery(fields, sender)
    if result["success"]:
        store.save(sender, store.STAGE_SUBMITTED, fields, history, order_reference=result["order_reference"])
        reply = result["message"] + " You'll get status updates here as your order progresses."
    else:
        # Stay in CONFIRMING so the user can just say "yes" again to retry.
        store.save(sender, store.STAGE_CONFIRMING, fields, history)
        reply = f"{result['message']} Reply *yes* to try again."
    history.append({"role": "assistant", "text": reply})
    store.save(sender, store.STAGE_SUBMITTED if result["success"] else store.STAGE_CONFIRMING,
               fields, history, order_reference=result.get("order_reference"))
    return reply


@app.route("/webhook/yellowbird", methods=["POST"])
def yellowbird_webhook():
    """
    Inbound webhook receiver for YellowBIRD delivery status events:
    ORDER_RECEIVED, RIDER_ASSIGNED, PICKUP_CONFIRMED, IN_TRANSIT,
    DELIVERY_CONFIRMED, DELIVERY_FAILED.
    """
    raw_body = request.get_data()
    signature = request.headers.get("X-YellowBird-Signature", "")

    if not verify_hmac_signature(raw_body, signature, Config.YELLOWBIRD_WEBHOOK_SECRET):
        logger.warning("Rejected YellowBIRD webhook with invalid signature.")
        return {"error": "invalid signature"}, 401

    payload = request.get_json(silent=True) or {}
    event_type = payload.get("event_type")
    order_reference = payload.get("order_reference")
    recipient_phone = (payload.get("delivery") or {}).get("recipient_phone")

    logger.info("Received YellowBIRD event %s for order %s", event_type, order_reference)

    status_messages = {
        "ORDER_RECEIVED": "Your order has been received by YellowBIRD.",
        "RIDER_ASSIGNED": "A rider has been assigned to your delivery.",
        "PICKUP_CONFIRMED": "Your item has been picked up and is on its way to the rider.",
        "IN_TRANSIT": "Your delivery is now in transit.",
        "DELIVERY_CONFIRMED": "Your delivery has been completed. Thank you!",
        "DELIVERY_FAILED": "The delivery attempt was unsuccessful. YellowBIRD will retry or contact you.",
    }
    message = status_messages.get(event_type)
    if message and recipient_phone:
        whatsapp_number = f"whatsapp:{normalize_ug_phone(recipient_phone)}"
        whatsapp_service.send_message(whatsapp_number, f"{message} (Order {order_reference})")

    return {"status": "received"}, 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=Config.PORT, debug=Config.DEBUG)

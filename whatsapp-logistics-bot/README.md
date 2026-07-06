# WhatsApp AI Logistics Chatbot (YellowBIRD)

An AI-powered WhatsApp chatbot that lets a customer create a delivery
request purely through conversation (text or voice note). It extracts
the required delivery information, tracks what's still missing across
turns, converts the finished conversation into YellowBIRD's delivery
payload, and submits it to the YellowBIRD Logistics API.

## Architecture

```
WhatsApp user
     │
     ▼
Twilio WhatsApp API  ──(inbound webhook, POST form-encoded)──▶  Flask app.py
     ▲                                                              │
     │ TwiML reply (sync)                                          │
     └──────────────────────────────────────────────────────────────
                                                                     │
                              ┌──────────────────────────────────────┤
                              ▼                                      ▼
                    services/transcription_service.py      services/ai_service.py
                    (voice note → text, OpenAI Whisper)     (Claude: extract fields,
                              │                               decide next question)
                              └───────────────┬──────────────────────┘
                                               ▼
                                  models/conversation_store.py
                                  (SQLite: per-number state machine
                                   COLLECTING → CONFIRMING → SUBMITTED)
                                               │
                                               ▼
                                  services/yellowbird_service.py
                                  (builds payload, POSTs to YellowBIRD)
                                               │
                                               ▼
                                     YellowBIRD Logistics API
                                               │
                              (async status events: RIDER_ASSIGNED, etc.)
                                               ▼
                              POST /webhook/yellowbird  (HMAC-verified)
                                               │
                                               ▼
                              services/whatsapp_service.send_message()
                              (push status update back to the customer)
```

**Why this structure:** 
Each external integration (Twilio, Claude, Whisper,
YellowBIRD) lives behind its own thin service module with a narrow,
typed interface. `app.py` only orchestrates the conversation state
machine — it never talks to a third-party SDK directly. That keeps the
AI conversation logic, the messaging channel, and the logistics API
independently swappable and testable.

## Project layout

```
app.py                          Flask routes + conversation state machine
config.py                       Env-driven configuration
prompts/system_prompt.py        Claude system prompt + confirmation summary
services/ai_service.py          Claude-based extraction & reply generation
services/transcription_service.py  Whisper speech-to-text
services/whatsapp_service.py    Twilio send/receive/media download
services/yellowbird_service.py  YellowBIRD payload builder + API client
models/conversation_store.py    SQLite-backed per-number session state
utils/validators.py             Required-field checks, phone normalization, HMAC verification
utils/logger.py                 Logging with automatic PII redaction
tests/test_validators.py        Unit tests for pure-function logic (no API keys needed)
```

## How the conversation flow works

1. **COLLECTING** — Every inbound message (or transcribed voice note) is
   sent to Claude along with the fields already known. Claude returns
   an updated field set (merged, never overwriting a known value
   unless the user corrected it) and the next thing to ask about. Only
   missing fields are ever asked for.
2. Once all **required fields** are present, the bot shows a summary
   and moves to **CONFIRMING**.
3. **CONFIRMING** — A lightweight local yes/no classifier (no API call
   needed) reads the reply:
   - `yes` → build the YellowBIRD payload, submit it, move to **SUBMITTED**.
   - `no` → go back to **COLLECTING**.
   - anything else → treated as a correction, re-extracted, summary re-shown.
4. **SUBMITTED** — the next message from that number starts a fresh
   conversation automatically.

Required fields: `pickup_location`, `delivery_location`,
`recipient_name`, `recipient_phone`, `item_description`, `quantity`.
Optional fields captured opportunistically: `delivery_window`,
`special_instructions`, `package_value`.

State is persisted to SQLite (`conversations.db`) keyed by phone
number, so the bot survives restarts and doesn't lose context
mid-conversation. Sessions older than `SESSION_TIMEOUT_MINUTES`
(default 60) auto-reset.

## Voice note support

Twilio delivers WhatsApp voice notes as an `audio/ogg` media
attachment on the inbound webhook. The flow is:

1. Detect `NumMedia > 0` and `MediaContentType0` starting with `audio/`.
2. Download the file from Twilio (`services/whatsapp_service.download_media`,
   authenticated with the Twilio account credentials).
3. Transcribe it via OpenAI Whisper (`services/transcription_service.transcribe_audio`).
4. Feed the transcript into **exactly the same** `handle_message()`
   path used for typed text — no separate logic branch.

## Setup

### 1. Prerequisites
- Python 3.10+
- A Twilio account with the WhatsApp Sandbox (or an approved WhatsApp
  Business sender) enabled
- An Anthropic API key (Claude)
- An OpenAI API key (Whisper, for voice notes)
- YellowBIRD sandbox API credentials (request from YellowBIRD's
  integration team)
- `ngrok` (or similar) for exposing your local server during development

### 2. Install

```bash
git clone <this-repo>
cd whatsapp-logistics-bot
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
```

Fill in `.env` with your real credentials. **The app will still boot
and run with the placeholder values** — every external integration
detects placeholder credentials and degrades gracefully (see "Demo
mode" below), which is useful for reviewing the code without live keys.

### 4. Run locally

```bash
python app.py
# or, for production-style serving:
gunicorn -w 2 -b 0.0.0.0:5000 app:app
```

### 5. Expose it and wire up Twilio

```bash
ngrok http 5000
```

In the [Twilio Console](https://console.twilio.com) → Messaging → Try it
out → WhatsApp Sandbox, set:
- **When a message comes in**: `https://<your-ngrok-domain>/webhook/whatsapp` (POST)

Join the sandbox from your phone (Twilio gives you a `join <code>` message
to send), then message the sandbox number to start the conversation.

### 6. Wire up the YellowBIRD status webhook (optional, bidirectional flow)

Set your YellowBIRD integration's webhook URL to:
`https://<your-domain>/webhook/yellowbird`

Inbound events are verified using HMAC-SHA256 over the raw request body
with `YELLOWBIRD_WEBHOOK_SECRET`, expected in an `X-YellowBird-Signature`
header (hex digest, optionally prefixed `sha256=`). Adjust the header
name in `app.py::yellowbird_webhook` if YellowBIRD's real docs specify
a different header.

## Demo mode (no real API keys)

Each service independently detects placeholder credentials and logs a
clear warning instead of crashing:
- **No Anthropic key** → falls back to a fixed-order field-by-field
  question flow (functional, but not true NLU).
- **No OpenAI key** → voice notes politely fail with "please type
  instead" rather than crashing.
- **No YellowBIRD key** → `create_delivery()` returns a simulated
  success with a generated order reference, so the full conversation
  flow can be demoed end-to-end.
- **No Twilio credentials** → outbound proactive sends (status
  webhook follow-ups) are skipped with a log line; the inbound
  webhook + TwiML reply path doesn't require them at all.

## Error handling & validation

- `utils/validators.missing_required_fields` is the single source of
  truth for "are we done collecting" — checked before ever calling
  YellowBIRD.
- Phone numbers are normalized to E.164 (`normalize_ug_phone`) before
  submission.
- Quantity is validated as a positive integer; invalid values are
  treated as still-missing so the bot re-asks rather than submitting
  garbage.
- All YellowBIRD API failures (timeout, HTTP error, network error) are
  caught and converted into a clear customer-facing message, and the
  conversation stays in **CONFIRMING** so the user can just reply
  `yes` again to retry without re-entering everything.
- The logger strips number-like sequences (phone numbers) from log
  output at write time, in keeping with YellowBIRD's stated handling
  of customer PII.

## Testing

```bash
python -m pytest tests/ -v
```

The included tests cover the pure validation/normalization logic and
require no API keys or network access. For a full end-to-end manual
test, use the Twilio Sandbox as described above, or POST directly to
the webhook:

```bash
curl -X POST http://localhost:5000/webhook/whatsapp \
  -d "From=whatsapp:+256772123456" \
  -d "Body=I need to send a laptop from Garden City to Bugolobi"
```

## Notes on the YellowBIRD payload shape

The assignment brief describes YellowBIRD's data model (pickup
location, recipient details, product info, order reference) but not
the literal field names/endpoint path of the real API. `services/yellowbird_service.py`
isolates this mapping in `build_payload()` and the `CREATE_DELIVERY_PATH`
constant — once real sandbox API docs are available from YellowBIRD's
integration team, only that one function and constant need to change.

## Scaling notes (beyond this take-home scope)

- Swap `models/conversation_store.py`'s SQLite backend for Redis/Postgres
  for multi-instance deployments (interface is already narrow: `get_or_create`,
  `save`, `reset`).
- Move the Twilio webhook handler to enqueue work and respond
  immediately, doing the Claude/YellowBIRD calls asynchronously, if
  response latency ever approaches Twilio's timeout.
- `services/whatsapp_service.py` is the only module that would need to
  change to move from Twilio to the Meta WhatsApp Cloud API directly.

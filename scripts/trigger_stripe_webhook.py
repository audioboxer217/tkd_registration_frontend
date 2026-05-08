#!/usr/bin/env python3
"""
Simulate a Stripe checkout webhook event for local debugging.

Usage:
    python scripts/trigger_stripe_webhook.py <checkout_session_id> [--failed] [payment_intent_id]

Examples:
    python scripts/trigger_stripe_webhook.py cs_test_abc123                         # completed
    python scripts/trigger_stripe_webhook.py cs_test_abc123 pi_test_xyz789          # completed + payment_intent
    python scripts/trigger_stripe_webhook.py cs_test_abc123 --failed                # expired/failed

Requires STRIPE_WEBHOOK_SECRET to be set (the whsec_... from `stripe listen`).
"""

import hashlib
import hmac
import json

# ---------------------------------------------------------------------------
# Config — edit or override via env vars
# ---------------------------------------------------------------------------
import os
import sys
import time

import urllib.error
import urllib.request

WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "http://localhost:5001/api/v1/webhooks/stripe")


def sign_payload(payload: str, secret: str, timestamp: int) -> str:
    """Reproduce Stripe's webhook signature algorithm."""
    signed_payload = f"{timestamp}.{payload}"
    return hmac.new(secret.encode("utf-8"), signed_payload.encode("utf-8"), hashlib.sha256).hexdigest()


def trigger(checkout_session_id: str, failed: bool = False, payment_intent_id: str = "pi_test_simulated") -> None:
    if not WEBHOOK_SECRET:
        print("ERROR: STRIPE_WEBHOOK_SECRET is not set. Load your frontend.env first.")
        sys.exit(1)

    timestamp = int(time.time())

    if failed:
        event_type = "checkout.session.expired"
        session_status = "expired"
        payment_status = "unpaid"
    else:
        event_type = "checkout.session.completed"
        session_status = "complete"
        payment_status = "paid"

    payload = json.dumps(
        {
            "id": "evt_test_simulated",
            "object": "event",
            "type": event_type,
            "data": {
                "object": {
                    "id": checkout_session_id,
                    "object": "checkout.session",
                    "payment_intent": None if failed else payment_intent_id,
                    "status": session_status,
                    "payment_status": payment_status,
                }
            },
        },
        separators=(",", ":"),
    )

    sig = sign_payload(payload, WEBHOOK_SECRET, timestamp)
    headers = {
        "Content-Type": "application/json",
        "Stripe-Signature": f"t={timestamp},v1={sig}",
    }

    print(f"POST {WEBHOOK_URL}")
    print(f"  event               : {event_type}")
    print(f"  checkout_session_id : {checkout_session_id}")
    if not failed:
        print(f"  payment_intent_id   : {payment_intent_id}")

    req = urllib.request.Request(WEBHOOK_URL, data=payload.encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            print(f"  → {resp.status} {resp.read().decode('utf-8', errors='replace')}")
    except urllib.error.HTTPError as e:
        print(f"  → {e.code} {e.read().decode('utf-8', errors='replace')}")
    except urllib.error.URLError as e:
        print(f"  ERROR: {e.reason}")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cs_id = sys.argv[1]
    args = sys.argv[2:]

    is_failed = "--failed" in args
    remaining = [a for a in args if a != "--failed"]
    pi_id = remaining[0] if remaining else "pi_test_simulated"

    trigger(cs_id, failed=is_failed, payment_intent_id=pi_id)

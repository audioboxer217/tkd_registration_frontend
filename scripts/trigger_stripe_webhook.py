#!/usr/bin/env python3
"""
Simulate a Stripe checkout.session.completed webhook for local debugging.

Usage:
    python scripts/trigger_stripe_webhook.py <checkout_session_id> [payment_intent_id]

Example:
    python scripts/trigger_stripe_webhook.py cs_test_abc123 pi_test_xyz789

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

import requests

WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "http://localhost:5001/api/v1/webhooks/stripe")


def sign_payload(payload: str, secret: str, timestamp: int) -> str:
    """Reproduce Stripe's webhook signature algorithm."""
    signed_payload = f"{timestamp}.{payload}"
    return hmac.new(secret.encode("utf-8"), signed_payload.encode("utf-8"), hashlib.sha256).hexdigest()


def trigger(checkout_session_id: str, payment_intent_id: str = "pi_test_simulated") -> None:
    if not WEBHOOK_SECRET:
        print("ERROR: STRIPE_WEBHOOK_SECRET is not set. Load your frontend.env first.")
        sys.exit(1)

    timestamp = int(time.time())
    payload = json.dumps(
        {
            "id": "evt_test_simulated",
            "object": "event",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": checkout_session_id,
                    "object": "checkout.session",
                    "payment_intent": payment_intent_id,
                    "status": "complete",
                    "payment_status": "paid",
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
    print(f"  checkout_session_id : {checkout_session_id}")
    print(f"  payment_intent_id   : {payment_intent_id}")

    resp = requests.post(WEBHOOK_URL, data=payload, headers=headers)
    print(f"  → {resp.status_code} {resp.text}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cs_id = sys.argv[1]
    pi_id = sys.argv[2] if len(sys.argv) > 2 else "pi_test_simulated"
    trigger(cs_id, pi_id)

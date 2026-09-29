"""Sign and send a test payment webhook (for live demos).

Usage:
  python scripts/send_webhook.py --booking-id <uuid> --status SUCCESS --amount 299.00
  python scripts/send_webhook.py --booking-id <uuid> --status FAILED --amount 299.00 --event-id evt-2
Env: API_URL (default http://localhost:8000), WEBHOOK_SECRET.
"""

import argparse
import hashlib
import hmac
import json
import os
import urllib.request
import uuid
from datetime import datetime, timezone

API_URL = os.environ.get("API_URL", "http://localhost:8000")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "change-me-webhook-secret")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--booking-id", required=True)
    p.add_argument("--status", default="SUCCESS", choices=["SUCCESS", "FAILED"])
    p.add_argument("--amount", default="299.00")
    p.add_argument("--event-id", default=f"evt-{uuid.uuid4().hex[:8]}")
    p.add_argument("--provider-reference", default=f"demo_{uuid.uuid4().hex[:8]}")
    args = p.parse_args()

    payload = {
        "event_id": args.event_id,
        "provider_reference": args.provider_reference,
        "booking_id": args.booking_id,
        "status": args.status,
        "amount": args.amount,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    raw = json.dumps(payload).encode()
    sig = hmac.new(WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    req = urllib.request.Request(
        f"{API_URL}/api/v1/payments/webhook/",
        data=raw,
        headers={"Content-Type": "application/json", "X-Signature": sig},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        print(resp.status, resp.read().decode())


if __name__ == "__main__":
    main()

import hashlib
import hmac
import time


def sign_webhook_payload(secret: str, timestamp: str, body: str) -> str:
    """Create an HMAC-SHA256 signature for a webhook payload.

    Scheme mirrors Stripe's: sign the string "{timestamp}.{body}" so the
    receiver can reconstruct it from the X-ReviewPulse-Timestamp header and
    the raw request body before JSON parsing.

    Using a constant-time comparison (hmac.compare_digest) on the receiver
    side prevents timing attacks. Verifying the timestamp prevents replays
    (reject if |now - timestamp| > 5 minutes).

    Example verification (Python):
        import hmac, hashlib, time
        sig = hmac.new(secret.encode(), f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()
        valid = hmac.compare_digest(sig, received_sig)
        fresh = abs(time.time() - int(ts)) < 300
    """
    message = f"{timestamp}.{body}"
    return hmac.new(
        secret.encode(),
        message.encode(),
        hashlib.sha256,
    ).hexdigest()


def current_unix_timestamp() -> str:
    return str(int(time.time()))

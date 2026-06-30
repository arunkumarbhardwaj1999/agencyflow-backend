"""Payment gateway integration — Razorpay (domestic) and Stripe (international).

When real API keys are not configured the module falls back to a local "mock"
mode so the full payment-link -> webhook -> paid flow can be exercised without
external accounts. Provider SDKs are imported lazily so the app boots even if
the optional packages are missing.
"""

import hashlib
import hmac
import json
from dataclasses import dataclass
from decimal import Decimal

from app.core.config import get_settings

settings = get_settings()

RAZORPAY = "razorpay"
STRIPE = "stripe"
MOCK = "mock"


class PaymentError(Exception):
    pass


@dataclass
class PaymentLink:
    provider: str
    url: str
    order_id: str


def _to_minor_units(amount: Decimal) -> int:
    """Convert a rupee/dollar amount to the smallest currency unit (paise/cents)."""
    return int((Decimal(amount) * 100).quantize(Decimal("1")))


def create_payment_link(
    *,
    provider: str,
    invoice_id: str,
    invoice_number: str,
    amount: Decimal,
    currency: str,
    customer_name: str,
    customer_email: str | None,
) -> PaymentLink:
    """Create a hosted payment link for an invoice."""
    if provider == RAZORPAY and settings.razorpay_enabled:
        return _razorpay_link(invoice_number, amount, currency, customer_name, customer_email)
    if provider == STRIPE and settings.stripe_enabled:
        return _stripe_link(invoice_number, amount, currency, customer_email)

    # Mock fallback for local development / testing.
    if not settings.payments_mock:
        raise PaymentError(
            f"{provider} is not configured. Set the API keys or enable PAYMENTS_MOCK."
        )
    return PaymentLink(
        provider=MOCK,
        url=f"{settings.frontend_url}/pay/mock/{invoice_id}",
        order_id=f"mock_{invoice_id}",
    )


def _razorpay_link(
    invoice_number: str,
    amount: Decimal,
    currency: str,
    customer_name: str,
    customer_email: str | None,
) -> PaymentLink:
    try:
        import razorpay
    except ImportError as exc:  # pragma: no cover
        raise PaymentError("razorpay package not installed") from exc

    client = razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))
    payload = {
        "amount": _to_minor_units(amount),
        "currency": currency,
        "accept_partial": False,
        "description": f"Invoice {invoice_number}",
        "customer": {"name": customer_name, "email": customer_email or ""},
        "notify": {"email": bool(customer_email)},
        "reminder_enable": True,
        "notes": {"invoice_number": invoice_number},
    }
    link = client.payment_link.create(payload)
    return PaymentLink(provider=RAZORPAY, url=link["short_url"], order_id=link["id"])


def _stripe_link(
    invoice_number: str,
    amount: Decimal,
    currency: str,
    customer_email: str | None,
) -> PaymentLink:
    try:
        import stripe
    except ImportError as exc:  # pragma: no cover
        raise PaymentError("stripe package not installed") from exc

    stripe.api_key = settings.stripe_secret_key
    session = stripe.checkout.Session.create(
        mode="payment",
        success_url=f"{settings.frontend_url}/dashboard?paid={invoice_number}",
        cancel_url=f"{settings.frontend_url}/dashboard",
        customer_email=customer_email or None,
        line_items=[{
            "price_data": {
                "currency": currency.lower(),
                "product_data": {"name": f"Invoice {invoice_number}"},
                "unit_amount": _to_minor_units(amount),
            },
            "quantity": 1,
        }],
        metadata={"invoice_number": invoice_number},
    )
    return PaymentLink(provider=STRIPE, url=session.url, order_id=session.id)


def verify_razorpay_signature(raw_body: bytes, signature: str | None) -> bool:
    secret = settings.razorpay_webhook_secret
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def parse_razorpay_event(raw_body: bytes) -> dict:
    """Return {event, order_id, payment_id} for a Razorpay webhook payload."""
    data = json.loads(raw_body.decode() or "{}")
    event = data.get("event", "")
    entity = (
        data.get("payload", {})
        .get("payment_link", {})
        .get("entity", {})
    ) or (
        data.get("payload", {})
        .get("payment", {})
        .get("entity", {})
    )
    return {
        "event": event,
        "order_id": entity.get("id") or entity.get("payment_link_id"),
        "payment_id": entity.get("payment_id") or entity.get("id"),
        "paid": event in {"payment_link.paid", "payment.captured", "order.paid"},
    }


def verify_stripe_event(raw_body: bytes, signature: str | None) -> dict:
    """Verify and parse a Stripe webhook. Returns {paid, order_id, payment_id}."""
    try:
        import stripe
    except ImportError as exc:  # pragma: no cover
        raise PaymentError("stripe package not installed") from exc

    secret = settings.stripe_webhook_secret
    if not secret or not signature:
        raise PaymentError("Stripe webhook secret/signature missing")

    event = stripe.Webhook.construct_event(raw_body, signature, secret)
    obj = event["data"]["object"]
    return {
        "event": event["type"],
        "order_id": obj.get("id"),
        "payment_id": obj.get("payment_intent") or obj.get("id"),
        "paid": event["type"] in {"checkout.session.completed", "payment_intent.succeeded"},
    }

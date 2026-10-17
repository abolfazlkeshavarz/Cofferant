"""Zarinpal (v4) online payment. Amounts in the app are Toman; the gateway wants Rial."""
import json
import logging
import urllib.error
import urllib.request

log = logging.getLogger("cofferant")

LIVE = "https://payment.zarinpal.com"
SANDBOX = "https://sandbox.zarinpal.com"


class PaymentError(Exception):
    pass


def _base(venue):
    return SANDBOX if venue.zarinpal_sandbox else LIVE


def _post(url, payload):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "cofferant/1"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:  # gateway answers errors with a JSON body too
        try:
            return json.loads(exc.read().decode())
        except Exception:
            raise PaymentError("پاسخ نامعتبر از درگاه پرداخت.")
    except (urllib.error.URLError, OSError, ValueError):
        raise PaymentError("ارتباط با درگاه پرداخت برقرار نشد.")


def start(venue, order, callback_url):
    """Ask the gateway for a payment session; returns (authority, redirect_url)."""
    body = _post(f"{_base(venue)}/pg/v4/payment/request.json", {
        "merchant_id": venue.zarinpal_merchant_id,
        "amount": order.total_cents * 10,
        "callback_url": callback_url,
        "description": f"سفارش #{order.id} - {venue.name}",
        "metadata": {"mobile": order.customer_phone} if order.customer_phone else {},
    })
    data = body.get("data") or {}
    if data.get("code") != 100 or not data.get("authority"):
        log.warning("zarinpal request refused: %s", body.get("errors"))
        raise PaymentError("درگاه پرداخت درخواست را نپذیرفت.")
    authority = data["authority"]
    return authority, f"{_base(venue)}/pg/StartPay/{authority}"


def verify(venue, order, authority):
    """True when the gateway confirms the payment (code 100 = verified, 101 = already verified)."""
    body = _post(f"{_base(venue)}/pg/v4/payment/verify.json", {
        "merchant_id": venue.zarinpal_merchant_id,
        "amount": order.total_cents * 10,
        "authority": authority,
    })
    data = body.get("data") or {}
    if data.get("code") in (100, 101):
        return str(data.get("ref_id", ""))
    return None

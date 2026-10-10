import requests
from config import ZARINPAL_MERCHANT_ID, ZARINPAL_CALLBACK_URL, STAR_TO_RIAL

def zarinpal_request(amount_rial, description):
    if not ZARINPAL_MERCHANT_ID or not ZARINPAL_CALLBACK_URL:
        raise RuntimeError("Zarinpal is not configured")
    url = "https://payment.zarinpal.com/pg/v4/payment/request.json"
    payload = {
        "merchant_id": ZARINPAL_MERCHANT_ID,
        "amount": int(amount_rial),
        "description": description,
        "callback_url": ZARINPAL_CALLBACK_URL,
    }
    r = requests.post(url, json=payload, timeout=20)
    r.raise_for_status()
    data = r.json()["data"]
    return data["authority"]

def zarinpal_url(authority):
    return f"https://www.zarinpal.com/pg/StartPay/{authority}"

def stars_amount(rial):
    return max(1, round(rial / STAR_TO_RIAL))

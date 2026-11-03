from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from bot import bot, start as start_handler
from config import WEBHOOK_SECRET, ADMIN_PASSWORD
import config as _cfg
from services import stats, is_admin
from db import table
import os
import json
import hmac
import traceback
import time
import requests
from collections import deque
from threading import Lock, Thread

# -----------------------------------------------------------------------------
# BASE_URL fallback: if the operator forgot to set BASE_URL on Render, use the
# auto-injected RENDER_EXTERNAL_URL so webhook + keep-alive can work anyway.
# -----------------------------------------------------------------------------
BASE_URL = (_cfg.BASE_URL or os.getenv("RENDER_EXTERNAL_URL", "")).rstrip("/")

app = Flask(__name__)
SESSION_SECRET = os.getenv("SESSION_SECRET", "").strip()
app.secret_key = SESSION_SECRET or None
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=True,
)

SEEN_UPDATES = deque()
SEEN_UPDATE_IDS = set()
SEEN_LOCK = Lock()

AUTO_SET_WEBHOOK = os.getenv("AUTO_SET_WEBHOOK", "1").strip().lower() not in ("0", "false", "no", "off")
KEEPALIVE_ENABLED = os.getenv("KEEPALIVE", "1").strip().lower() not in ("0", "false", "no", "off")

# Explicitly set the update types this bot actually handles. Telegram preserves
# the previous allowed_updates filter when this argument is omitted; an old
# filter can silently prevent /start messages from reaching this webhook.
WEBHOOK_ALLOWED_UPDATES = ["message", "callback_query", "pre_checkout_query"]
try:
    KEEPALIVE_SECONDS = max(300, min(840, int(os.getenv("KEEPALIVE_SECONDS", "540"))))
except ValueError:
    KEEPALIVE_SECONDS = 540


def _remember_update(update_id):
    if update_id is None:
        return True
    with SEEN_LOCK:
        if update_id in SEEN_UPDATE_IDS:
            return False
        SEEN_UPDATE_IDS.add(update_id)
        SEEN_UPDATES.append(update_id)
        if len(SEEN_UPDATES) > 2000:
            expired = SEEN_UPDATES.popleft()
            SEEN_UPDATE_IDS.discard(expired)
        return True


def _forget_update(update_id):
    if update_id is None:
        return
    with SEEN_LOCK:
        SEEN_UPDATE_IDS.discard(update_id)
        try:
            SEEN_UPDATES.remove(update_id)
        except ValueError:
            pass


def ensure_webhook():
    if not AUTO_SET_WEBHOOK:
        print("Webhook skipped: AUTO_SET_WEBHOOK is disabled", flush=True)
        return False
    if not BASE_URL:
        print("Webhook skipped: BASE_URL is empty AND RENDER_EXTERNAL_URL not set", flush=True)
        return False
    if not WEBHOOK_SECRET or WEBHOOK_SECRET == "change_me":
        print("Webhook skipped: WEBHOOK_SECRET is missing or still the default", flush=True)
        return False
    try:
        url = f"{BASE_URL}/telegram-webhook"
        result = bot.set_webhook(
            url=url,
            secret_token=WEBHOOK_SECRET,
            allowed_updates=WEBHOOK_ALLOWED_UPDATES,
            max_connections=40,
            drop_pending_updates=False,
        )
        info = bot.get_webhook_info()
        current_url = (getattr(info, "url", "") or "").rstrip("/")
        matches = current_url == url.rstrip("/")
        print(
            "Webhook registration: "
            f"set_result={result} url_matches={matches} "
            f"current_url={current_url or '(empty)'} "
            f"pending={getattr(info, 'pending_update_count', 'unknown')} "
            f"allowed_updates={WEBHOOK_ALLOWED_UPDATES}",
            flush=True,
        )
        return bool(result and matches)
    except Exception:
        traceback.print_exc()
        print("Webhook setup failed; background retry will continue", flush=True)
        return False


def _webhook_retry_loop():
    delay = 5
    while True:
        time.sleep(delay)
        if ensure_webhook():
            print("Webhook registration retry succeeded", flush=True)
            return
        delay = min(delay * 2, 120)


def _bootstrap_webhook():
    """First webhook attempt in a background thread so Gunicorn's /health is
    reachable immediately at cold start."""
    try:
        if ensure_webhook():
            print("Webhook registered at startup", flush=True)
            return
    except Exception:
        traceback.print_exc()
    print("Webhook bootstrap failed; starting retry loop", flush=True)
    _webhook_retry_loop()


def _keepalive_loop():
    """Self-ping /health every ~9 min so Render Free's 15-min idle timer never fires."""
    print(f"Keep-alive loop started (interval={KEEPALIVE_SECONDS}s, target={BASE_URL}/health)", flush=True)
    while True:
        time.sleep(KEEPALIVE_SECONDS)
        try:
            response = requests.get(f"{BASE_URL}/health", timeout=(3, 8))
            if response.status_code == 200:
                print(f"Keep-alive OK ({response.status_code})", flush=True)
            else:
                print(f"Keep-alive returned HTTP {response.status_code}", flush=True)
        except Exception as e:
            print(f"Keep-alive request failed: {e}", flush=True)


def start_background_tasks():
    if KEEPALIVE_ENABLED and BASE_URL:
        Thread(target=_keepalive_loop, name="render-keepalive", daemon=True).start()
    elif KEEPALIVE_ENABLED and not BASE_URL:
        print("Keep-alive disabled: BASE_URL and RENDER_EXTERNAL_URL both empty", flush=True)
    if AUTO_SET_WEBHOOK and BASE_URL:
        Thread(target=_bootstrap_webhook, name="webhook-bootstrap", daemon=True).start()


# ====================== DIAGNOSTIC ENDPOINTS ======================

@app.get("/")
def home():
    return jsonify({"status": "ok", "service": "telegram-shop-bot", "base_url": BASE_URL or None})


@app.get("/health")
def health():
    return "OK", 200


@app.get("/diag")
def diag():
    """Read-only diagnostic: shows what env vars are loaded and Telegram's view of our webhook."""
    wh_info = None
    bot_info = None
    try:
        me = bot.get_me()
        bot_info = {
            "id": getattr(me, "id", None),
            "username": getattr(me, "username", None),
            "first_name": getattr(me, "first_name", None),
        }
    except Exception as e:
        bot_info = {"error_type": type(e).__name__}
    try:
        info = bot.get_webhook_info()
        actual_url = (getattr(info, "url", "") or "").rstrip("/")
        expected_url = f"{BASE_URL}/telegram-webhook".rstrip("/") if BASE_URL else ""
        last_error_date = getattr(info, "last_error_date", None)
        if hasattr(last_error_date, "isoformat"):
            last_error_date = last_error_date.isoformat()
        wh_info = {
            "url": actual_url,
            "url_matches_expected": bool(actual_url and actual_url == expected_url),
            "pending_updates": info.pending_update_count,
            "last_error": info.last_error_message,
            "last_error_date": last_error_date,
        }
    except Exception as e:
        wh_info = {"error_type": type(e).__name__}
    return jsonify({
        "base_url": BASE_URL,
        "bot": bot_info,
        "auto_webhook": AUTO_SET_WEBHOOK,
        "keepalive": KEEPALIVE_ENABLED,
        "keepalive_seconds": KEEPALIVE_SECONDS,
        "secret_present": bool(WEBHOOK_SECRET),
        "secret_is_default": WEBHOOK_SECRET == "change_me",
        "secret_len": len(WEBHOOK_SECRET or ""),
        "allowed_updates_configured": WEBHOOK_ALLOWED_UPDATES,
        "telegram_webhook_info": wh_info,
        "expected_webhook_url": f"{BASE_URL}/telegram-webhook" if BASE_URL else None,
    })

@app.post("/test-send")
def test_send():
    """Send a test message directly to a chat_id (bypasses webhook).
    Use this to check whether bot.send_message works at all."""
    chat_id = request.args.get("chat_id", "").strip()
    if not chat_id:
        return jsonify({"error": "chat_id query param required"}), 400
    try:
        result = bot.send_message(int(chat_id), "🧪 Test message from server (bypassing webhook)")
        return jsonify({
            "ok": bool(result),
            "message_id": getattr(result, "message_id", None),
            "chat_id": int(chat_id),
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({
            "error": str(e),
            "type": type(e).__name__,
        }), 500
        
@app.post("/force-set-webhook")
def force_set_webhook():
    """Manually register the webhook with Telegram. Use this if the auto-bootstrap
    didn't fire (e.g. WEBHOOK_SECRET was added AFTER the service booted)."""
    if not BASE_URL:
        return jsonify({"error": "BASE_URL missing", "hint": "set BASE_URL env var or use RENDER_EXTERNAL_URL"}), 400
    if not WEBHOOK_SECRET or WEBHOOK_SECRET == "change_me":
        return jsonify({
            "error": "WEBHOOK_SECRET not set properly",
            "secret_present": bool(WEBHOOK_SECRET),
            "secret_is_default": WEBHOOK_SECRET == "change_me",
            "secret_len": len(WEBHOOK_SECRET or ""),
            "hint": "Set WEBHOOK_SECRET to a random 32+ character string in Render Environment, then redeploy.",
        }), 400
    url = f"{BASE_URL}/telegram-webhook"
    try:
        result = bot.set_webhook(
            url=url,
            secret_token=WEBHOOK_SECRET,
            allowed_updates=WEBHOOK_ALLOWED_UPDATES,
            max_connections=40,
            drop_pending_updates=False,
        )
        info = bot.get_webhook_info()
        current_url = (getattr(info, "url", "") or "").rstrip("/")
        return jsonify({
            "set_result": result,
            "requested_url": url,
            "current_url": current_url,
            "url_matches": current_url == url.rstrip("/"),
            "allowed_updates": WEBHOOK_ALLOWED_UPDATES,
            "pending": info.pending_update_count,
            "last_error": info.last_error_message,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e), "hint": "check BOT_TOKEN, network, and Telegram API access"}), 500


@app.post("/force-delete-webhook")
def force_delete_webhook():
    """Delete the webhook (useful for debugging: then re-run force-set-webhook)."""
    try:
        result = bot.delete_webhook(drop_pending_updates=False)
        return jsonify({"delete_result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ====================== TELEGRAM WEBHOOK ENDPOINT ======================

@app.post("/telegram-webhook")
def telegram_webhook():
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if not WEBHOOK_SECRET or WEBHOOK_SECRET == "change_me" or not hmac.compare_digest(secret or "", WEBHOOK_SECRET):
        print(f"webhook forbidden: secret header mismatch (got_len={len(secret or '')}, expected_len={len(WEBHOOK_SECRET or '')})", flush=True)
        return "forbidden", 403
    update = request.get_json(force=True, silent=True)
    if not update:
        return "OK", 200
    if not isinstance(update, dict):
        print("webhook received a non-object JSON payload", flush=True)
        return "bad update payload", 400
    uid = update.get("update_id")
    update_kinds = [k for k in ("message", "callback_query", "pre_checkout_query", "edited_message") if k in update]
    print(f"Webhook received update_id={uid} types={update_kinds or ['unknown']}", flush=True)
    if not _remember_update(uid):
        print(f"Webhook duplicate ignored update_id={uid}", flush=True)
        return "OK", 200
    try:
        from telebot.types import Update
        # Decode using the library's JSON-string deserializer.
        update_obj = Update.de_json(json.dumps(update, ensure_ascii=False))

        # Dispatch /start directly in the request thread. This guarantees that the
        # onboarding handler actually runs before acknowledging the update, and makes
        # any DB/Telegram API failure visible in Render logs. Other updates continue
        # through TeleBot's normal threaded dispatcher for throughput.
        message = getattr(update_obj, "message", None)
        message_text = (getattr(message, "text", None) or "").strip()
        first_token = message_text.split(maxsplit=1)[0] if message_text else ""
        command = first_token.split("@", 1)[0].lower()
        if message is not None and command == "/start":
            print(
                f"[WEBHOOK] direct /start dispatch chat_id={getattr(getattr(message, 'chat', None), 'id', None)} "
                f"user_id={getattr(getattr(message, 'from_user', None), 'id', None)}",
                flush=True,
            )
            start_handler(message)
            print(f"[WEBHOOK] /start handler completed update_id={uid}", flush=True)
        else:
            bot.process_new_updates([update_obj])
            print(f"[WEBHOOK] update queued to bot handlers update_id={uid}", flush=True)
    except Exception:
        _forget_update(uid)
        print(f"[WEBHOOK] dispatch failed update_id={uid}", flush=True)
        traceback.print_exc()
        return "temporary processing failure", 500
    return "OK", 200


# ====================== ADMIN PANEL ======================

@app.get("/admin")
def admin():
    if not SESSION_SECRET:
        return "SESSION_SECRET is not configured", 503
    if not session.get("admin"):
        return redirect(url_for("login"))
    return render_template("admin.html", stats=stats())


@app.route("/admin/login", methods=["GET", "POST"])
def login():
    if not SESSION_SECRET:
        return "SESSION_SECRET is not configured", 503
    if request.method == "POST":
        submitted = request.form.get("password", "")
        if ADMIN_PASSWORD and ADMIN_PASSWORD.strip() and hmac.compare_digest(submitted, ADMIN_PASSWORD):
            session.clear()
            session["admin"] = True
            return redirect(url_for("admin"))
        return render_template("login.html", error="Admin login is not configured or the password is incorrect")
    return render_template("login.html", error=None)


@app.post("/admin/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/admin/stats/daily")
def admin_daily_stats():
    if not session.get("admin"):
        return jsonify({"error": "unauthorized"}), 401
    rows = table("orders").select("created_at,total,payment_status,currency,payment_method").eq("payment_status", "paid").execute().data
    daily = {}
    for x in rows:
        if x.get("currency") == "CUSTOM" or x.get("payment_method") == "custom":
            continue
        day = x["created_at"][:10]
        cur = x.get("currency") or "IRT"
        key = f"{day}:{cur}"
        daily[key] = daily.get(key, 0) + float(x.get("total") or 0)
    return jsonify(sorted([{"date": k.rsplit(":", 1)[0], "currency": k.rsplit(":", 1)[1], "revenue": v} for k, v in daily.items()], key=lambda x: (x["date"], x["currency"])))


@app.get("/admin/products")
def admin_products():
    if not session.get("admin"):
        return jsonify({"error": "unauthorized"}), 401
    return jsonify(table("products").select("*").order("created_at", desc=True).execute().data)


@app.post("/admin/products")
def admin_create_product():
    if not session.get("admin"):
        return jsonify({"error": "unauthorized"}), 401
    payload = request.get_json(force=True)
    allowed = ["category_id", "name_fa", "name_en", "description_fa", "description_en", "image_url", "price", "stock", "digital_content", "active", "product_type", "pay_method", "stars_price"]
    payload = {k: payload[k] for k in allowed if k in payload}
    return jsonify(table("products").insert(payload).execute().data)


@app.get("/admin/orders")
def admin_orders():
    if not session.get("admin"):
        return jsonify({"error": "unauthorized"}), 401
    return jsonify(table("orders").select("*").order("created_at", desc=True).limit(100).execute().data)


start_background_tasks()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)

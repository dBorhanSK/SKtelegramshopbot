from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from bot import bot
from config import BASE_URL, WEBHOOK_SECRET, ADMIN_PASSWORD
from services import stats, is_admin
from db import table
import os
import hmac
import traceback
from collections import deque
from threading import Lock

app = Flask(__name__)
# Use a dedicated secret for Flask sessions when available. Never fall back to a public default.
SESSION_SECRET = os.getenv("SESSION_SECRET", "").strip()
# Never derive the session-signing key from other credentials.
app.secret_key = SESSION_SECRET or None
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=True,
)

SEEN_UPDATES = deque(maxlen=2000)   # process-local duplicate optimization
SEEN_LOCK = Lock()

def ensure_webhook():
    if not BASE_URL:
        print("Webhook skipped: BASE_URL is empty")
        return
    try:
        url = f"{BASE_URL}/telegram-webhook"
        result = bot.set_webhook(url=url, secret_token=WEBHOOK_SECRET)
        print("Webhook set:", url, result)
    except Exception as e:
        print("Webhook setup:", e)

@app.get("/")
def home():
    return jsonify({"status":"ok","service":"telegram-shop-bot"})

@app.get("/health")
def health():
    return "OK", 200

@app.post("/telegram-webhook")
def telegram_webhook():
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    # The secret header is REQUIRED (the old check let requests without the header through,
    # which would allow forged "successful_payment" updates).
    if not WEBHOOK_SECRET or WEBHOOK_SECRET == "change_me" or not hmac.compare_digest(secret or "", WEBHOOK_SECRET):
        print("webhook forbidden: secret mismatch")
        return "forbidden", 403
    update = request.get_json(force=True, silent=True)
    if not update:
        print("webhook: empty body")
        return "OK", 200
    uid = update.get("update_id")
    # Mark only after successful dispatch so transient exceptions are retryable.
    with SEEN_LOCK:
        if uid is not None and uid in SEEN_UPDATES:
            return "OK", 200
    try:
        from telebot.types import Update
        bot.process_new_updates([Update.de_json(update)])
    except Exception:
        traceback.print_exc()
        return "temporary processing failure", 500
    with SEEN_LOCK:
        if uid is not None:
            SEEN_UPDATES.append(uid)
    return "OK", 200

@app.get("/admin")
def admin():
    if not SESSION_SECRET:
        return "SESSION_SECRET is not configured", 503
    if not session.get("admin"):
        return redirect(url_for("login"))
    return render_template("admin.html", stats=stats())


@app.route("/admin/login", methods=["GET","POST"])
def login():
    if not SESSION_SECRET:
        return "SESSION_SECRET is not configured", 503
    if request.method=="POST":
        # Fail closed if Render's ADMIN_PASSWORD was removed/misspelled; blank must never log in.
        submitted = request.form.get("password", "")
        if ADMIN_PASSWORD and ADMIN_PASSWORD.strip() and hmac.compare_digest(submitted, ADMIN_PASSWORD):
            session.clear()  # rotate the session contents after authentication
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
        return jsonify({"error":"unauthorized"}),401
    rows=table("orders").select("created_at,total,payment_status,currency,payment_method").eq("payment_status","paid").execute().data
    daily={}
    for x in rows:
        if x.get("currency") == "CUSTOM" or x.get("payment_method") == "custom":
            continue
        day=x["created_at"][:10]
        cur=x.get("currency") or "IRT"
        key=f"{day}:{cur}"
        daily[key]=daily.get(key,0)+float(x.get("total") or 0)
    return jsonify(sorted([{"date":k.rsplit(":",1)[0],"currency":k.rsplit(":",1)[1],"revenue":v} for k,v in daily.items()], key=lambda x:(x["date"],x["currency"])))

@app.get("/admin/products")
def admin_products():
    if not session.get("admin"):
        return jsonify({"error":"unauthorized"}),401
    return jsonify(table("products").select("*").order("created_at",desc=True).execute().data)

@app.post("/admin/products")
def admin_create_product():
    if not session.get("admin"):
        return jsonify({"error":"unauthorized"}),401
    payload=request.get_json(force=True)
    allowed=["category_id","name_fa","name_en","description_fa","description_en","image_url","price","stock","digital_content","active","product_type","pay_method","stars_price"]
    payload={k:payload[k] for k in allowed if k in payload}
    return jsonify(table("products").insert(payload).execute().data)

@app.get("/admin/orders")
def admin_orders():
    if not session.get("admin"):
        return jsonify({"error":"unauthorized"}),401
    return jsonify(table("orders").select("*").order("created_at",desc=True).limit(100).execute().data)

@app.post("/set-webhook")
def set_webhook():
    supplied = request.args.get("secret", "")
    if not WEBHOOK_SECRET or WEBHOOK_SECRET == "change_me" or not hmac.compare_digest(supplied, WEBHOOK_SECRET):
        return "forbidden",403
    if not BASE_URL:
        return "BASE_URL missing",400
    url=f"{BASE_URL}/telegram-webhook"
    result=bot.set_webhook(url=url, secret_token=WEBHOOK_SECRET)
    return jsonify({"webhook":url,"result":result})

ensure_webhook()

if __name__=="__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)

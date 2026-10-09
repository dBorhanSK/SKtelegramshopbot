from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from bot import bot
from config import BASE_URL, WEBHOOK_SECRET, ADMIN_PASSWORD
from services import stats, is_admin
from db import table
import os
import traceback

app = Flask(__name__)
app.secret_key = WEBHOOK_SECRET or "dev-secret"

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
    if WEBHOOK_SECRET and secret and secret != WEBHOOK_SECRET:
        print("webhook forbidden: secret mismatch")
        return "forbidden", 403
    update = request.get_json(force=True, silent=True)
    if not update:
        print("webhook: empty body")
        return "OK", 200
    try:
        from telebot.types import Update
        print("webhook update:", update.get("update_id"), list(update.keys()))
        bot.process_new_updates([Update.de_json(update)])
    except Exception:
        traceback.print_exc()
    return "OK", 200

@app.get("/admin")
def admin():
    if not session.get("admin"):
        return redirect(url_for("login"))
    return render_template("admin.html", stats=stats())

@app.route("/admin/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        if request.form.get("password")==ADMIN_PASSWORD:
            session["admin"]=True
            return redirect(url_for("admin"))
        return render_template("login.html", error="Wrong password")
    return render_template("login.html", error=None)

@app.post("/admin/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.get("/admin/stats/daily")
def admin_daily_stats():
    if not session.get("admin"):
        return jsonify({"error":"unauthorized"}),401
    rows=table("orders").select("created_at,total,payment_status").eq("payment_status","paid").execute().data
    daily={}
    for x in rows:
        day=x["created_at"][:10]
        daily[day]=daily.get(day,0)+float(x["total"])
    return jsonify(sorted([{"date":k,"revenue":v} for k,v in daily.items()], key=lambda x:x["date"]))

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
    allowed=["category_id","name_fa","name_en","description_fa","description_en","image_url","price","stock","digital_content","active"]
    payload={k:payload[k] for k in allowed if k in payload}
    return jsonify(table("products").insert(payload).execute().data)

@app.get("/admin/orders")
def admin_orders():
    if not session.get("admin"):
        return jsonify({"error":"unauthorized"}),401
    return jsonify(table("orders").select("*").order("created_at",desc=True).limit(100).execute().data)

@app.post("/set-webhook")
def set_webhook():
    if request.args.get("secret") != WEBHOOK_SECRET:
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

import telebot
from telebot import types
from config import *
from i18n import t
from services import *
from payments import stars_amount
from db import table, one

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

def kb_main(lang):
    k = types.InlineKeyboardMarkup()
    k.row(types.InlineKeyboardButton(t(lang,"shop"), callback_data="shop"))
    k.row(
        types.InlineKeyboardButton(t(lang,"cart"), callback_data="cart"),
        types.InlineKeyboardButton(t(lang,"orders"), callback_data="orders")
    )
    k.row(
        types.InlineKeyboardButton(t(lang,"wallet"), callback_data="wallet"),
        types.InlineKeyboardButton(t(lang,"support"), callback_data="support")
    )
    k.row(types.InlineKeyboardButton(t(lang,"language"), callback_data="language"))
    return k

def send_home(chat_id, lang):
    bot.send_message(chat_id, t(lang,"welcome") + "\n\n" + t(lang,"choose"), reply_markup=kb_main(lang))

def channel_required(user_id):
    if not REQUIRED_CHANNEL_ID:
        return False
    try:
        m = bot.get_chat_member(REQUIRED_CHANNEL_ID, user_id)
        return m.status in ("member", "administrator", "creator")
    except Exception:
        return True

@bot.message_handler(commands=["start"])
def start(m):
    u = get_user(m.from_user)
    lang = u.get("language","fa")
    if not channel_required(m.from_user.id):
        k = types.InlineKeyboardMarkup()
        if REQUIRED_CHANNEL_USERNAME:
            k.add(types.InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{REQUIRED_CHANNEL_USERNAME}"))
        k.add(types.InlineKeyboardButton(t(lang,"joined"), callback_data="check_join"))
        bot.send_message(m.chat.id, t(lang,"join_first"), reply_markup=k)
        return
    send_home(m.chat.id, lang)

@bot.callback_query_handler(func=lambda c: True)
def callback(c):
    u = get_user(c.from_user)
    lang = u.get("language","fa")
    data = c.data
    bot.answer_callback_query(c.id)

    if data == "check_join":
        if channel_required(c.from_user.id):
            bot.delete_message(c.message.chat.id, c.message.message_id)
            send_home(c.message.chat.id, lang)
        else:
            bot.answer_callback_query(c.id, t(lang,"join_first"), show_alert=True)
        return

    if data == "language":
        k = types.InlineKeyboardMarkup()
        k.row(types.InlineKeyboardButton("🇮🇷 فارسی", callback_data="lang_fa"),
              types.InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"))
        bot.edit_message_text("Language / زبان", c.message.chat.id, c.message.message_id, reply_markup=k)
        return

    if data.startswith("lang_"):
        new = data[-2:]
        set_language(u["id"], new)
        send_home(c.message.chat.id, new)
        return

    if data == "shop":
        show_categories(c.message.chat.id, lang)
    elif data.startswith("cat:"):
        show_products(c.message.chat.id, lang, data.split(":")[1])
    elif data.startswith("product:"):
        show_product(c.message.chat.id, lang, data.split(":")[1])
    elif data.startswith("add:"):
        add_cart(u["id"], data.split(":")[1])
        bot.answer_callback_query(c.id, t(lang,"added"))
    elif data == "cart":
        show_cart(c.message.chat.id, u, lang)
    elif data.startswith("remove:"):
        remove_cart(u["id"], data.split(":")[1])
        show_cart(c.message.chat.id, u, lang)
    elif data == "checkout":
        checkout_menu(c.message.chat.id, u, lang)
    elif data.startswith("pay:"):
        create_and_pay(c.message.chat.id, u, lang, data.split(":")[1])
    elif data == "orders":
        show_orders(c.message.chat.id, u, lang)
    elif data == "wallet":
        bot.send_message(c.message.chat.id, f"💰 {u.get('wallet_balance',0)}")
    elif data == "support":
        bot.send_message(c.message.chat.id, t(lang,"ticket"))
        bot.register_next_step_handler_by_chat_id(c.message.chat.id, create_ticket)
    elif data == "admin":
        if is_admin(c.from_user.id):
            admin_menu(c.message.chat.id, lang)
        else:
            bot.send_message(c.message.chat.id, t(lang,"admin_only"))

def show_categories(chat_id, lang):
    cats = categories()
    k = types.InlineKeyboardMarkup()
    for x in cats:
        name = x["name_fa"] if lang=="fa" else x["name_en"]
        k.add(types.InlineKeyboardButton(name, callback_data=f"cat:{x['id']}"))
    k.add(types.InlineKeyboardButton(t(lang,"back"), callback_data="home"))
    bot.send_message(chat_id, "🗂", reply_markup=k)

def show_products(chat_id, lang, cat_id):
    ps = products(cat_id)
    k = types.InlineKeyboardMarkup()
    for p in ps:
        name = p["name_fa"] if lang=="fa" else p["name_en"]
        k.add(types.InlineKeyboardButton(f"{name} — {p['price']}", callback_data=f"product:{p['id']}"))
    bot.send_message(chat_id, "📦", reply_markup=k)

def show_product(chat_id, lang, pid):
    p = product(pid)
    if not p:
        bot.send_message(chat_id, t(lang,"not_found")); return
    name = p["name_fa"] if lang=="fa" else p["name_en"]
    desc = p["description_fa"] if lang=="fa" else p["description_en"]
    text = f"<b>{name}</b>\n\n{desc}\n\n💵 {p['price']}\n📦 {p['stock']}"
    k = types.InlineKeyboardMarkup()
    k.add(types.InlineKeyboardButton("🛒 " + t(lang,"cart"), callback_data=f"add:{pid}"))
    if p.get("image_url"):
        bot.send_photo(chat_id, p["image_url"], caption=text, reply_markup=k)
    else:
        bot.send_message(chat_id, text, reply_markup=k)

def show_cart(chat_id, user, lang):
    items = cart(user["id"])
    if not items:
        bot.send_message(chat_id, t(lang,"empty_cart")); return
    total = sum(float(x["products"]["price"])*x["quantity"] for x in items)
    k = types.InlineKeyboardMarkup()
    for x in items:
        p=x["products"]
        name=p["name_fa"] if lang=="fa" else p["name_en"]
        k.add(types.InlineKeyboardButton(f"❌ {name} × {x['quantity']}", callback_data=f"remove:{x['id']}"))
    k.add(types.InlineKeyboardButton(t(lang,"checkout"), callback_data="checkout"))
    bot.send_message(chat_id, f"🛒\n💵 {total}", reply_markup=k)

def checkout_menu(chat_id, user, lang):
    k=types.InlineKeyboardMarkup()
    k.add(types.InlineKeyboardButton(t(lang,"stars"), callback_data="pay:stars"))
    k.add(types.InlineKeyboardButton(t(lang,"card"), callback_data="pay:card"))
    k.add(types.InlineKeyboardButton(t(lang,"online"), callback_data="pay:zarinpal"))
    bot.send_message(chat_id, t(lang,"payment"), reply_markup=k)

def create_and_pay(chat_id, user, lang, method):
    order=create_order(user, method)
    if not order:
        bot.send_message(chat_id,t(lang,"empty_cart")); return
    total=float(order["total"])
    if method=="stars":
        prices=[types.LabeledPrice(label="Order", amount=stars_amount(total))]
        bot.send_invoice(chat_id, "Shop Order", "Telegram Shop Order", f"order:{order['id']}", "", "XTR", prices)
    elif method=="card":
        bot.send_message(chat_id, f"💳 {CARD_NUMBER}\n👤 {CARD_HOLDER}\n\nOrder ID: {order['id']}\nAmount: {total}\nپس از پرداخت، رسید را ارسال کنید.")
        bot.register_next_step_handler_by_chat_id(chat_id, lambda m: submit_receipt(m, order["id"]))
    else:
        bot.send_message(chat_id, "Zarinpal payment requires the configured gateway.")

def submit_receipt(m, order_id):
    text = m.text or m.caption or ""
    if m.content_type == "photo":
        file_id = m.photo[-1].file_id
        text = f"PHOTO:{file_id}\n{text}"
    table("payment_receipts").insert({"order_id":order_id,"telegram_id":m.from_user.id,"text":text}).execute()
    k=types.InlineKeyboardMarkup()
    k.add(types.InlineKeyboardButton("✅ Approve", callback_data=f"approve:{order_id}"))
    k.add(types.InlineKeyboardButton("📦 Mark shipped", callback_data=f"ship:{order_id}"))
    for admin in ADMIN_IDS:
        try:
            bot.send_message(admin, f"💳 Card payment receipt\nOrder: {order_id}\n{text}", reply_markup=k)
        except Exception:
            pass
    bot.send_message(m.chat.id, "✅ Receipt submitted. Waiting for admin confirmation.")

@bot.pre_checkout_query_handler(func=lambda q: True)
def precheckout(q):
    bot.answer_pre_checkout_query(q.id, ok=True)

@bot.message_handler(content_types=["successful_payment"])
def successful_payment(m):
    payload=m.successful_payment.invoice_payload
    order_id=payload.split(":",1)[1]
    mark_paid(order_id, m.successful_payment.telegram_payment_charge_id)
    bot.send_message(m.chat.id, "✅ Payment successful. Your digital product will be delivered automatically.")
    deliver_digital(order_id, m.chat.id)

def deliver_digital(order_id, chat_id):
    rows=table("order_items").select("*").eq("order_id",order_id).execute().data
    for x in rows:
        content=x.get("digital_delivery")
        if content:
            try:
                if str(content).startswith(("http://","https://")):
                    bot.send_document(chat_id, content, caption=x.get("product_name","Digital product"))
                else:
                    bot.send_message(chat_id, f"🔐 {x.get('product_name')}\n\n{content}")
            except Exception as e:
                bot.send_message(chat_id, f"Digital delivery error: {e}")

def show_orders(chat_id,user,lang):
    rows=table("orders").select("*").eq("user_id",user["id"]).order("created_at",desc=True).limit(10).execute().data
    if not rows:
        bot.send_message(chat_id,"No orders."); return
    text="\n".join([f"#{x['id']} — {x['status']} — {x['total']}" for x in rows])
    bot.send_message(chat_id,text)

def create_ticket(m):
    u=get_user(m.from_user)
    row=table("tickets").insert({"user_id":u["id"],"message":m.text or "","status":"open"}).execute().data[0]
    for admin in ADMIN_IDS:
        try: bot.send_message(admin,f"🎫 Ticket #{row['id']}\n@m.from_user.username\n{m.text}")
        except: pass
    bot.send_message(m.chat.id,"✅ Ticket created.")

def admin_menu(chat_id,lang):
    k=types.InlineKeyboardMarkup()
    k.row(types.InlineKeyboardButton("📊 Stats",callback_data="admin_stats"),
          types.InlineKeyboardButton("📦 Orders",callback_data="admin_orders"))
    k.row(types.InlineKeyboardButton("📢 Broadcast",callback_data="admin_broadcast"))
    bot.send_message(chat_id,"⚙️ Admin Panel",reply_markup=k)

@bot.callback_query_handler(func=lambda c: c.data=="admin_stats")
def admin_stats(c):
    if not is_admin(c.from_user.id): return
    s=stats()
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id,f"Orders: {s['orders']}\nRevenue: {s['revenue']}")

@bot.callback_query_handler(func=lambda c: c.data=="admin_orders")
def admin_orders(c):
    if not is_admin(c.from_user.id): return
    rows=table("orders").select("*").order("created_at",desc=True).limit(20).execute().data
    bot.send_message(c.message.chat.id,"\n".join([f"#{x['id']} {x['status']} {x['total']}" for x in rows]) or "No orders")



@bot.callback_query_handler(func=lambda c: c.data.startswith("approve:"))
def approve_order(c):
    if not is_admin(c.from_user.id):
        bot.answer_callback_query(c.id, "Admin only", show_alert=True); return
    order_id=c.data.split(":",1)[1]
    approve_card_payment(order_id)
    rows=table("orders").select("user_id").eq("id",order_id).limit(1).execute().data
    if rows:
        u=table("users").select("telegram_id").eq("id",rows[0]["user_id"]).limit(1).execute().data
        if u:
            bot.send_message(u[0]["telegram_id"], "✅ Payment approved. Your order is confirmed.")
            deliver_digital(order_id, u[0]["telegram_id"])
    bot.answer_callback_query(c.id,"Approved")

@bot.callback_query_handler(func=lambda c: c.data.startswith("ship:"))
def ship_order(c):
    if not is_admin(c.from_user.id): return
    order_id=c.data.split(":",1)[1]
    update_order_status(order_id,"shipped")
    bot.answer_callback_query(c.id,"Order marked as shipped")
    bot.send_message(c.message.chat.id, f"📦 #{order_id} → shipped")

@bot.message_handler(commands=["broadcast"])
def broadcast_command(m):
    if not is_admin(m.from_user.id):
        return
    bot.send_message(m.chat.id, "Send the broadcast text now.")
    bot.register_next_step_handler(m, do_broadcast)

def do_broadcast(m):
    if not is_admin(m.from_user.id):
        return
    users=table("users").select("telegram_id").execute().data
    sent=0
    for u in users:
        try:
            bot.send_message(u["telegram_id"], m.text)
            sent += 1
        except Exception:
            pass
    bot.send_message(m.chat.id, f"Broadcast complete: {sent} users.")

@bot.message_handler(commands=["status"])
def order_status_command(m):
    u=get_user(m.from_user)
    rows=customer_orders(u["id"])
    if not rows:
        bot.send_message(m.chat.id, "No orders yet.")
        return
    lines=[]
    for x in rows[:10]:
        lines.append(f"#{x['id']} — {x['status']} — {x['payment_status']} — {x['total']}")
    bot.send_message(m.chat.id, "\n".join(lines))

@bot.message_handler(commands=["admin"])
def admin_command(m):
    if is_admin(m.from_user.id):
        admin_menu(m.chat.id, get_user(m.from_user).get("language","fa"))
    else:
        bot.send_message(m.chat.id,t("fa","admin_only"))

import telebot
from telebot import types
from config import *
from i18n import t
from services import *
from payments import stars_amount
from db import table, one

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
WAIT = {}
PENDING_SHOP = {}
LAST_SHOP = {}
OWNER_ID = 6914909647

def box(title, body):
    return f"✦ <b>{title}</b>\n━━━━━━━━━━━━\n{body}"

def chat_menu(lang, role):
    k = types.ReplyKeyboardMarkup(resize_keyboard=True, is_persistent=True)
    if role == "owner":
        k.row("👑 پنل مالک", "📊 درآمد")
        k.row("🛍 فروشگاه‌ها", "📣 کانال‌ها")
        k.row("⭐ اشتراک‌ها", "🌐 زبان")
    elif role == "seller":
        k.row("🏪 پنل ادمین", "⭐ اشتراک من")
        k.row("🛍 فروشگاه من", "📦 محصولات")
        k.row("📣 کانال من", "🌐 زبان")
    else:
        k.row("🛍 فروشگاه‌ها", "🛒 سبد خرید")
        k.row("📦 سفارش‌ها", "🎫 پشتیبانی")
        k.row("🌐 زبان", "🔁 تغییر پنل")
    return k

def setup_commands():
    try:
        bot.set_my_commands([
            types.BotCommand("start", "شروع و انتخاب زبان"),
            types.BotCommand("menu", "منوی پنل"),
            types.BotCommand("panel", "تغییر پنل"),
            types.BotCommand("shops", "فروشگاه‌ها"),
            types.BotCommand("support", "پشتیبانی"),
        ])
    except Exception as e:
        print("commands:", e)

def ask_panel(chat_id, lang, tg_id):
    k = types.InlineKeyboardMarkup()
    if int(tg_id) == OWNER_ID or is_owner(tg_id):
        k.add(types.InlineKeyboardButton("👑 پنل مالک", callback_data="panel_owner"))
    k.add(types.InlineKeyboardButton("🏪 پنل ادمین فروشگاه", callback_data="panel_admin"))
    k.add(types.InlineKeyboardButton("🛍 پنل مشتری", callback_data="panel_customer"))
    bot.send_message(chat_id, box(t(lang, "choose"), "پنل خود را انتخاب کنید.\nChoose your panel."), reply_markup=k)

def lang_of(user):
    return user.get("language") or "fa"

def ask_language(chat_id):
    k = types.InlineKeyboardMarkup()
    k.row(
        types.InlineKeyboardButton("🇮🇷 فارسی", callback_data="lang_fa"),
        types.InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
    )
    bot.send_message(chat_id, t("fa", "pick_lang") + "\n" + t("en", "pick_lang"), reply_markup=k)

def role_of(user, tg_id):
    if is_owner(tg_id):
        return "owner"
    if is_seller(user):
        return "seller"
    return "customer"

def kb_owner(lang):
    k = types.InlineKeyboardMarkup()
    k.row(types.InlineKeyboardButton(t(lang, "admins"), callback_data="own:admins"))
    k.row(types.InlineKeyboardButton(t(lang, "revenue"), callback_data="own:revenue"),
          types.InlineKeyboardButton(t(lang, "admin_stats"), callback_data="own:stats"))
    k.row(types.InlineKeyboardButton(t(lang, "shops"), callback_data="own:shops"),
          types.InlineKeyboardButton(t(lang, "channels"), callback_data="own:channels"))
    k.row(types.InlineKeyboardButton(t(lang, "plans"), callback_data="own:plans"))
    k.row(types.InlineKeyboardButton(t(lang, "my_support"), callback_data="own:support"))
    k.row(types.InlineKeyboardButton(t(lang, "language"), callback_data="language"))
    return k

def kb_seller(lang):
    k = types.InlineKeyboardMarkup()
    k.row(types.InlineKeyboardButton(t(lang, "my_shop"), callback_data="sel:shop"))
    k.row(types.InlineKeyboardButton(t(lang, "my_products"), callback_data="sel:products"))
    k.row(types.InlineKeyboardButton(t(lang, "my_sub"), callback_data="sel:sub"))
    k.row(types.InlineKeyboardButton(t(lang, "my_channel"), callback_data="sel:channel"))
    k.row(types.InlineKeyboardButton(t(lang, "my_support"), callback_data="sel:support"))
    k.row(types.InlineKeyboardButton(t(lang, "language"), callback_data="language"))
    return k

def kb_customer(lang):
    k = types.InlineKeyboardMarkup()
    k.row(types.InlineKeyboardButton(t(lang, "shop"), callback_data="cus:shops"))
    k.row(types.InlineKeyboardButton(t(lang, "cart"), callback_data="cart"),
          types.InlineKeyboardButton(t(lang, "orders"), callback_data="orders"))
    k.row(types.InlineKeyboardButton(t(lang, "support"), callback_data="cus:support"))
    k.row(types.InlineKeyboardButton(t(lang, "language"), callback_data="language"))
    return k

def send_home(chat_id, user, tg_id):
    lang = lang_of(user)
    if int(tg_id) == OWNER_ID or is_owner(tg_id):
        role = "owner"
    else:
        chosen = panel_of(tg_id)
        role = "seller" if chosen == "admin" else "customer"
    title = {"owner": "👑 پنل مالک", "seller": "🏪 پنل ادمین"}.get(role, "🛍 پنل مشتری")
    markup = {"owner": kb_owner(lang), "seller": kb_seller(lang)}.get(role, kb_customer(lang))
    sub = ""
    if role == "seller":
        active = active_subscription(user["id"])
        sub = "\n⭐ اشتراک فعال تا " + str(active["ends_at"])[:16] if active else "\n⛔ اشتراک تمام شده. برای ادامه باید دوباره بخرید."
    bot.send_message(
        chat_id,
        box(title, t(lang, "welcome") + sub + "\n\n" + t(lang, "choose")),
        reply_markup=markup,
    )
    bot.send_message(chat_id, "منوی پایین چت هم آماده است.", reply_markup=chat_menu(lang, role))

def member_of(channel_id, user_id):
    if not channel_id:
        return True
    try:
        m = bot.get_chat_member(channel_id, user_id)
        return m.status in ("member", "administrator", "creator")
    except Exception as e:
        print("channel check failed:", e)
        return False

def gate_channels(user_id, shop=None):
    missing = []
    global_id = get_setting("global_channel_id")
    global_name = get_setting("global_channel_username")
    if global_id and not member_of(global_id, user_id):
        missing.append(global_name or global_id)
    if shop and shop.get("required_channel_id") and not member_of(shop.get("required_channel_id"), user_id):
        missing.append(shop.get("required_channel_username") or shop.get("required_channel_id"))
    return missing

def ask_join(chat_id, lang, names):
    k = types.InlineKeyboardMarkup()
    for name in names:
        clean = str(name).lstrip("@")
        if clean.startswith("-100") or clean.lstrip("-").isdigit():
            continue
        k.add(types.InlineKeyboardButton(clean, url=f"https://t.me/{clean}"))
    k.add(types.InlineKeyboardButton(t(lang, "joined"), callback_data="check_join"))
    bot.send_message(chat_id, t(lang, "join_first"), reply_markup=k)

def bot_link(shop_id):
    try:
        me = bot.get_me()
        return f"https://t.me/{me.username}?start=shop_{shop_id}"
    except Exception:
        return f"/start shop_{shop_id}"

def expect(chat_id, kind, extra=None):
    WAIT[chat_id] = {"kind": kind, "extra": extra or {}}
    bot.register_next_step_handler_by_chat_id(chat_id, on_text)

@bot.message_handler(commands=["start"])
def start(m):
    try:
        user = get_user(m.from_user)
    except Exception as e:
        print("start/get_user failed:", e)
        bot.send_message(m.chat.id, "ربات روشن است، ولی اتصال به دیتابیس خطا داد. schema_update.sql را در Supabase اجرا کنید.")
        return
    arg = ""
    parts = (m.text or "").split(maxsplit=1)
    if len(parts) > 1:
        arg = parts[1].strip()
    if arg.startswith("shop_"):
        PENDING_SHOP[m.chat.id] = arg.split("shop_", 1)[1]
    if not user.get("language_set"):
        ask_language(m.chat.id)
        return
    if panel_of(m.from_user.id) == "" and int(m.from_user.id) != OWNER_ID:
        ask_panel(m.chat.id, lang_of(user), m.from_user.id)
        return
    open_pending_or_home(m.chat.id, user, m.from_user.id)

def open_pending_or_home(chat_id, user, tg_id):
    shop_id = PENDING_SHOP.pop(chat_id, None)
    if shop_id and role_of(user, tg_id) == "customer":
        show_shop(chat_id, user, tg_id, shop_id)
        return
    send_home(chat_id, user, tg_id)

@bot.callback_query_handler(func=lambda c: True)
def callback(c):
    try:
        user = get_user(c.from_user)
    except Exception as e:
        print("callback/get_user failed:", e)
        bot.answer_callback_query(c.id, "Database error", show_alert=True)
        return
    lang = lang_of(user)
    data = c.data or ""
    bot.answer_callback_query(c.id)
    if data.startswith("lang_"):
        set_language(user["id"], data[-2:])
        user = get_user(c.from_user)
        ask_panel(c.message.chat.id, lang_of(user), c.from_user.id)
        return
    if data.startswith("panel_"):
        choice = data.split("_", 1)[1]
        if choice == "owner" and not is_owner(c.from_user.id):
            bot.send_message(c.message.chat.id, t(lang, "admin_only"))
            return
        if choice == "admin":
            trial = accept_admin(user)
            note = t(lang, "trial") if trial else t(lang, "trial_used")
            bot.send_message(c.message.chat.id, "شما به عنوان ادمین پذیرفته شدید.\n" + note)
        elif choice == "customer":
            set_panel(c.from_user.id, "customer")
        else:
            set_panel(c.from_user.id, "owner")
        user = get_user(c.from_user)
        send_home(c.message.chat.id, user, c.from_user.id)
        return
    if not user.get("language_set"):
        ask_language(c.message.chat.id)
        return
    if data == "language":
        ask_language(c.message.chat.id)
        return
    if data == "home":
        send_home(c.message.chat.id, user, c.from_user.id)
        return
    if data == "check_join":
        send_home(c.message.chat.id, user, c.from_user.id)
        return
    if data.startswith("own:"):
        if not is_owner(c.from_user.id):
            bot.send_message(c.message.chat.id, t(lang, "admin_only"))
            return
        owner_action(c, user, lang, data.split(":", 1)[1])
        return
    if data.startswith("sel:"):
        if not is_seller(user) and not is_owner(c.from_user.id):
            bot.send_message(c.message.chat.id, t(lang, "admin_only"))
            return
        seller_action(c, user, lang, data.split(":", 1)[1])
        return
    if data.startswith("cus:"):
        customer_action(c, user, lang, data.split(":", 1)[1])
        return
    if data.startswith("ok:"):
        if is_admin(c.from_user.id):
            approve_card_payment(data.split(":", 1)[1])
            bot.send_message(c.message.chat.id, "Approved")
        return
    if data.startswith("sh:"):
        show_shop(c.message.chat.id, user, c.from_user.id, data.split(":", 1)[1])
    elif data.startswith("pr:"):
        show_product(c.message.chat.id, lang, data.split(":", 1)[1])
    elif data.startswith("add:"):
        add_cart(user["id"], data.split(":", 1)[1])
        bot.answer_callback_query(c.id, t(lang, "added"))
    elif data == "cart":
        show_cart(c.message.chat.id, user, lang)
    elif data.startswith("rm:"):
        remove_cart(user["id"], data.split(":", 1)[1])
        show_cart(c.message.chat.id, user, lang)
    elif data == "checkout":
        checkout_menu(c.message.chat.id, lang)
    elif data.startswith("pay:"):
        create_and_pay(c.message.chat.id, user, lang, data.split(":", 1)[1])
    elif data == "orders":
        show_orders(c.message.chat.id, user)
    elif data.startswith("pl:"):
        pay_plan(c.message.chat.id, user, data.split(":", 1)[1])
    elif data.startswith("dp:"):
        if is_owner(c.from_user.id):
            deactivate_plan(data.split(":", 1)[1])
            bot.send_message(c.message.chat.id, t(lang, "saved"))
    elif data.startswith("ra:"):
        if is_owner(c.from_user.id):
            set_user_role(int(data.split(":", 1)[1]), "user")
            bot.send_message(c.message.chat.id, t(lang, "saved"))
    elif data.startswith("dc:"):
        if is_owner(c.from_user.id):
            clear_shop_channel(data.split(":", 1)[1])
            bot.send_message(c.message.chat.id, t(lang, "saved"))
    elif data == "dg":
        if is_owner(c.from_user.id):
            set_setting("global_channel_id", "")
            set_setting("global_channel_username", "")
            bot.send_message(c.message.chat.id, t(lang, "saved"))
    elif data.startswith("os:"):
        show_shop_products_text(c.message.chat.id, data.split(":", 1)[1])
    elif data == "sub:cancel":
        cancel_subscription(user["id"])
        bot.send_message(c.message.chat.id, t(lang, "saved"))
    elif data.startswith("sup:"):
        target = data.split(":", 1)[1]
        WAIT[c.message.chat.id] = {"kind": "support", "extra": {"target": target, "user": user}}
        bot.send_message(c.message.chat.id, t(lang, "ticket"))
        bot.register_next_step_handler_by_chat_id(c.message.chat.id, on_text)

def owner_action(c, user, lang, action):
    chat_id = c.message.chat.id
    if action == "admins":
        k = types.InlineKeyboardMarkup()
        for row in list_admins():
            if row.get("telegram_id") in ADMIN_IDS:
                continue
            k.add(types.InlineKeyboardButton(f"❌ {row.get('telegram_id')}", callback_data=f"ra:{row.get('telegram_id')}"))
        k.add(types.InlineKeyboardButton(t(lang, "add_admin"), callback_data="own:add_admin"))
        k.add(types.InlineKeyboardButton(t(lang, "back"), callback_data="home"))
        bot.send_message(chat_id, t(lang, "admins"), reply_markup=k)
    elif action == "add_admin":
        bot.send_message(chat_id, t(lang, "send_admin_id"))
        expect(chat_id, "add_admin")
    elif action == "revenue":
        data, subs = revenue_text()
        bot.send_message(chat_id, f"{t(lang, 'revenue')}\nOrders: {data['orders']}\nTotal: {data['revenue']}\nActive subs: {len(subs)}")
    elif action == "stats":
        lines = admin_sales()
        text = t(lang, "admin_stats") + "\n" + ("\n".join(
            [f"{x['shop']} | {x['admin']} | qty {x['orders']} | {x['total']} | {x['sub']}" for x in lines]
        ) or "-")
        bot.send_message(chat_id, text[:4000])
    elif action == "shops":
        rows = all_shops()
        if not rows:
            bot.send_message(chat_id, t(lang, "no_shops"))
            return
        k = types.InlineKeyboardMarkup()
        for shop in rows[:30]:
            k.add(types.InlineKeyboardButton(shop["title"], callback_data=f"os:{shop['id']}"))
        bot.send_message(chat_id, t(lang, "shops"), reply_markup=k)
    elif action == "channels":
        k = types.InlineKeyboardMarkup()
        gname = get_setting("global_channel_username") or "-"
        k.add(types.InlineKeyboardButton(f"Global: {gname}", callback_data="dg"))
        for shop in all_shops():
            if shop.get("required_channel_username") or shop.get("required_channel_id"):
                k.add(types.InlineKeyboardButton(
                    f"❌ {shop['title']} {shop.get('required_channel_username') or ''}",
                    callback_data=f"dc:{shop['id']}",
                ))
        k.add(types.InlineKeyboardButton(t(lang, "add_channel"), callback_data="own:add_channel"))
        bot.send_message(chat_id, t(lang, "channels"), reply_markup=k)
    elif action == "add_channel":
        bot.send_message(chat_id, t(lang, "send_channel"))
        expect(chat_id, "global_channel")
    elif action == "plans":
        k = types.InlineKeyboardMarkup()
        for plan in list_plans():
            name = plan["name_fa"] if lang == "fa" else plan["name_en"]
            k.add(types.InlineKeyboardButton(f"❌ {name} / {plan['days']}d / {plan['stars']}⭐", callback_data=f"dp:{plan['id']}"))
        k.add(types.InlineKeyboardButton(t(lang, "add_plan"), callback_data="own:add_plan"))
        bot.send_message(chat_id, t(lang, "plans"), reply_markup=k)
    elif action == "add_plan":
        bot.send_message(chat_id, t(lang, "send_plan"))
        expect(chat_id, "add_plan")
    elif action == "support":
        bot.send_message(chat_id, t(lang, "send_support"))
        expect(chat_id, "owner_support", {"user": user})

def seller_action(c, user, lang, action):
    chat_id = c.message.chat.id
    if action not in ("sub", "renew") and not active_subscription(user["id"]):
        bot.send_message(chat_id, "⛔ اشتراک شما تمام شده است. برای استفاده از پنل ادمین باید دوباره اشتراک بخرید.")
        seller_action(c, user, lang, "renew")
        return
    shop = my_shop(user["id"])
    if action == "shop":
        if not shop:
            bot.send_message(chat_id, t(lang, "send_shop"))
            expect(chat_id, "create_shop", {"user": user})
            return
        bot.send_message(chat_id, f"{shop['title']}\n{t(lang, 'link')}: {bot_link(shop['id'])}")
    elif action == "products":
        if not shop:
            bot.send_message(chat_id, t(lang, "send_shop"))
            return
        lines = [f"• {p['name_fa']} — {p['price']}" for p in shop_products(shop["id"])]
        bot.send_message(chat_id, (t(lang, "my_products") + "\n" + "\n".join(lines) + "\n\n" + t(lang, "send_product"))[:4000])
        expect(chat_id, "add_product", {"shop_id": shop["id"]})
    elif action == "sub":
        sub = active_subscription(user["id"])
        k = types.InlineKeyboardMarkup()
        k.add(types.InlineKeyboardButton(t(lang, "renew"), callback_data="sel:renew"))
        k.add(types.InlineKeyboardButton(t(lang, "cancel_sub"), callback_data="sub:cancel"))
        text = t(lang, "my_sub") + "\n" + (f"{sub['status']} until {sub['ends_at']}" if sub else "inactive")
        bot.send_message(chat_id, text, reply_markup=k)
    elif action == "renew":
        k = types.InlineKeyboardMarkup()
        for plan in list_plans():
            name = plan["name_fa"] if lang == "fa" else plan["name_en"]
            k.add(types.InlineKeyboardButton(f"{name} — {plan['stars']}⭐", callback_data=f"pl:{plan['id']}"))
        bot.send_message(chat_id, t(lang, "plans"), reply_markup=k)
    elif action == "channel":
        if not shop:
            bot.send_message(chat_id, t(lang, "send_shop"))
            return
        bot.send_message(chat_id, t(lang, "send_channel"))
        expect(chat_id, "shop_channel", {"shop_id": shop["id"]})
    elif action == "support":
        bot.send_message(chat_id, t(lang, "send_support"))
        expect(chat_id, "seller_support", {"user": user})

def customer_action(c, user, lang, action):
    chat_id = c.message.chat.id
    if action == "shops":
        rows = public_shops()
        if not rows:
            bot.send_message(chat_id, t(lang, "no_shops"))
            return
        k = types.InlineKeyboardMarkup()
        for shop in rows[:30]:
            k.add(types.InlineKeyboardButton(shop["title"], callback_data=f"sh:{shop['id']}"))
        bot.send_message(chat_id, t(lang, "shop"), reply_markup=k)
    elif action == "support":
        k = types.InlineKeyboardMarkup()
        k.add(types.InlineKeyboardButton(t(lang, "support_seller"), callback_data="sup:seller"))
        k.add(types.InlineKeyboardButton(t(lang, "support_owner"), callback_data="sup:owner"))
        bot.send_message(chat_id, t(lang, "support"), reply_markup=k)

def show_shop(chat_id, user, tg_id, shop_id):
    lang = lang_of(user)
    shop = shop_by_id(shop_id)
    if not shop:
        bot.send_message(chat_id, t(lang, "not_found"))
        return
    missing = gate_channels(tg_id, shop)
    if missing and role_of(user, tg_id) == "customer":
        ask_join(chat_id, lang, missing)
        return
    if role_of(user, tg_id) == "customer" and not shop_has_active_sub(shop):
        bot.send_message(chat_id, t(lang, "need_sub"))
        return
    LAST_SHOP[chat_id] = shop_id
    k = types.InlineKeyboardMarkup()
    for p in shop_products(shop_id):
        name = p["name_fa"] if lang == "fa" else p["name_en"]
        k.add(types.InlineKeyboardButton(f"{name} — {p['price']}", callback_data=f"pr:{p['id']}"))
    k.add(types.InlineKeyboardButton(t(lang, "back"), callback_data="home"))
    bot.send_message(chat_id, shop["title"], reply_markup=k)

def show_shop_products_text(chat_id, shop_id):
    shop = shop_by_id(shop_id)
    if not shop:
        bot.send_message(chat_id, "Not found")
        return
    lines = [f"• {p['name_fa']} — {p['price']}" for p in shop_products(shop_id)]
    bot.send_message(chat_id, f"{shop['title']}\n" + ("\n".join(lines) or "-"))

def show_product(chat_id, lang, pid):
    p = product(pid)
    if not p:
        bot.send_message(chat_id, t(lang, "not_found"))
        return
    name = p["name_fa"] if lang == "fa" else p["name_en"]
    desc = p.get("description_fa") if lang == "fa" else p.get("description_en")
    text = f"<b>{name}</b>\n\n{desc or ''}\n\n💵 {p['price']}\n📦 {p.get('stock')}"
    k = types.InlineKeyboardMarkup()
    k.add(types.InlineKeyboardButton(t(lang, "cart"), callback_data=f"add:{pid}"))
    k.add(types.InlineKeyboardButton(t(lang, "buy"), callback_data=f"add:{pid}"))
    bot.send_message(chat_id, text, reply_markup=k)

def show_cart(chat_id, user, lang):
    items = cart(user["id"])
    if not items:
        bot.send_message(chat_id, t(lang, "empty_cart"))
        return
    total = sum(float(x["products"]["price"]) * x["quantity"] for x in items)
    k = types.InlineKeyboardMarkup()
    for x in items:
        p = x["products"]
        name = p["name_fa"] if lang == "fa" else p["name_en"]
        k.add(types.InlineKeyboardButton(f"❌ {name} × {x['quantity']}", callback_data=f"rm:{x['id']}"))
    k.add(types.InlineKeyboardButton(t(lang, "checkout"), callback_data="checkout"))
    bot.send_message(chat_id, f"🛒\n💵 {total}", reply_markup=k)

def checkout_menu(chat_id, lang):
    k = types.InlineKeyboardMarkup()
    k.add(types.InlineKeyboardButton(t(lang, "stars"), callback_data="pay:stars"))
    k.add(types.InlineKeyboardButton(t(lang, "card"), callback_data="pay:card"))
    bot.send_message(chat_id, t(lang, "payment"), reply_markup=k)

def create_and_pay(chat_id, user, lang, method):
    order = create_order(user, method)
    if not order:
        bot.send_message(chat_id, t(lang, "empty_cart"))
        return
    total = float(order["total"])
    if method == "stars":
        prices = [types.LabeledPrice(label="Order", amount=stars_amount(total))]
        bot.send_invoice(chat_id, "Shop Order", "Telegram Shop Order", f"order:{order['id']}", "", "XTR", prices)
    else:
        bot.send_message(chat_id, f"💳 {CARD_NUMBER}\n👤 {CARD_HOLDER}\n\nOrder ID: {order['id']}\nAmount: {total}\nپس از پرداخت، رسید را ارسال کنید.")
        WAIT[chat_id] = {"kind": "receipt", "extra": {"order_id": order["id"]}}
        bot.register_next_step_handler_by_chat_id(chat_id, on_text)

def pay_plan(chat_id, user, plan_id):
    plan = plan_by_id(plan_id)
    if not plan:
        bot.send_message(chat_id, "Plan not found")
        return
    shop = my_shop(user["id"])
    shop_id = shop["id"] if shop else "none"
    prices = [types.LabeledPrice(label=plan["name_en"], amount=max(1, int(plan["stars"])))]
    bot.send_invoice(chat_id, plan["name_en"], "Shop subscription", f"plan:{plan['id']}:{user['id']}:{shop_id}", "", "XTR", prices)

def show_orders(chat_id, user):
    rows = customer_orders(user["id"])
    if not rows:
        bot.send_message(chat_id, "No orders.")
        return
    text = "\n".join([f"#{x['id'][:8]} — {x['status']} — {x['total']}" for x in rows[:10]])
    bot.send_message(chat_id, text)

def parse_channel(text):
    parts = [x.strip() for x in text.split("|")]
    username = parts[0].lstrip("@") if parts else ""
    channel_id = parts[1] if len(parts) > 1 else username
    return channel_id, username

def on_text(m):
    state = WAIT.pop(m.chat.id, None)
    if not state:
        return
    user = get_user(m.from_user)
    lang = lang_of(user)
    kind = state["kind"]
    text = m.text or m.caption or ""
    try:
        if kind == "add_admin":
            row = set_user_role(int(text.strip()), "admin")
            bot.send_message(m.chat.id, t(lang, "saved") if row else t(lang, "not_found"))
        elif kind == "add_plan":
            name_fa, name_en, days, stars = [x.strip() for x in text.split("|")]
            add_plan(name_fa, name_en, days, stars)
            bot.send_message(m.chat.id, t(lang, "saved"))
        elif kind == "global_channel":
            channel_id, username = parse_channel(text)
            set_setting("global_channel_id", channel_id)
            set_setting("global_channel_username", username)
            bot.send_message(m.chat.id, t(lang, "saved"))
        elif kind == "owner_support":
            set_setting("owner_support", text.strip())
            set_support(user["id"], text.strip())
            bot.send_message(m.chat.id, t(lang, "saved"))
        elif kind == "create_shop":
            shop, trial = create_shop(user, text.strip())
            extra = "\n" + (t(lang, "trial") if trial else t(lang, "trial_used"))
            bot.send_message(m.chat.id, f"{shop['title']}\n{bot_link(shop['id'])}{extra}")
        elif kind == "add_product":
            name_fa, name_en, price, stock = [x.strip() for x in text.split("|")]
            add_shop_product(state["extra"]["shop_id"], name_fa, name_en, price, stock)
            bot.send_message(m.chat.id, t(lang, "saved"))
        elif kind == "shop_channel":
            channel_id, username = parse_channel(text)
            set_shop_channel(state["extra"]["shop_id"], channel_id, username)
            bot.send_message(m.chat.id, t(lang, "saved"))
        elif kind == "seller_support":
            set_support(user["id"], text.strip())
            bot.send_message(m.chat.id, t(lang, "saved"))
        elif kind == "support":
            target = state["extra"].get("target")
            save_support_message(user["id"], None, target, text)
            if target == "owner":
                dest = get_setting("owner_support")
                for admin in ADMIN_IDS:
                    bot.send_message(admin, f"Support for owner\nfrom {m.from_user.id}\n{text}")
                if dest:
                    bot.send_message(m.chat.id, f"Sent. Owner: {dest}")
                else:
                    bot.send_message(m.chat.id, t(lang, "saved"))
            else:
                shop = shop_by_id(LAST_SHOP.get(m.chat.id)) if LAST_SHOP.get(m.chat.id) else None
                if not shop:
                    shops = public_shops()
                    shop = shops[0] if shops else None
                if shop:
                    owner = one("users", {"id": shop["owner_user_id"]})
                    if owner:
                        bot.send_message(owner["telegram_id"], f"Support\nfrom {m.from_user.id}\n{text}")
                bot.send_message(m.chat.id, t(lang, "saved"))
        elif kind == "receipt":
            submit_receipt(m, state["extra"]["order_id"])
    except Exception as e:
        print("form failed:", e)
        bot.send_message(m.chat.id, t(lang, "not_found"))

def submit_receipt(m, order_id):
    text = m.text or m.caption or ""
    if m.content_type == "photo":
        text = f"PHOTO:{m.photo[-1].file_id}\n{text}"
    table("payment_receipts").insert({"order_id": order_id, "telegram_id": m.from_user.id, "text": text}).execute()
    k = types.InlineKeyboardMarkup()
    k.add(types.InlineKeyboardButton("✅ Approve", callback_data=f"ok:{order_id}"))
    for admin in ADMIN_IDS:
        try:
            bot.send_message(admin, f"Receipt\nOrder: {order_id}\n{text}", reply_markup=k)
        except Exception:
            pass
    bot.send_message(m.chat.id, "✅ Receipt submitted.")

@bot.pre_checkout_query_handler(func=lambda q: True)
def precheckout(q):
    bot.answer_pre_checkout_query(q.id, ok=True)

@bot.message_handler(content_types=["successful_payment"])
def successful_payment(m):
    payload = m.successful_payment.invoice_payload
    if payload.startswith("plan:"):
        parts = payload.split(":")
        plan_id, user_id = parts[1], parts[2]
        shop_id = parts[3] if len(parts) > 3 and parts[3] != "none" else None
        plan = plan_by_id(plan_id)
        if plan:
            ends = activate_plan(user_id, shop_id, plan)
            bot.send_message(m.chat.id, f"✅ اشتراک فعال شد تا {ends.date()}")
        return
    order_id = payload.split(":", 1)[1]
    mark_paid(order_id, m.successful_payment.telegram_payment_charge_id)
    bot.send_message(m.chat.id, "✅ Payment successful.")
    rows = table("order_items").select("*").eq("order_id", order_id).execute().data
    for x in rows:
        content = x.get("digital_delivery")
        if content:
            bot.send_message(m.chat.id, f"🔐 {x.get('product_name')}\n\n{content}")

@bot.message_handler(commands=["menu", "panel", "shops", "support"])
def menu_commands(m):
    user = get_user(m.from_user)
    if m.text.startswith("/panel"):
        ask_panel(m.chat.id, lang_of(user), m.from_user.id)
        return
    if m.text.startswith("/shops"):
        customer_action(types.SimpleNamespace(message=m), user, lang_of(user), "shops")
        return
    if m.text.startswith("/support"):
        customer_action(types.SimpleNamespace(message=m), user, lang_of(user), "support")
        return
    send_home(m.chat.id, user, m.from_user.id)

@bot.message_handler(func=lambda m: m.content_type == "text" and m.chat.id not in WAIT)
def menu_text(m):
    user = get_user(m.from_user)
    lang = lang_of(user)
    text = m.text or ""
    fake = types.SimpleNamespace(message=m, from_user=m.from_user, id="0", data="")
    if text in ("👑 پنل مالک", "🏪 پنل ادمین", "🔁 تغییر پنل"):
        if text == "🔁 تغییر پنل":
            ask_panel(m.chat.id, lang, m.from_user.id)
        else:
            send_home(m.chat.id, user, m.from_user.id)
    elif text == "📊 درآمد":
        owner_action(fake, user, lang, "revenue")
    elif text == "🛍 فروشگاه‌ها":
        if is_owner(m.from_user.id):
            owner_action(fake, user, lang, "shops")
        else:
            customer_action(fake, user, lang, "shops")
    elif text == "📣 کانال‌ها":
        owner_action(fake, user, lang, "channels")
    elif text == "⭐ اشتراک‌ها":
        owner_action(fake, user, lang, "plans")
    elif text in ("⭐ اشتراک من",):
        seller_action(fake, user, lang, "sub")
    elif text == "🛍 فروشگاه من":
        seller_action(fake, user, lang, "shop")
    elif text == "📦 محصولات":
        seller_action(fake, user, lang, "products")
    elif text == "📣 کانال من":
        seller_action(fake, user, lang, "channel")
    elif text == "🛒 سبد خرید":
        show_cart(m.chat.id, user, lang)
    elif text == "📦 سفارش‌ها":
        show_orders(m.chat.id, user)
    elif text == "🎫 پشتیبانی":
        customer_action(fake, user, lang, "support")
    elif text == "🌐 زبان":
        ask_language(m.chat.id)

setup_commands()

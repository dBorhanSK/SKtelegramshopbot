import html
import json
import re
from datetime import datetime, timezone

import telebot
from telebot import types
from config import *
from i18n import t, tf, num, fmt_amount, fmt_date, to_ascii_digits
from services import *
from payments import stars_amount
from db import table, one

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")


class PersistentWait(dict):
    """Same dict API the bot already uses (WAIT[chat] = {...}, WAIT.pop, `in`), but every
    unfinished form is mirrored to the `bot_states` table. A Render restart/sleep no longer
    drops an address, product or review form half-way. Best effort: if the table is missing
    the bot keeps working purely in memory."""

    def __init__(self):
        super().__init__()
        self._checked = set()
        self._warned = False

    def _warn(self, e):
        if not self._warned:
            self._warned = True
            print("bot_states unavailable (run schema_update.sql):", e)

    def _load(self, key):
        key = int(key)
        if key in self._checked:
            return
        self._checked.add(key)
        try:
            row = one("bot_states", {"chat_id": key})
        except Exception as e:
            self._warn(e)
            return
        if not row:
            return
        try:
            updated = datetime.fromisoformat(str(row["updated_at"]).replace("Z", "+00:00"))
            fresh = (datetime.now(timezone.utc) - updated).total_seconds() < STATE_TTL_MIN * 60
        except Exception:
            fresh = False
        if not fresh:
            self._drop(key)
            return
        dict.__setitem__(self, key, {"kind": row.get("kind"), "extra": row.get("data") or {}})

    def _save(self, key, value):
        try:
            table("bot_states").upsert({
                "chat_id": int(key),
                "kind": value.get("kind"),
                "data": json.loads(json.dumps(value.get("extra") or {}, default=str)),
                "updated_at": iso_now(),
            }, on_conflict="chat_id").execute()
        except Exception as e:
            self._warn(e)

    def _drop(self, key):
        try:
            table("bot_states").delete().eq("chat_id", int(key)).execute()
        except Exception as e:
            self._warn(e)

    def __contains__(self, key):
        self._load(key)
        return dict.__contains__(self, key)

    def __getitem__(self, key):
        self._load(key)
        return dict.__getitem__(self, key)

    def get(self, key, default=None):
        self._load(key)
        return dict.get(self, key, default)

    def __setitem__(self, key, value):
        self._checked.add(int(key))
        dict.__setitem__(self, key, value)
        self._save(key, value)

    def pop(self, key, *default):
        self._load(key)
        had = dict.__contains__(self, key)
        value = dict.pop(self, key, *default)
        if had:
            self._drop(key)
        return value


WAIT = PersistentWait()
PENDING_SHOP = {}
LAST_SHOP = {}
DEAL_CHAT = {}
OWNER_ID = 6914909647

def box(title, body):
    return f"✦ <b>{title}</b>\n━━━━━━━━━━━━\n{body}"

def labels(*keys):
    return {t("fa", key) for key in keys} | {t("en", key) for key in keys}

def chat_menu(lang, role):
    k = types.ReplyKeyboardMarkup(resize_keyboard=True, is_persistent=True)
    if role == "owner":
        k.row(t(lang, "owner_btn"), t(lang, "income_btn"))
        k.row(t(lang, "admins"), t(lang, "admin_stats"))
        k.row(t(lang, "shops"), t(lang, "channels"))
        k.row(t(lang, "plans"), t(lang, "manage_orders_btn"))
        k.row(t(lang, "my_support"), t(lang, "language"))
    elif role == "seller":
        k.row(t(lang, "admin_btn"), t(lang, "my_sub_btn"))
        k.row(t(lang, "my_shop_btn"), t(lang, "products_btn"))
        k.row(t(lang, "manage_orders_btn"), t(lang, "my_channel_btn"))
        k.row(t(lang, "pay_method"), t(lang, "my_support"))
        k.row(t(lang, "language"))
    else:
        k.row(t(lang, "shop"), t(lang, "cart"))
        k.row(t(lang, "orders"), t(lang, "support"))
        k.row(t(lang, "language"), t(lang, "switch_panel"))
    return k

def setup_commands():
    try:
        bot.set_my_commands([
            types.BotCommand("start", "شروع و انتخاب زبان"),
            types.BotCommand("menu", "منوی پنل"),
            types.BotCommand("panel", "تغییر پنل"),
            types.BotCommand("shops", "فروشگاه‌ها"),
            types.BotCommand("support", "پشتیبانی"),
        ], language_code="fa")
        bot.set_my_commands([
            types.BotCommand("start", "Start and choose language"),
            types.BotCommand("menu", "Open panel menu"),
            types.BotCommand("panel", "Switch panel"),
            types.BotCommand("shops", "Shops"),
            types.BotCommand("support", "Support"),
        ], language_code="en")
        # everyone whose Telegram language is neither fa nor en gets the English list
        bot.set_my_commands([
            types.BotCommand("start", "Start and choose language"),
            types.BotCommand("menu", "Open panel menu"),
            types.BotCommand("panel", "Switch panel"),
            types.BotCommand("shops", "Shops"),
            types.BotCommand("support", "Support"),
        ])
    except Exception as e:
        print("commands:", e)

def ask_panel(chat_id, lang, tg_id):
    k = types.InlineKeyboardMarkup()
    if int(tg_id) == OWNER_ID or is_owner(tg_id):
        k.add(types.InlineKeyboardButton(t(lang, "owner_btn"), callback_data="panel_owner"))
    k.add(types.InlineKeyboardButton(t(lang, "admin_btn"), callback_data="panel_admin"))
    k.add(types.InlineKeyboardButton(t(lang, "customer_btn"), callback_data="panel_customer"))
    bot.send_message(chat_id, box(t(lang, "choose"), t(lang, "pick_panel")), reply_markup=k)

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
    k.row(types.InlineKeyboardButton("🚚 " + t(lang, "manage_orders"), callback_data="own:orders"))
    k.row(types.InlineKeyboardButton(t(lang, "my_support"), callback_data="own:support"))
    k.row(types.InlineKeyboardButton(t(lang, "language"), callback_data="language"))
    return k

def kb_seller(lang):
    k = types.InlineKeyboardMarkup()
    k.row(types.InlineKeyboardButton(t(lang, "my_shop"), callback_data="sel:shop"))
    k.row(types.InlineKeyboardButton(t(lang, "my_products"), callback_data="sel:products"))
    k.row(types.InlineKeyboardButton("🚚 " + t(lang, "manage_orders"), callback_data="sel:orders"))
    k.row(types.InlineKeyboardButton(t(lang, "pay_method"), callback_data="sel:method"))
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
    title = {"owner": t(lang, "owner_btn"), "seller": t(lang, "admin_btn")}.get(role, t(lang, "customer_btn"))
    markup = {"owner": kb_owner(lang), "seller": kb_seller(lang)}.get(role, kb_customer(lang))
    sub = ""
    if role == "seller":
        active = active_subscription(user["id"])
        sub = "\n⭐ " + t(lang, "sub_active") + " " + fmt_date(lang, active["ends_at"]) if active else "\n⛔ " + t(lang, "sub_expired")
        try:
            waiting = count_to_ship(user["id"])
        except Exception:
            waiting = 0
        if waiting:
            sub += "\n🚚 " + t(lang, "to_ship_count") + ": " + num(lang, waiting)
    bot.send_message(
        chat_id,
        box(title, t(lang, "welcome") + sub + "\n\n" + t(lang, "choose")),
        reply_markup=markup,
    )
    bot.send_message(chat_id, t(lang, "menu_ready"), reply_markup=chat_menu(lang, role))

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
    try:
        bot.clear_step_handler_by_chat_id(chat_id)
    except Exception:
        pass

# =====================================================================
# NEW: helpers, orders, shipping wizard, checkout, fulfilment
# =====================================================================
def esc(x):
    return html.escape("" if x is None else str(x), quote=False)

def trunc(x, n):
    x = "" if x is None else str(x)
    return x if len(x) <= n else x[: n - 1] + "…"

def short_id(x):
    return str(x)[:8]

def pname(lang, p):
    p = p or {}
    if lang == "fa":
        return p.get("name_fa") or p.get("name_en") or "-"
    return p.get("name_en") or p.get("name_fa") or "-"

def oname(lang, it):
    if lang == "fa":
        return it.get("product_name") or it.get("product_name_en") or "-"
    return it.get("product_name_en") or it.get("product_name") or "-"

def pdesc(lang, p):
    d = p.get("description_fa") if lang == "fa" else p.get("description_en")
    return d or p.get("description_fa") or p.get("description_en") or ""

def money(lang, amount, currency):
    if currency == "XTR":
        return f"{fmt_amount(lang, amount)} ⭐"
    if currency == "CUSTOM":
        return t(lang, "custom_price")
    unit = t(lang, "irt_unit") if CURRENCY == "IRT" else CURRENCY
    return f"{fmt_amount(lang, amount)} {unit}"

def notify(tg_id, text, markup=None):
    try:
        bot.send_message(tg_id, text, reply_markup=markup)
        return True
    except Exception as e:
        print("notify failed:", tg_id, e)
        return False

def address_lines(lang, ship):
    rows = [("👤", "f_name", ship.get("name")), ("📞", "f_phone", ship.get("phone")),
            ("📍", "f_address", ship.get("address")), ("📮", "f_postal", ship.get("postal"))]
    return "\n".join(f"{ic} {t(lang, key)}: {esc(val)}" for ic, key, val in rows if val)

def ship_of_order(o):
    return {"name": o.get("ship_name"), "phone": o.get("ship_phone"),
            "address": o.get("ship_address"), "postal": o.get("ship_postal_code")}

def clean_phone(text):
    s = to_ascii_digits(text).strip()
    digits = re.sub(r"\D", "", s)
    if not (7 <= len(digits) <= 15):
        return None
    return ("+" if s.startswith("+") else "") + digits

def clean_postal(text):
    s = to_ascii_digits(text).strip()
    if s in ("", "-", "–", "—"):
        return ""
    s = re.sub(r"[\s-]", "", s)
    return s if re.fullmatch(r"[A-Za-z0-9]{3,12}", s) else None

def continue_onboarding(chat_id, user, tg_id):
    """Language is already set. Next: panel (skipped when the person arrived through a
    shop link: they are obviously a customer), then the home screen."""
    if panel_of(tg_id) == "" and int(tg_id) != OWNER_ID:
        if chat_id in PENDING_SHOP:
            set_panel(tg_id, "customer")
        else:
            ask_panel(chat_id, lang_of(user), tg_id)
            return
    open_pending_or_home(chat_id, user, tg_id)

def gate_onboarding(m, user):
    """True when language/panel still has to be chosen (the person has been asked)."""
    if not user.get("language_set"):
        ask_language(m.chat.id)
        return True
    if panel_of(m.from_user.id) == "" and int(m.from_user.id) != OWNER_ID:
        ask_panel(m.chat.id, lang_of(user), m.from_user.id)
        return True
    return False

# ------------------------------------------------------------------ order views
def order_role(user, tg_id, o):
    if o.get("user_id") == user["id"]:
        return "customer"
    if o.get("seller_id") and o["seller_id"] == user["id"]:
        return "seller"
    if is_owner(tg_id):
        return "owner"
    return None

def pm_label(lang, o):
    key = {"stars": "pm_stars", "custom": "pm_custom", "card": "pm_card"}.get(o.get("payment_method"))
    return t(lang, key) if key else "-"

def order_status_label(lang, o):
    st = o.get("status") or "pending"
    key = "st_paid_ship" if (st == "paid" and o.get("requires_shipping")) else "st_" + st
    label = t(lang, key)
    return st if label == key else label

def order_card(lang, o, items, role):
    cur = o.get("currency") or "IRT"
    lines = [
        f"🧾 <b>{t(lang, 'order_word')} #{short_id(o['id'])}</b>",
        f"{t(lang, 'status_word')}: {order_status_label(lang, o)}",
        f"{t(lang, 'date_word')}: {fmt_date(lang, o.get('created_at'))}",
        f"{t(lang, 'pay_method_word')}: {pm_label(lang, o)}",
        "",
        f"<b>{t(lang, 'items_word')}:</b>",
    ]
    for it in items:
        q = int(it.get("quantity") or 1)
        kind = t(lang, "type_physical_short" if it.get("product_type") == "physical" else "type_digital_short")
        price = "" if cur == "CUSTOM" else " — " + money(lang, float(it.get("unit_price") or 0) * q, cur)
        lines.append(f"• {esc(oname(lang, it))} × {num(lang, q)} ({kind}){price}")
    lines.append(f"{t(lang, 'total_word')}: {money(lang, o.get('total') or 0, cur)}")
    if o.get("requires_shipping"):
        if role == "customer" or o.get("payment_status") == "paid":
            lines += ["", f"📦 <b>{t(lang, 'ship_by_post')}</b>", address_lines(lang, ship_of_order(o))]
        else:
            lines += ["", t(lang, "address_after_pay")]
        if o.get("tracking_code") and o.get("status") in ("shipped", "completed"):
            lines.append(f"🚚 {t(lang, 'tracking_code')}: <code>{esc(o['tracking_code'])}</code>")
    return "\n".join(lines)

def order_markup(lang, o, role, has_digital, deal):
    k = types.InlineKeyboardMarkup()
    oid, st = o["id"], o.get("status")
    paid = o.get("payment_status") == "paid"
    if role == "customer":
        if st == "pending" and not paid:
            if o.get("payment_method") in ("stars", "card"):
                k.add(types.InlineKeyboardButton(t(lang, "btn_pay_now"), callback_data=f"po:{oid}"))
            k.add(types.InlineKeyboardButton(t(lang, "btn_cancel_order"), callback_data=f"cn:{oid}"))
        if paid and has_digital and st != "cancelled":
            k.add(types.InlineKeyboardButton(t(lang, "btn_resend"), callback_data=f"rd:{oid}"))
        if st == "shipped":
            k.add(types.InlineKeyboardButton(t(lang, "btn_received"), callback_data=f"rc:{oid}"))
    else:
        if o.get("requires_shipping") and paid and st in ("paid", "shipped"):
            k.add(types.InlineKeyboardButton(t(lang, "btn_mark_shipped"), callback_data=f"sg:{oid}"))
            if st == "paid":
                k.add(types.InlineKeyboardButton(t(lang, "btn_refund"), callback_data=f"cn:{oid}"))
        if st == "pending" and o.get("payment_method") == "custom" and deal and deal.get("status") == "open":
            k.add(types.InlineKeyboardButton(t(lang, "confirm_paid"), callback_data=f"cf:{deal['id']}"))
            k.add(types.InlineKeyboardButton(t(lang, "cancel_deal"), callback_data=f"cx:{deal['id']}"))
    return k

def show_order(chat_id, user, tg_id, lang, order_id):
    o = order_by_id(order_id)
    role = order_role(user, tg_id, o) if o else None
    if not o or not role:
        bot.send_message(chat_id, t(lang, "not_found"))
        return
    items = order_items(order_id)
    deal = deal_for_order(order_id) if (role != "customer" and o.get("payment_method") == "custom") else None
    has_digital = any(it.get("product_type") != "physical" for it in items)
    bot.send_message(chat_id, order_card(lang, o, items, role), reply_markup=order_markup(lang, o, role, has_digital, deal))

def show_manage_orders(chat_id, user, tg_id, lang, flt="all"):
    if is_owner(tg_id):
        rows = all_order_rows(only_ship=(flt == "ship"))
        waiting = count_to_ship()
    elif my_shop(user["id"]) or is_seller(user):
        rows = seller_order_rows(user["id"], only_ship=(flt == "ship"))
        waiting = count_to_ship(user["id"])
    else:
        bot.send_message(chat_id, t(lang, "not_allowed"))
        return
    k = types.InlineKeyboardMarkup()
    k.row(types.InlineKeyboardButton(t(lang, "btn_toship"), callback_data="ol:ship"),
          types.InlineKeyboardButton(t(lang, "btn_all_orders"), callback_data="ol:all"))
    for o in rows:
        label = f"{order_status_label(lang, o)} #{short_id(o['id'])} · {money(lang, o.get('total') or 0, o.get('currency') or 'IRT')}"
        k.add(types.InlineKeyboardButton(trunc(label, 60), callback_data=f"od:{o['id']}"))
    head = f"<b>{t(lang, 'manage_orders')}</b>\n{t(lang, 'to_ship_count')}: {num(lang, waiting)}"
    if not rows:
        head += "\n\n" + t(lang, "no_orders_here")
    bot.send_message(chat_id, head, reply_markup=k)

# ----------------------------------------------------------- fulfilment
def seller_targets(o):
    if o.get("seller_id"):
        s = user_by_id(o["seller_id"])
        if s:
            return [(s["telegram_id"], lang_of(s))]
    return [(tg, lang_of_tg(tg)) for tg in owner_ids()]

def seller_order_message(lang, o, items, kind):
    head = {"paid": "seller_new_paid", "sale": "seller_new_sale", "custom": "seller_new_custom"}[kind]
    lines = [f"<b>{tf(lang, head, id=short_id(o['id']))}</b>", ""]
    for it in items:
        lines.append(f"• {esc(oname(lang, it))} × {num(lang, int(it.get('quantity') or 1))}")
    if (o.get("currency") or "") == "XTR":
        lines.append(f"{t(lang, 'total_word')}: {money(lang, o.get('total') or 0, 'XTR')}")
    if o.get("requires_shipping"):
        if kind == "custom":
            lines += ["", t(lang, "address_after_pay"), "", t(lang, "seller_custom_hint")]
        else:
            lines += ["", f"📦 <b>{t(lang, 'ship_by_post')}</b>", address_lines(lang, ship_of_order(o)), "", t(lang, "seller_ship_hint")]
    elif kind == "custom":
        lines += ["", t(lang, "new_deal")]
    return "\n".join(lines)

def deliver_order_digital(chat_id, lang, items):
    failed = []
    for it in items:
        if it.get("product_type") == "physical":
            continue
        p = product(it["product_id"]) if it.get("product_id") else None
        try:
            bot.send_message(chat_id, f"🔐 {esc(oname(lang, it))}")
            if p and (p.get("product_file_id") or p.get("digital_content")):
                deliver_product(chat_id, p)
            elif it.get("digital_delivery"):
                bot.send_message(chat_id, esc(it["digital_delivery"]))
            else:
                failed.append(it)
        except Exception as e:
            print("digital delivery failed:", e)
            failed.append(it)
    return failed

def finalize_paid_order(o, source="stars"):
    """Runs exactly once per order, right after claim_payment() succeeded.
    Returns (ok, reason). reason == 'stock' means the caller must undo the payment."""
    items = order_items(o["id"])
    customer = user_by_id(o["user_id"])
    if not customer:
        return False, "no_customer"
    clang, ctg, short = lang_of(customer), customer["telegram_id"], short_id(o["id"])
    shipping = bool(o.get("requires_shipping"))
    if shipping and not deduct_order_stock(o, items):
        return False, "stock"
    k = types.InlineKeyboardMarkup()
    k.add(types.InlineKeyboardButton(t(clang, "btn_order_details"), callback_data=f"od:{o['id']}"))
    notify(ctg, tf(clang, "order_paid_ship" if shipping else "order_paid_digital", id=short), k)
    if deliver_order_digital(ctg, clang, items):
        notify(ctg, t(clang, "digital_failed"))
    if not shipping:
        update_order(o["id"], status="completed", completed_at=iso_now())
    fresh = order_by_id(o["id"]) or o
    for tg, sl in seller_targets(fresh):
        sk = types.InlineKeyboardMarkup()
        if shipping:
            sk.add(types.InlineKeyboardButton(t(sl, "btn_mark_shipped"), callback_data=f"sg:{o['id']}"))
            sk.add(types.InlineKeyboardButton(t(sl, "btn_refund"), callback_data=f"cn:{o['id']}"))
        sk.add(types.InlineKeyboardButton(t(sl, "btn_order_details"), callback_data=f"od:{o['id']}"))
        notify(tg, seller_order_message(sl, fresh, items, "paid" if shipping else "sale"), sk)
    return True, None

def refund_charge(tg_id, charge_id):
    try:
        return bool(bot.refund_star_payment(user_id=int(tg_id), telegram_payment_charge_id=charge_id))
    except Exception as e:
        print("refund failed:", e)
        return False

def refund_order_payment(o):
    customer = user_by_id(o["user_id"])
    if not customer or not o.get("transaction_id") or o.get("payment_method") != "stars":
        return False
    return refund_charge(customer["telegram_id"], o["transaction_id"])

def handle_order_payment(m, order_id):
    sp = m.successful_payment
    charge = sp.telegram_payment_charge_id
    lang = lang_of(get_user(m.from_user))
    o = order_by_id(order_id)
    if not o:
        refund_charge(m.from_user.id, charge)
        for tg in owner_ids():
            notify(tg, f"⚠️ Payment for unknown order {esc(order_id)} was refunded. charge={esc(charge)}")
        return
    record_charge(charge, "order", order_id, o.get("user_id"), m.from_user.id, sp.total_amount, sp.currency)  # audit trail
    if sp.currency != "XTR" or int(sp.total_amount) != order_stars_amount(o):
        refund_charge(m.from_user.id, charge)
        bot.send_message(m.chat.id, t(lang, "amount_mismatch"))
        return
    claimed = claim_payment(order_id, charge)   # atomic: only the first delivery wins
    if not claimed:
        latest = order_by_id(order_id) or {}
        if latest.get("payment_status") == "paid":
            return                               # duplicated webhook: already fulfilled
        refund_charge(m.from_user.id, charge)
        bot.send_message(m.chat.id, t(lang, "late_payment_refund"))
        return
    ok, why = finalize_paid_order(claimed, "stars")
    if not ok and why == "stock":
        refunded = refund_charge(m.from_user.id, charge)
        update_order(order_id, status="cancelled", payment_status="refunded" if refunded else "paid", cancelled_at=iso_now())
        bot.send_message(m.chat.id, t(lang, "stock_race_refund"))
        if not refunded:
            for tg in owner_ids():
                notify(tg, f"⚠️ Manual refund needed: order {esc(order_id)} charge={esc(charge)}")

def precheck_order(order_id, q):
    lang = lang_of_tg(q.from_user.id)
    o = order_by_id(order_id)
    if not o or o.get("status") != "pending" or o.get("payment_status") != "unpaid":
        return False, t(lang, "order_inactive")
    if int(q.total_amount) != order_stars_amount(o):
        return False, t(lang, "order_inactive")
    for it in order_items(order_id):
        if it.get("product_type") == "physical":
            p = product(it["product_id"]) if it.get("product_id") else None
            if not p or not p.get("active", True) or int(p.get("stock") or 0) < int(it.get("quantity") or 1):
                return False, t(lang, "item_unavailable")
    return True, None

# ------------------------------------------------- ship / receive / cancel
def can_fulfil(user, tg_id, o):
    return bool(o) and order_role(user, tg_id, o) in ("seller", "owner")

def start_tracking(chat_id, user, tg_id, lang, order_id):
    o = order_by_id(order_id)
    if not can_fulfil(user, tg_id, o) or not (o.get("requires_shipping") and o.get("payment_status") == "paid"
                                              and o.get("status") in ("paid", "shipped")):
        bot.send_message(chat_id, t(lang, "not_allowed"))
        return
    bot.send_message(chat_id, t(lang, "ask_tracking"))
    expect(chat_id, "ship_track", {"order_id": order_id})

def mark_shipped(m, user, lang, order_id, text):
    o = order_by_id(order_id)
    if not can_fulfil(user, m.from_user.id, o) or o.get("status") not in ("paid", "shipped"):
        bot.send_message(m.chat.id, t(lang, "not_allowed"))
        return
    code = text.strip()
    if code == "-":
        code = ""
    if len(code) > 100:
        bot.send_message(m.chat.id, t(lang, "bad_text_len"))
        WAIT[m.chat.id] = {"kind": "ship_track", "extra": {"order_id": order_id}}
        return
    update_order(order_id, status="shipped", tracking_code=code or None, shipped_at=iso_now())
    customer = user_by_id(o["user_id"])
    if customer:
        cl = lang_of(customer)
        track = f"{t(cl, 'tracking_code')}: <code>{esc(code)}</code>" if code else ""
        k = types.InlineKeyboardMarkup()
        k.add(types.InlineKeyboardButton(t(cl, "btn_received"), callback_data=f"rc:{order_id}"))
        notify(customer["telegram_id"], tf(cl, "order_shipped_msg", id=short_id(order_id), track=track), k)
    bot.send_message(m.chat.id, t(lang, "saved"))

def customer_received(chat_id, user, lang, order_id):
    o = order_by_id(order_id)
    if not o or o.get("user_id") != user["id"] or o.get("status") != "shipped":
        bot.send_message(chat_id, t(lang, "already_done"))
        return
    update_order(order_id, status="completed", completed_at=iso_now())
    bot.send_message(chat_id, tf(lang, "order_completed_msg", id=short_id(order_id)))
    for tg, sl in seller_targets(o):
        notify(tg, tf(sl, "buyer_received_msg", id=short_id(order_id)))

def resend_digital(chat_id, user, lang, order_id):
    o = order_by_id(order_id)
    if not o or o.get("user_id") != user["id"] or o.get("payment_status") != "paid" or o.get("status") == "cancelled":
        bot.send_message(chat_id, t(lang, "not_allowed"))
        return
    failed = deliver_order_digital(chat_id, lang, order_items(order_id))
    bot.send_message(chat_id, t(lang, "digital_failed") if failed else t(lang, "redelivered"))

def ask_cancel_order(chat_id, user, tg_id, lang, order_id):
    o = order_by_id(order_id)
    role = order_role(user, tg_id, o) if o else None
    paid = bool(o) and o.get("payment_status") == "paid"
    ok = bool(o) and (
        (role == "customer" and not paid and o.get("status") == "pending") or
        (role in ("seller", "owner") and not paid and o.get("status") == "pending") or
        (role in ("seller", "owner") and paid and o.get("status") == "paid" and o.get("requires_shipping")))
    if not ok:
        bot.send_message(chat_id, t(lang, "not_allowed"))
        return
    q = t(lang, "confirm_refund_q" if (paid and o.get("payment_method") == "stars") else "confirm_cancel_q")
    k = types.InlineKeyboardMarkup()
    k.row(types.InlineKeyboardButton(t(lang, "yes_btn"), callback_data=f"cy:{order_id}"),
          types.InlineKeyboardButton(t(lang, "no_btn"), callback_data=f"od:{order_id}"))
    bot.send_message(chat_id, q, reply_markup=k)

def do_cancel_order(chat_id, user, tg_id, lang, order_id):
    o = order_by_id(order_id)
    role = order_role(user, tg_id, o) if o else None
    if not o or not role:
        bot.send_message(chat_id, t(lang, "not_allowed"))
        return
    customer = user_by_id(o["user_id"])
    cl = lang_of(customer) if customer else "fa"
    short = short_id(order_id)
    items = order_items(order_id)
    if o.get("payment_status") != "paid":
        res = table("orders").update({"status": "cancelled", "cancelled_at": iso_now()}).eq("id", order_id) \
            .eq("payment_status", "unpaid").eq("status", "pending").execute()
        if not res.data:
            bot.send_message(chat_id, t(lang, "already_done"))
            return
        deal = deal_for_order(order_id)
        if deal and deal.get("status") == "open":
            close_deal(deal["id"], "cancelled")
        bot.send_message(chat_id, t(lang, "order_cancelled"))
        if customer and role != "customer":
            notify(customer["telegram_id"], tf(cl, "order_cancelled_by_seller", id=short))
        elif role == "customer":
            for tg, sl in seller_targets(o):
                notify(tg, tf(sl, "order_cancelled_by_buyer", id=short))
        return
    if role == "customer" or not o.get("requires_shipping"):
        bot.send_message(chat_id, t(lang, "not_allowed"))
        return
    # paid, not shipped yet: claim the cancellation first so a double tap can't refund twice
    res = table("orders").update({"status": "cancelled", "cancelled_at": iso_now()}).eq("id", order_id).eq("status", "paid").execute()
    if not res.data:
        bot.send_message(chat_id, t(lang, "already_done"))
        return
    refunded = False
    if o.get("payment_method") == "stars":
        refunded = refund_order_payment(o)
        if not refunded:
            update_order(order_id, status="paid", cancelled_at=None)   # undo, nothing was refunded
            bot.send_message(chat_id, t(lang, "refund_failed"))
            return
        update_order(order_id, payment_status="refunded")
    restore_order_stock(o, items)
    bot.send_message(chat_id, t(lang, "order_refunded" if refunded else "order_cancelled"))
    if customer:
        notify(customer["telegram_id"], tf(cl, "order_cancelled_by_seller", id=short))

# ------------------------------------------------------ shipping wizard
SHIP_PROMPTS = {"ship_name": "ask_ship_name", "ship_phone": "ask_ship_phone",
                "ship_address": "ask_ship_address", "ship_postal": "ask_ship_postal"}

def ask_ship_field(chat_id, lang, kind, extra):
    k = types.InlineKeyboardMarkup()
    k.add(types.InlineKeyboardButton(t(lang, "cancel"), callback_data="ad:x"))
    bot.send_message(chat_id, t(lang, SHIP_PROMPTS[kind]), reply_markup=k)
    WAIT[chat_id] = {"kind": kind, "extra": extra}

def start_shipping(chat_id, user, lang, intent):
    bot.send_message(chat_id, t(lang, "ship_intro"))
    saved = get_address(user["id"])
    if saved:
        ship = ship_from_address_row(saved)
        k = types.InlineKeyboardMarkup()
        k.add(types.InlineKeyboardButton(t(lang, "ship_use"), callback_data="ad:use"))
        k.add(types.InlineKeyboardButton(t(lang, "ship_new"), callback_data="ad:new"))
        k.add(types.InlineKeyboardButton(t(lang, "cancel"), callback_data="ad:x"))
        bot.send_message(chat_id, tf(lang, "ship_saved_q", addr=address_lines(lang, ship)), reply_markup=k)
        WAIT[chat_id] = {"kind": "ship_pick", "extra": {"intent": intent, "ship": ship}}
        return
    ask_ship_field(chat_id, lang, "ship_name", {"intent": intent, "ship": {}})

def handle_ship_input(m, lang, kind, extra, text):
    ship, intent = dict(extra.get("ship") or {}), extra.get("intent")
    text = (text or "").strip()

    def again(err):
        bot.send_message(m.chat.id, t(lang, err))
        WAIT[m.chat.id] = {"kind": kind, "extra": extra}

    if kind == "ship_name":
        if not (3 <= len(text) <= 100):
            return again("bad_name")
        ship["name"] = text
        return ask_ship_field(m.chat.id, lang, "ship_phone", {"intent": intent, "ship": ship})
    if kind == "ship_phone":
        phone = clean_phone(text)
        if not phone:
            return again("bad_phone")
        ship["phone"] = phone
        return ask_ship_field(m.chat.id, lang, "ship_address", {"intent": intent, "ship": ship})
    if kind == "ship_address":
        if not (10 <= len(text) <= 500):
            return again("bad_address")
        ship["address"] = text
        return ask_ship_field(m.chat.id, lang, "ship_postal", {"intent": intent, "ship": ship})
    postal = clean_postal(text)
    if postal is None:
        return again("bad_postal")
    ship["postal"] = postal
    k = types.InlineKeyboardMarkup()
    k.add(types.InlineKeyboardButton(t(lang, "ship_confirm"), callback_data="ad:ok"))
    k.add(types.InlineKeyboardButton(t(lang, "ship_edit"), callback_data="ad:new"))
    k.add(types.InlineKeyboardButton(t(lang, "cancel"), callback_data="ad:x"))
    bot.send_message(m.chat.id, tf(lang, "ship_confirm_q", addr=address_lines(lang, ship)), reply_markup=k)
    WAIT[m.chat.id] = {"kind": "ship_confirm", "extra": {"intent": intent, "ship": ship}}

def ship_callback(chat_id, user, lang, action):
    state = WAIT.get(chat_id)
    if action == "x":
        WAIT.pop(chat_id, None)
        bot.send_message(chat_id, t(lang, "cancelled"))
        return
    if not state or state.get("kind") not in ("ship_pick", "ship_confirm"):
        bot.send_message(chat_id, t(lang, "session_expired"))
        return
    extra = state["extra"]
    intent, ship = extra.get("intent"), extra.get("ship") or {}
    if action == "new":
        ask_ship_field(chat_id, lang, "ship_name", {"intent": intent, "ship": {}})
    elif action == "use" and state["kind"] == "ship_pick":
        WAIT.pop(chat_id, None)
        finish_checkout(chat_id, user, lang, intent, ship)
    elif action == "ok" and state["kind"] == "ship_confirm":
        WAIT.pop(chat_id, None)
        try:
            save_address(user["id"], ship)
        except Exception as e:
            print("save_address failed:", e)
        finish_checkout(chat_id, user, lang, intent, ship)

# ---------------------------------------------------------------- checkout
def resolve_intent(user, intent):
    """-> (ctx, err). Everything is re-read from the DB, so stale buttons can't buy stale data.
    err = (lang_key, format_kwargs)."""
    if intent.get("mode") == "now":
        p = product(intent.get("pid"))
        if not p:
            return None, ("not_found", {})
        shop = shop_by_id(p["shop_id"]) if p.get("shop_id") else None
        method = product_method(p, shop) if shop else "platform"
        lines, item_ids = [(p, 1)], []
    else:
        items = [x for x in cart(user["id"]) if x.get("products")]
        key = f"{intent.get('shop_id') or '0'}:{intent.get('method')}"
        g = next((g for g in group_cart(items) if g["key"] == key), None)
        if not g:
            return None, ("cart_changed", {})
        shop, method = g["shop"], g["method"]
        lines = [(x["products"], int(x["quantity"])) for x in g["items"]]
        item_ids = [x["id"] for x in g["items"]]
    if shop:
        if shop.get("owner_user_id") == user["id"]:
            return None, ("own_product", {})
        if not (shop.get("active") and shop_has_active_sub(shop)):
            return None, ("need_sub", {})
    via = method if shop else intent.get("via")
    for p, q in lines:
        if not p.get("active", True):
            return None, ("item_unavailable", {})
        if via == "stars" and shop and product_price_stars(p) < 1:
            return None, ("item_unavailable", {})
        if is_physical(p):
            stock = int(p.get("stock") or 0)
            if stock <= 0:
                return None, ("out_of_stock_item", {"name": pname(user.get("language") or "fa", p)})
            if stock < q:
                return None, ("stock_limit", {"n": num(user.get("language") or "fa", stock)})
    return {"shop": shop, "lines": lines, "item_ids": item_ids, "via": via, "method": method,
            "needs_ship": any(is_physical(p) for p, _ in lines)}, None

def begin_checkout(chat_id, user, lang, intent):
    ctx, err = resolve_intent(user, intent)
    if err:
        bot.send_message(chat_id, tf(lang, err[0], **err[1]))
        return
    if ctx["method"] == "platform" and not intent.get("via"):
        checkout_menu(chat_id, lang)
        return
    if ctx["needs_ship"]:
        start_shipping(chat_id, user, lang, intent)
        return
    finish_checkout(chat_id, user, lang, intent, None)

def finish_checkout(chat_id, user, lang, intent, ship):
    ctx, err = resolve_intent(user, intent)       # stock may have changed while the address was typed
    if err:
        bot.send_message(chat_id, tf(lang, err[0], **err[1]))
        return
    via = ctx["via"]
    order = create_order_for_lines(user, ctx["shop"], ctx["lines"], via, ship if ctx["needs_ship"] else None)
    if ctx["item_ids"]:
        remove_cart_items(user["id"], ctx["item_ids"])
    if via == "stars":
        send_order_invoice(chat_id, lang, order)
    elif via == "card":
        send_card_instructions(chat_id, lang, order)
    else:
        open_custom_deal(chat_id, user, lang, order, ctx)

def send_order_invoice(chat_id, lang, order, items=None):
    items = items if items is not None else order_items(order["id"])
    short = short_id(order["id"])
    title = trunc(oname(lang, items[0]) if len(items) == 1 else f"{t(lang, 'order_word')} #{short}", 32)
    names = ", ".join(f"{oname(lang, i)} × {i.get('quantity')}" for i in items)
    desc = trunc(tf(lang, "invoice_desc", id=short) + "\n" + names, 250)
    bot.send_invoice(chat_id, title, desc, f"order:{order['id']}", "", "XTR",
                     [types.LabeledPrice(label=title, amount=order_stars_amount(order))])

def send_card_instructions(chat_id, lang, order):
    total = fmt_amount(lang, order.get("total") or 0)
    bot.send_message(chat_id, f"💳 {esc(CARD_NUMBER)}\n👤 {esc(CARD_HOLDER)}\n\nID: {order['id']}\n{t(lang, 'total_word')}: {total}\n{t(lang, 'pay_card')}")
    WAIT[chat_id] = {"kind": "receipt", "extra": {"order_id": order["id"]}}

def open_custom_deal(chat_id, user, lang, order, ctx):
    shop = ctx["shop"]
    seller = user_by_id(shop["owner_user_id"]) if shop else None
    if not seller:
        update_order(order["id"], status="cancelled", cancelled_at=iso_now())
        bot.send_message(chat_id, t(lang, "not_found"))
        return
    qty = sum(q for _, q in ctx["lines"])
    deal = create_order_deal(order, user, seller, ctx["lines"][0][0], qty)
    if not deal:
        update_order(order["id"], status="cancelled", cancelled_at=iso_now())
        bot.send_message(chat_id, t(lang, "not_found"))
        return
    DEAL_CHAT[chat_id] = deal["id"]
    DEAL_CHAT[seller["telegram_id"]] = deal["id"]
    bot.send_message(chat_id, f"#{short_id(order['id'])}\n" + t(lang, "custom_chat_hint"))
    sl = lang_of(seller)
    k = types.InlineKeyboardMarkup()
    k.add(types.InlineKeyboardButton(t(sl, "confirm_paid"), callback_data=f"cf:{deal['id']}"))
    k.add(types.InlineKeyboardButton(t(sl, "cancel_deal"), callback_data=f"cx:{deal['id']}"))
    notify(seller["telegram_id"], seller_order_message(sl, order, order_items(order["id"]), "custom"), k)

def confirm_custom_order(chat_id, lang, deal):
    """Seller says 'paid' for a custom-payment order."""
    order = order_by_id(deal["order_id"])
    if not order:
        return
    claimed = claim_payment(order["id"], None)
    if not claimed:
        bot.send_message(chat_id, t(lang, "already_done"))
        return
    ok, why = finalize_paid_order(claimed, "custom")
    if not ok:
        release_claim(order["id"])
        table("deals").update({"status": "open"}).eq("id", deal["id"]).execute()
        bot.send_message(chat_id, t(lang, "stock_short_confirm") if why == "stock" else t(lang, "err_generic"))
        return
    bot.send_message(chat_id, t(lang, "approved"))

def checkout_entry(chat_id, user, lang):
    items = [x for x in cart(user["id"]) if x.get("products")]
    groups = group_cart(items)
    if len(groups) == 1:
        g = groups[0]
        begin_checkout(chat_id, user, lang, {"mode": "cart", "shop_id": g["shop_id"], "method": g["method"]})
    else:
        show_cart(chat_id, user, lang)


@bot.message_handler(commands=["start"])
def start(m):
    try:
        user = get_user(m.from_user)
    except Exception as e:
        print("start/get_user failed:", e)
        bot.send_message(m.chat.id, t("fa", "db_error") + "\n" + t("en", "db_error"))
        return
    arg = ""
    parts = (m.text or "").split(maxsplit=1)
    if len(parts) > 1:
        arg = parts[1].strip()
    if arg.startswith("shop_"):
        PENDING_SHOP[m.chat.id] = arg.split("shop_", 1)[1]
    WAIT.pop(m.chat.id, None)   # /start always leaves any half-finished form
    if not user.get("language_set"):
        ask_language(m.chat.id)
        return
    continue_onboarding(m.chat.id, user, m.from_user.id)

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
        bot.answer_callback_query(c.id, t("fa", "db_error_alert") + " / " + t("en", "db_error_alert"), show_alert=True)
        return
    lang = lang_of(user)
    data = c.data or ""
    bot.answer_callback_query(c.id)
    if data.startswith("lang_"):
        if data[-2:] in ("fa", "en"):
            set_language(user["id"], data[-2:])
        user = get_user(c.from_user)
        continue_onboarding(c.message.chat.id, user, c.from_user.id)
        return
    if data.startswith("panel_"):
        choice = data.split("_", 1)[1]
        if choice == "owner" and not is_owner(c.from_user.id):
            bot.send_message(c.message.chat.id, t(lang, "admin_only"))
            return
        if choice == "admin":
            trial = accept_admin(user)
            note = t(lang, "trial") if trial else t(lang, "trial_used")
            bot.send_message(c.message.chat.id, t(lang, "accepted_admin") + "\n" + note)
        elif choice == "customer":
            set_panel(c.from_user.id, "customer")
        else:
            set_panel(c.from_user.id, "owner")
        user = get_user(c.from_user)
        open_pending_or_home(c.message.chat.id, user, c.from_user.id)
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
        if is_owner(c.from_user.id):
            claimed = claim_payment(data.split(":", 1)[1], "CARD_TRANSFER")
            if claimed:
                finalize_paid_order(claimed, "card")
                bot.send_message(c.message.chat.id, t(lang, "approved"))
            else:
                bot.send_message(c.message.chat.id, t(lang, "already_done"))
        else:
            bot.send_message(c.message.chat.id, t(lang, "not_allowed"))
        return
    if data.startswith("spm:"):
        shop = my_shop(user["id"])
        if shop:
            set_shop_pay_method(shop["id"], data.split(":", 1)[1])
            bot.send_message(c.message.chat.id, t(lang, "method_saved"))
        return
    if data.startswith("pt:"):
        state = WAIT.get(c.message.chat.id) or {}
        if state.get("kind") != "prod_type":
            bot.send_message(c.message.chat.id, t(lang, "session_expired"))
            return
        extra = state.get("extra") or {}
        draft = extra.get("draft") or {}
        draft["product_type"] = "physical" if data.split(":", 1)[1] == "physical" else "digital"
        k = types.InlineKeyboardMarkup()
        k.add(types.InlineKeyboardButton(t(lang, "method_stars"), callback_data="pm:stars"))
        k.add(types.InlineKeyboardButton(t(lang, "method_custom"), callback_data="pm:custom"))
        bot.send_message(c.message.chat.id, t(lang, "ask_method"), reply_markup=k)
        WAIT[c.message.chat.id] = {"kind": "prod_method", "extra": {"draft": draft, "shop_id": extra.get("shop_id")}}
        return
    if data.startswith("pm:"):
        state = WAIT.get(c.message.chat.id) or {}
        if state.get("kind") != "prod_method":
            bot.send_message(c.message.chat.id, t(lang, "session_expired"))
            return
        draft = (state.get("extra") or {}).get("draft") or {}
        draft["pay_method"] = "stars" if data.split(":", 1)[1] == "stars" else "custom"
        shop_id = (state.get("extra") or {}).get("shop_id")
        if draft["pay_method"] == "stars":
            bot.send_message(c.message.chat.id, t(lang, "ask_stars"))
            expect(c.message.chat.id, "prod_stars", {"draft": draft, "shop_id": shop_id})
        else:
            product_next_step(c.message.chat.id, lang, draft, shop_id)
        return
    if data.startswith("rv:") or data.startswith("rp:"):
        kind = "review" if data.startswith("rv:") else "report"
        pid = data.split(":", 1)[1]
        ok, why = feedback_gate(kind, pid, user)
        if not ok:
            bot.send_message(c.message.chat.id, t(lang, why))
            return
        expect(c.message.chat.id, kind, {"product_id": pid})
        bot.send_message(c.message.chat.id, t(lang, "ask_review" if kind == "review" else "ask_report"))
        return
    if data.startswith("by:"):
        start_buy(c.message.chat.id, user, lang, data.split(":", 1)[1])
        return
    if data.startswith("cf:"):
        confirm_deal(c, data.split(":", 1)[1])
        return
    if data.startswith("cx:"):
        cancel_deal(c, user, lang, data.split(":", 1)[1])
        return
    chat_id = c.message.chat.id
    if data.startswith("co:"):
        _, sid, method = data.split(":", 2)
        begin_checkout(chat_id, user, lang, {"mode": "cart", "shop_id": None if sid == "0" else sid, "method": method})
        return
    if data.startswith("qp:") or data.startswith("qm:"):
        res = change_cart_qty(user["id"], data[3:], 1 if data.startswith("qp:") else -1)
        if res == "limit":
            bot.send_message(chat_id, tf(lang, "stock_limit", n=num(lang, MAX_CART_QTY)))
        show_cart(chat_id, user, lang, edit_message=c.message)
        return
    if data.startswith("ad:"):
        ship_callback(chat_id, user, lang, data.split(":", 1)[1])
        return
    if data.startswith("od:"):
        show_order(chat_id, user, c.from_user.id, lang, data.split(":", 1)[1])
        return
    if data.startswith("ol:"):
        show_manage_orders(chat_id, user, c.from_user.id, lang, data.split(":", 1)[1])
        return
    if data.startswith("sg:"):
        start_tracking(chat_id, user, c.from_user.id, lang, data.split(":", 1)[1])
        return
    if data.startswith("rc:"):
        customer_received(chat_id, user, lang, data.split(":", 1)[1])
        return
    if data.startswith("rd:"):
        resend_digital(chat_id, user, lang, data.split(":", 1)[1])
        return
    if data.startswith("po:"):
        pay_order_again(chat_id, user, lang, data.split(":", 1)[1])
        return
    if data.startswith("cn:"):
        ask_cancel_order(chat_id, user, c.from_user.id, lang, data.split(":", 1)[1])
        return
    if data.startswith("cy:"):
        do_cancel_order(chat_id, user, c.from_user.id, lang, data.split(":", 1)[1])
        return
    if data.startswith(("mp:", "ms:", "mr:", "mx:")):
        product_admin_action(chat_id, user, c.from_user.id, lang, data[:2], data[3:])
        return
    if data.startswith("sh:"):
        show_shop(c.message.chat.id, user, c.from_user.id, data.split(":", 1)[1])
    elif data.startswith("pr:"):
        show_product(c.message.chat.id, lang, data.split(":", 1)[1])
    elif data.startswith("add:"):
        add_to_cart_msg(chat_id, user, lang, data.split(":", 1)[1])
    elif data == "cart":
        show_cart(c.message.chat.id, user, lang)
    elif data.startswith("rm:"):
        remove_cart(user["id"], data.split(":", 1)[1])
        show_cart(c.message.chat.id, user, lang, edit_message=c.message)
    elif data == "checkout":
        checkout_entry(c.message.chat.id, user, lang)
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
        show_owner_shop(c.message.chat.id, user, c.from_user.id, lang, data.split(":", 1)[1])
    elif data.startswith("ds:"):
        # delete shop confirm
        shop_id = data.split(":", 1)[1]
        k = types.InlineKeyboardMarkup()
        k.row(types.InlineKeyboardButton(t(lang, "yes_btn"), callback_data=f"dxy:{shop_id}"),
              types.InlineKeyboardButton(t(lang, "no_btn"), callback_data="home"))
        bot.send_message(c.message.chat.id, t(lang, "confirm_delete_shop"), reply_markup=k)
    elif data.startswith("dxy:"):
        shop_id = data.split(":", 1)[1]
        shop = shop_by_id(shop_id)
        if shop and (is_owner(c.from_user.id) or (my_shop(user["id"]) and my_shop(user["id"])["id"] == shop_id)):
            deactivate_shop(shop_id)
            bot.send_message(c.message.chat.id, t(lang, "shop_deleted"))
        else:
            bot.send_message(c.message.chat.id, t(lang, "not_allowed"))
    elif data.startswith("sc:"):
        shop_id = data.split(":", 1)[1]
        bot.send_message(c.message.chat.id, t(lang, "send_channel"))
        expect(c.message.chat.id, "shop_channel", {"shop_id": shop_id})
    elif data.startswith("cc:"):
        shop_id = data.split(":", 1)[1]
        clear_shop_channel(shop_id)
        bot.send_message(c.message.chat.id, t(lang, "channel_cleared"))
    elif data == "sub:cancel":
        cancel_subscription(user["id"])
        bot.send_message(c.message.chat.id, t(lang, "saved"))
    elif data.startswith("sup:"):
        target = data.split(":", 1)[1]
        WAIT[c.message.chat.id] = {"kind": "support", "extra": {"target": target, "user": user}}
        bot.send_message(c.message.chat.id, t(lang, "ticket"))

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
        extra = ""
        try:
            by_cur = revenue_by_currency()
            if by_cur.get("XTR"):
                extra += f"\n⭐ {t(lang, 'revenue_stars')}: {fmt_amount(lang, by_cur['XTR'])}"
            others = sum(v for k2, v in by_cur.items() if k2 not in ("XTR", "CUSTOM"))
            if others:
                extra += f"\n{t(lang, 'revenue_other')}: {fmt_amount(lang, others)}"
            extra += f"\n🚚 {t(lang, 'to_ship_count')}: {num(lang, count_to_ship())}"
        except Exception as e:
            print("revenue breakdown:", e)
        bot.send_message(chat_id, f"{t(lang, 'revenue')}\n{t(lang, 'orders_word')}: {data['orders']}\n{t(lang, 'total_word')}: {data['revenue']}\n{t(lang, 'active_subs')}: {len(subs)}" + extra)
    elif action == "stats":
        lines = admin_sales()
        text = t(lang, "admin_stats") + "\n" + ("\n".join(
            [f"{esc(x['shop'])} | {x['admin']} | {t(lang, 'qty_word')} {x['orders']} | {x['total']} | {t(lang, 'sub_active') if x['sub'] == 'active' else t(lang, 'sub_inactive')}" for x in lines]
        ) or "-")
        bot.send_message(chat_id, text[:4000])
    elif action == "shops":
        rows = [s for s in all_shops() if s.get("active", True)]
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
    elif action == "orders":
        show_manage_orders(chat_id, user, c.from_user.id, lang)
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
    if action not in ("sub", "renew", "method", "orders") and not active_subscription(user["id"]) and not is_owner(user.get("telegram_id")):
        bot.send_message(chat_id, "⛔ " + t(lang, "sub_expired"))
        seller_action(c, user, lang, "renew")
        return
    shop = my_shop(user["id"])
    if action == "shop":
        if not shop:
            bot.send_message(chat_id, t(lang, "send_shop"))
            expect(chat_id, "create_shop", {"user": user})
            return
        k = types.InlineKeyboardMarkup()
        k.add(types.InlineKeyboardButton(t(lang, "delete_shop"), callback_data=f"ds:{shop['id']}"))
        bot.send_message(chat_id, f"{esc(shop['title'])}\n{t(lang, 'link')}: {bot_link(shop['id'])}", reply_markup=k)
    elif action == "products":
        if not shop:
            bot.send_message(chat_id, t(lang, "send_shop"))
            return
        rows = shop_products(shop["id"])
        lines = []
        for p in rows:
            stock = f" · {t(lang, 'stock_label')}: {num(lang, int(p.get('stock') or 0))}" if is_physical(p) else ""
            lines.append(f"• {esc(pname(lang, p))} — {type_short_of(lang, p)} — {t(lang, 'method_' + (p.get('pay_method') or 'stars'))}{stock}")
        k = types.InlineKeyboardMarkup()
        k.add(types.InlineKeyboardButton(t(lang, "add_product_btn"), callback_data="sel:newprod"))
        for p in rows[:20]:
            k.add(types.InlineKeyboardButton("⚙️ " + trunc(pname(lang, p), 40), callback_data=f"mp:{p['id']}"))
        bot.send_message(chat_id, (t(lang, "my_products") + "\n" + "\n".join(lines or ["-"]))[:4000], reply_markup=k)
    elif action == "newprod":
        if not shop:
            bot.send_message(chat_id, t(lang, "send_shop"))
            return
        bot.send_message(chat_id, t(lang, "ask_name_fa"))
        expect(chat_id, "prod_name_fa", {"shop_id": shop["id"], "draft": {}})
    elif action == "orders":
        show_manage_orders(chat_id, user, c.from_user.id, lang)
    elif action == "method":
        if not shop:
            bot.send_message(chat_id, t(lang, "send_shop"))
            return
        k = types.InlineKeyboardMarkup()
        k.add(types.InlineKeyboardButton(t(lang, "method_stars"), callback_data="spm:stars"))
        k.add(types.InlineKeyboardButton(t(lang, "method_custom"), callback_data="spm:custom"))
        bot.send_message(chat_id, t(lang, "pay_method") + f": {shop.get('pay_method') or 'stars'}", reply_markup=k)
    elif action == "sub":
        sub = active_subscription(user["id"])
        k = types.InlineKeyboardMarkup()
        k.add(types.InlineKeyboardButton(t(lang, "renew"), callback_data="sel:renew"))
        k.add(types.InlineKeyboardButton(t(lang, "cancel_sub"), callback_data="sub:cancel"))
        text = t(lang, "my_sub") + "\n" + (f"{t(lang, 'sub_active')} {fmt_date(lang, sub['ends_at'])}" if sub else t(lang, "sub_inactive"))
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
        curr = shop.get("required_channel_username") or shop.get("required_channel_id") or ""
        text = t(lang, "current_channel") + " " + (curr or t(lang, "no_channel"))
        k = types.InlineKeyboardMarkup()
        k.add(types.InlineKeyboardButton(t(lang, "set_channel"), callback_data=f"sc:{shop['id']}"))
        if curr:
            k.add(types.InlineKeyboardButton(t(lang, "clear_channel"), callback_data=f"cc:{shop['id']}"))
        bot.send_message(chat_id, text, reply_markup=k)
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
        if product_method(p, shop) == "stars":
            price = f"{num(lang, product_price_stars(p))} ⭐"
        else:
            price = t(lang, "custom_price")
        if is_physical(p) and int(p.get("stock") or 0) <= 0:
            price = t(lang, "out_of_stock")
        icon = "📦" if is_physical(p) else "💾"
        k.add(types.InlineKeyboardButton(trunc(f"{icon} {pname(lang, p)} — {price}", 60), callback_data=f"pr:{p['id']}"))
    k.add(types.InlineKeyboardButton(t(lang, "back"), callback_data="home"))
    bot.send_message(chat_id, esc(shop["title"]), reply_markup=k)

def show_shop_products_text(chat_id, shop_id, lang="fa"):
    shop = shop_by_id(shop_id)
    if not shop:
        bot.send_message(chat_id, t(lang, "not_found"))
        return
    lines = [f"• {esc(pname(lang, p))} — {product_price_stars(p) or p.get('price')}" for p in shop_products(shop_id)]
    bot.send_message(chat_id, f"{esc(shop['title'])}\n" + ("\n".join(lines) or "-"))

def show_owner_shop(chat_id, user, tg_id, lang, shop_id):
    if not is_owner(tg_id):
        bot.send_message(chat_id, t(lang, "admin_only"))
        return
    shop = shop_by_id(shop_id)
    if not shop or not shop.get("active", True):
        bot.send_message(chat_id, t(lang, "not_found"))
        return
    text = f"<b>{esc(shop['title'])}</b>\nOwner: {shop.get('owner_user_id')}\n{t(lang, 'link')}: {bot_link(shop['id'])}"
    k = types.InlineKeyboardMarkup()
    k.add(types.InlineKeyboardButton(t(lang, "delete_shop"), callback_data=f"ds:{shop_id}"))
    for p in shop_products(shop_id)[:15]:
        k.add(types.InlineKeyboardButton("🗑 " + trunc(pname(lang, p), 30), callback_data=f"mp:{p['id']}"))
    k.add(types.InlineKeyboardButton(t(lang, "back"), callback_data="own:shops"))
    bot.send_message(chat_id, text, reply_markup=k)

def type_short_of(lang, p):
    return t(lang, "type_physical_short" if is_physical(p) else "type_digital_short")

def show_product(chat_id, lang, pid):
    p = product(pid)
    if not p or not p.get("active", True):
        bot.send_message(chat_id, t(lang, "not_found"))
        return
    shop = shop_by_id(p.get("shop_id")) if p.get("shop_id") else None
    method = product_method(p, shop)
    price = f"{num(lang, product_price_stars(p))} ⭐" if method == "stars" else t(lang, "custom_price")
    available = True
    lines = [f"<b>{esc(pname(lang, p))}</b>", "",
             f"{t(lang, 'type_label')}: {type_short_of(lang, p)} ({t(lang, 'ship_by_post') if is_physical(p) else t(lang, 'digital_auto')})",
             f"{t(lang, 'price_label')}: {price}"]
    if is_physical(p):
        stock = int(p.get("stock") or 0)
        available = stock > 0
        lines.append(f"{t(lang, 'stock_label')}: {num(lang, stock) if stock > 0 else t(lang, 'out_of_stock')}")
    desc = trunc(pdesc(lang, p), 300)
    if desc:
        lines += ["", esc(desc)]
    text = "\n".join(lines) + "\n\n" + feedback_text(lang, pid)
    k = types.InlineKeyboardMarkup()
    if available:
        k.row(types.InlineKeyboardButton(t(lang, "add_to_cart"), callback_data=f"add:{pid}"),
              types.InlineKeyboardButton(t(lang, "buy"), callback_data=f"by:{pid}"))
    k.add(types.InlineKeyboardButton(t(lang, "good_product"), callback_data=f"rv:{pid}"))
    k.add(types.InlineKeyboardButton(t(lang, "report_product"), callback_data=f"rp:{pid}"))
    send_banner(chat_id, p, text, k)

def feedback_text(lang, pid):
    reviews, reports = product_feedback(pid)
    rlines = "\n".join([f"• {esc(trunc(x.get('comment'), 120))}" for x in reviews if x.get("comment")]) or t(lang, "no_reviews")
    plines = "\n".join([f"• {esc(trunc(x.get('reason'), 120))}" for x in reports if x.get("reason")]) or t(lang, "no_reports")
    return f"{t(lang, 'reviews')} ({num(lang, len(reviews))})\n{rlines}\n\n{t(lang, 'reports')} ({num(lang, len(reports))})\n{plines}"

def send_banner(chat_id, p, text, markup=None):
    fid = p.get("banner_file_id")
    kind = p.get("banner_type")
    long_text = len(text) > 1000          # Telegram caption limit is 1024
    cap = None if long_text else text
    mk = None if long_text else markup
    try:
        if fid and kind == "photo":
            bot.send_photo(chat_id, fid, caption=cap, reply_markup=mk)
        elif fid and kind == "video":
            bot.send_video(chat_id, fid, caption=cap, reply_markup=mk)
        elif fid:
            bot.send_document(chat_id, fid, caption=cap, reply_markup=mk)
        else:
            bot.send_message(chat_id, text, reply_markup=markup)
            return
        if long_text:
            bot.send_message(chat_id, text, reply_markup=markup)
    except Exception:
        bot.send_message(chat_id, text, reply_markup=markup)

def start_buy(chat_id, user, lang, pid):
    p = product(pid)
    if not p or not p.get("active", True):
        bot.send_message(chat_id, t(lang, "not_found"))
        return
    shop = shop_by_id(p.get("shop_id")) if p.get("shop_id") else None
    if not shop:                      # shop-less (platform) product: goes through the cart
        add_to_cart_msg(chat_id, user, lang, pid)
        return
    # payment method is decided by the seller (Stars or custom); one order per seller
    begin_checkout(chat_id, user, lang, {"mode": "now", "pid": pid, "shop_id": shop["id"], "method": product_method(p, shop)})

def confirm_deal(c, deal_id):
    deal = deal_by_id(deal_id)
    if not deal:
        return
    actor = get_user(c.from_user)
    lang = lang_of(actor)
    if not (is_owner(c.from_user.id) or actor["id"] == deal.get("seller_id")):
        bot.send_message(c.message.chat.id, t(lang, "not_allowed"))
        return
    if not claim_deal(deal_id, "paid"):          # a second tap must never deliver twice
        bot.send_message(c.message.chat.id, t(lang, "already_done"))
        return
    customer = one("users", {"id": deal["customer_id"]})
    if deal.get("order_id"):
        confirm_custom_order(c.message.chat.id, lang, deal)
    else:                                         # legacy deal without an order
        p = product(deal["product_id"])
        if customer and p:
            deliver_product(customer["telegram_id"], p)
            bot.send_message(customer["telegram_id"], t(lang_of(customer), "delivered"))
        bot.send_message(c.message.chat.id, t(lang, "approved"))
    DEAL_CHAT.pop(c.message.chat.id, None)
    if customer:
        DEAL_CHAT.pop(customer["telegram_id"], None)

def cancel_deal(c, user, lang, deal_id):
    deal = deal_by_id(deal_id)
    if not deal or not (is_owner(c.from_user.id) or user["id"] in (deal.get("seller_id"), deal.get("customer_id"))):
        bot.send_message(c.message.chat.id, t(lang, "not_allowed"))
        return
    if not claim_deal(deal_id, "cancelled"):
        bot.send_message(c.message.chat.id, t(lang, "already_done"))
        return
    if deal.get("order_id"):
        table("orders").update({"status": "cancelled", "cancelled_at": iso_now()}).eq("id", deal["order_id"]) \
            .eq("payment_status", "unpaid").eq("status", "pending").execute()
        other_id = deal["customer_id"] if user["id"] == deal.get("seller_id") else deal.get("seller_id")
        other = user_by_id(other_id) if other_id and other_id != user["id"] else None
        if other:
            key = "order_cancelled_by_seller" if user["id"] == deal.get("seller_id") else "order_cancelled_by_buyer"
            notify(other["telegram_id"], tf(lang_of(other), key, id=short_id(deal["order_id"])))
    for uid in (deal.get("customer_id"), deal.get("seller_id")):
        row = user_by_id(uid)
        if row:
            DEAL_CHAT.pop(row["telegram_id"], None)
    bot.send_message(c.message.chat.id, t(lang, "saved"))

def deliver_product(chat_id, p):
    fid = p.get("product_file_id")
    kind = p.get("product_file_type")
    if fid and kind == "photo":
        bot.send_photo(chat_id, fid)
    elif fid and kind == "video":
        bot.send_video(chat_id, fid)
    elif fid:
        bot.send_document(chat_id, fid)
    elif p.get("digital_content"):
        bot.send_message(chat_id, esc(p["digital_content"]))   # delivered literally (no HTML surprises)

def relay_deal(m):
    deal_id = DEAL_CHAT.get(m.chat.id)
    deal = deal_by_id(deal_id) if deal_id else None
    if not deal:                      # memory lost after a restart: fall back to the database
        me = one("users", {"telegram_id": m.from_user.id})
        deal = open_deal_for_user(me["id"]) if me else None
        if deal:
            DEAL_CHAT[m.chat.id] = deal["id"]
    if not deal or deal.get("status") != "open":
        DEAL_CHAT.pop(m.chat.id, None)
        return False
    customer = one("users", {"id": deal["customer_id"]})
    seller = one("users", {"id": deal["seller_id"]})
    if not customer or not seller:
        return False
    from_customer = m.from_user.id == customer["telegram_id"]
    target_row = seller if from_customer else customer
    target = target_row["telegram_id"]
    label = t(lang_of(target_row), "from_customer" if from_customer else "from_seller")
    bot.send_message(target, f"{label} #{short_id(deal['id'])}:")
    try:
        bot.copy_message(target, m.chat.id, m.message_id)
    except Exception:
        bot.send_message(target, esc(m.text or m.caption or ""))
    return True

def send_or_edit(chat_id, text, markup, edit_message=None):
    if edit_message is not None:
        try:
            bot.edit_message_text(text, chat_id, edit_message.message_id, reply_markup=markup)
            return
        except Exception as e:
            if "not modified" in str(e):
                return
    bot.send_message(chat_id, text, reply_markup=markup)

def add_to_cart_msg(chat_id, user, lang, pid):
    status, _ = add_to_cart(user, pid)
    if status == "ok":
        k = types.InlineKeyboardMarkup()
        k.add(types.InlineKeyboardButton(t(lang, "view_cart"), callback_data="cart"))
        bot.send_message(chat_id, "✅ " + t(lang, "added"), reply_markup=k)
        return
    p = product(pid) if status == "limit" else None
    msg = {"not_found": t(lang, "not_found"), "unavailable": t(lang, "item_unavailable"),
           "own": t(lang, "own_product"), "out": t(lang, "item_unavailable"),
           "digital_once": t(lang, "digital_once"),
           "limit": tf(lang, "stock_limit", n=num(lang, max_qty(p) if p else MAX_CART_QTY))}.get(status, t(lang, "err_generic"))
    bot.send_message(chat_id, msg)

def show_cart(chat_id, user, lang, edit_message=None):
    live = []
    for x in cart(user["id"]):
        p = x.get("products")
        if not p or not p.get("active", True):
            remove_cart(user["id"], x["id"])
            continue
        live.append(x)
    if not live:
        send_or_edit(chat_id, t(lang, "empty_cart"), None, edit_message)
        return
    lines = [f"🛒 <b>{t(lang, 'cart_title')}</b>"]
    k = types.InlineKeyboardMarkup()
    for g in group_cart(live):
        title = esc(g["shop"]["title"]) if g["shop"] else t(lang, "main_store")
        lines.append(f"\n🏪 <b>{title}</b>")
        for x in g["items"]:
            p, q = x["products"], int(x["quantity"])
            if g["method"] == "stars":
                price = f"{fmt_amount(lang, unit_price(p, 'stars') * q)} ⭐"
            elif g["method"] == "custom":
                price = t(lang, "custom_in_chat")
            else:
                price = money(lang, unit_price(p, "platform") * q, "IRT")
            lines.append(f"• {esc(pname(lang, p))} × {num(lang, q)} ({type_short_of(lang, p)}) — {price}")
            k.row(types.InlineKeyboardButton("➖", callback_data=f"qm:{x['id']}"),
                  types.InlineKeyboardButton(trunc(f"❌ {pname(lang, p)} × {num(lang, q)}", 40), callback_data=f"rm:{x['id']}"),
                  types.InlineKeyboardButton("➕", callback_data=f"qp:{x['id']}"))
        if g["method"] == "custom":
            lines.append(f"{t(lang, 'total_word')}: {t(lang, 'custom_in_chat')}")
        else:
            cur = "XTR" if g["method"] == "stars" else "IRT"
            lines.append(f"{t(lang, 'total_word')}: {money(lang, group_total(g), cur)}")
        k.add(types.InlineKeyboardButton(trunc(tf(lang, "checkout_shop", shop=g["shop"]["title"] if g["shop"] else t(lang, "main_store")), 60),
                                         callback_data=f"co:{g['shop_id'] or '0'}:{g['method']}"))
    send_or_edit(chat_id, "\n".join(lines), k, edit_message)

def checkout_menu(chat_id, lang):
    k = types.InlineKeyboardMarkup()
    k.add(types.InlineKeyboardButton(t(lang, "stars"), callback_data="pay:stars"))
    k.add(types.InlineKeyboardButton(t(lang, "card"), callback_data="pay:card"))
    bot.send_message(chat_id, t(lang, "payment"), reply_markup=k)

def create_and_pay(chat_id, user, lang, method):
    # platform (shop-less) products only: the customer picked Stars or bank transfer
    begin_checkout(chat_id, user, lang, {"mode": "cart", "shop_id": None, "method": "platform",
                                         "via": "card" if method == "card" else "stars"})

def pay_order_again(chat_id, user, lang, order_id):
    o = order_by_id(order_id)
    if not o or o.get("user_id") != user["id"] or o.get("status") != "pending" or o.get("payment_status") != "unpaid":
        bot.send_message(chat_id, t(lang, "not_allowed"))
        return
    if o.get("payment_method") == "stars":
        send_order_invoice(chat_id, lang, o)
    elif o.get("payment_method") == "card":
        send_card_instructions(chat_id, lang, o)

def product_next_step(chat_id, lang, draft, shop_id):
    """After the price step: physical -> stock, digital -> the file/code itself."""
    if draft.get("product_type") == "physical":
        bot.send_message(chat_id, t(lang, "ask_stock"))
        expect(chat_id, "prod_stock", {"draft": draft, "shop_id": shop_id})
    else:
        bot.send_message(chat_id, t(lang, "ask_file"))
        expect(chat_id, "prod_file", {"draft": draft, "shop_id": shop_id})

def product_admin_action(chat_id, user, tg_id, lang, kind, pid):
    p = product(pid)
    shop = my_shop(user["id"])
    if not p or not (is_owner(tg_id) or (shop and p.get("shop_id") == shop["id"])):
        bot.send_message(chat_id, t(lang, "not_allowed"))
        return
    if kind == "mp":
        stock = f"\n{t(lang, 'stock_label')}: {num(lang, int(p.get('stock') or 0))}" if is_physical(p) else ""
        k = types.InlineKeyboardMarkup()
        if is_physical(p):
            k.add(types.InlineKeyboardButton(t(lang, "edit_stock"), callback_data=f"ms:{pid}"))
        k.add(types.InlineKeyboardButton(t(lang, "remove_product"), callback_data=f"mr:{pid}"))
        bot.send_message(chat_id, f"<b>{esc(pname(lang, p))}</b>\n{type_short_of(lang, p)}{stock}", reply_markup=k)
    elif kind == "ms" and is_physical(p):
        bot.send_message(chat_id, t(lang, "ask_new_stock"))
        expect(chat_id, "stock_edit", {"product_id": pid})
    elif kind == "mr":
        k = types.InlineKeyboardMarkup()
        k.row(types.InlineKeyboardButton(t(lang, "yes_btn"), callback_data=f"mx:{pid}"),
              types.InlineKeyboardButton(t(lang, "no_btn"), callback_data=f"mp:{pid}"))
        bot.send_message(chat_id, t(lang, "confirm_remove_q"), reply_markup=k)
    elif kind == "mx":
        deactivate_product(pid)
        bot.send_message(chat_id, t(lang, "product_removed"))

def pay_plan(chat_id, user, plan_id):
    lang = lang_of(user)
    plan = plan_by_id(plan_id)
    if not plan:
        bot.send_message(chat_id, t(lang, "plan_missing"))
        return
    shop = my_shop(user["id"])
    shop_id = shop["id"] if shop else "none"
    title = trunc(plan["name_fa"] if lang == "fa" else plan["name_en"], 32)
    prices = [types.LabeledPrice(label=title, amount=max(1, int(plan["stars"])))]
    bot.send_invoice(chat_id, title, t(lang, "invoice_plan_desc"), f"plan:{plan['id']}:{user['id']}:{shop_id}", "", "XTR", prices)

def show_orders(chat_id, user):
    lang = lang_of(user)
    rows = [o for o in customer_orders(user["id"]) if o.get("status") != "draft"]
    if not rows:
        bot.send_message(chat_id, t(lang, "no_orders"))
        return
    k = types.InlineKeyboardMarkup()
    for o in rows[:10]:
        label = f"{order_status_label(lang, o)} #{short_id(o['id'])} · {money(lang, o.get('total') or 0, o.get('currency') or 'IRT')}"
        k.add(types.InlineKeyboardButton(trunc(label, 60), callback_data=f"od:{o['id']}"))
    bot.send_message(chat_id, f"<b>{t(lang, 'orders')}</b>", reply_markup=k)

def file_from_message(m):
    if m.photo:
        return m.photo[-1].file_id, "photo"
    if m.video:
        return m.video.file_id, "video"
    if m.document:
        return m.document.file_id, "document"
    if m.animation:
        return m.animation.file_id, "animation"
    return None, None

def parse_channel(text):
    parts = [x.strip() for x in text.split("|")]
    username = parts[0].lstrip("@") if parts else ""
    channel_id = parts[1] if len(parts) > 1 else username
    return channel_id, username

def on_text(m):
    state = WAIT.pop(m.chat.id, None)
    if not state:
        handle_menu(m)
        return
    if is_exact_menu_text(m.text or ""):
        handle_menu(m)
        return
    user = get_user(m.from_user)
    lang = lang_of(user)
    kind = state["kind"]
    text = m.text or m.caption or ""
    try:
        if kind == "add_admin":
            row = set_user_role(int(text.strip()), "admin")
            bot.send_message(m.chat.id, t(lang, "saved") if row else t(lang, "not_found"))
        elif kind in ("review", "report"):
            body = text.strip()
            if not (3 <= len(body) <= 500):
                bot.send_message(m.chat.id, t(lang, "bad_text_len"))
                WAIT[m.chat.id] = state
                return
            pid = state["extra"]["product_id"]
            if kind == "review":
                ok, why = submit_review(pid, user, body)
                bot.send_message(m.chat.id, t(lang, "review_saved") if ok else t(lang, why))
            else:
                ok, why = submit_report(pid, user, body)
                bot.send_message(m.chat.id, t(lang, "report_saved") if ok else t(lang, why))
                if ok:
                    prod = product(pid) or {}
                    for tg in owner_ids():
                        ol = lang_of_tg(tg)
                        notify(tg, tf(ol, "report_alert", name=esc(pname(ol, prod)), reason=esc(trunc(body, 300))))
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
            bot.send_message(m.chat.id, t(lang, "add_product_btn"))
        elif kind == "prod_name_fa":
            draft = state["extra"].get("draft") or {}
            draft["name_fa"] = text.strip()
            bot.send_message(m.chat.id, t(lang, "ask_name_en"))
            expect(m.chat.id, "prod_name_en", {"draft": draft, "shop_id": state["extra"].get("shop_id")})
        elif kind == "prod_name_en":
            draft = state["extra"].get("draft") or {}
            draft["name_en"] = draft["name_fa"] if text.strip() == "-" else text.strip()
            bot.send_message(m.chat.id, t(lang, "ask_desc"))
            expect(m.chat.id, "prod_desc", {"draft": draft, "shop_id": state["extra"].get("shop_id")})
        elif kind == "prod_desc":
            draft = state["extra"].get("draft") or {}
            draft["description"] = None if text.strip() in ("-", "") else text.strip()[:1500]
            bot.send_message(m.chat.id, t(lang, "ask_banner"))
            expect(m.chat.id, "prod_banner", {"draft": draft, "shop_id": state["extra"].get("shop_id")})
        elif kind == "prod_banner":
            draft = state["extra"].get("draft") or {}
            fid, ftype = file_from_message(m)
            draft["banner_file_id"] = fid
            draft["banner_type"] = ftype
            k = types.InlineKeyboardMarkup()
            k.add(types.InlineKeyboardButton(t(lang, "type_digital"), callback_data="pt:digital"))
            k.add(types.InlineKeyboardButton(t(lang, "type_physical"), callback_data="pt:physical"))
            bot.send_message(m.chat.id, t(lang, "ask_type"), reply_markup=k)
            WAIT[m.chat.id] = {"kind": "prod_type", "extra": {"draft": draft, "shop_id": state["extra"].get("shop_id")}}
        elif kind == "prod_stars":
            draft = state["extra"].get("draft") or {}
            digits = to_ascii_digits(text).strip()
            if not digits.isdigit() or int(digits) < 1:
                bot.send_message(m.chat.id, t(lang, "bad_number"))
                WAIT[m.chat.id] = state
                return
            draft["stars_price"] = int(digits)
            product_next_step(m.chat.id, lang, draft, state["extra"].get("shop_id"))
        elif kind == "prod_stock":
            draft = state["extra"].get("draft") or {}
            digits = to_ascii_digits(text).strip()
            if not digits.isdigit() or int(digits) > 1000000:
                bot.send_message(m.chat.id, t(lang, "bad_number"))
                WAIT[m.chat.id] = state
                return
            draft["stock"] = int(digits)
            add_shop_product(state["extra"].get("shop_id"), draft)
            bot.send_message(m.chat.id, t(lang, "product_saved"))
        elif kind == "stock_edit":
            digits = to_ascii_digits(text).strip()
            pid = state["extra"]["product_id"]
            shop = my_shop(user["id"])
            prod = product(pid)
            if not prod or not (is_owner(m.from_user.id) or (shop and prod.get("shop_id") == shop["id"])):
                bot.send_message(m.chat.id, t(lang, "not_allowed"))
            elif not digits.isdigit() or int(digits) > 1000000:
                bot.send_message(m.chat.id, t(lang, "bad_number"))
                WAIT[m.chat.id] = state
            else:
                set_product_stock(pid, int(digits))
                bot.send_message(m.chat.id, t(lang, "stock_updated"))
        elif kind == "prod_file":
            draft = state["extra"].get("draft") or {}
            fid, ftype = file_from_message(m)
            if not fid and not text.strip():
                bot.send_message(m.chat.id, t(lang, "ask_file"))
                WAIT[m.chat.id] = state
                return
            draft["product_file_id"] = fid
            draft["product_file_type"] = ftype
            if not fid:
                draft["digital_content"] = text
            add_shop_product(state["extra"].get("shop_id"), draft)
            bot.send_message(m.chat.id, t(lang, "product_saved"))
        elif kind in ("ship_pick", "ship_confirm", "prod_type", "prod_method"):
            # waiting for a BUTTON: keep the form alive instead of silently swallowing the text
            WAIT[m.chat.id] = state
            bot.send_message(m.chat.id, t(lang, "choose"))
        elif kind in SHIP_PROMPTS:
            handle_ship_input(m, lang, kind, state["extra"], text)
        elif kind == "ship_track":
            mark_shipped(m, user, lang, state["extra"]["order_id"], text)
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
                    notify(admin, f"{t(lang_of_tg(admin), 'support_from')} {m.from_user.id}\n{esc(text)}")
                if dest:
                    bot.send_message(m.chat.id, f"{t(lang, 'sent_owner')} {dest}")
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
                        notify(owner["telegram_id"], f"{t(lang_of(owner), 'support_from')} {m.from_user.id}\n{esc(text)}")
                bot.send_message(m.chat.id, t(lang, "saved"))
        elif kind == "receipt":
            submit_receipt(m, state["extra"]["order_id"])
    except Exception as e:
        print("form failed:", e)
        bot.send_message(m.chat.id, t(lang, "err_generic"))

def submit_receipt(m, order_id):
    text = m.text or m.caption or ""
    if m.content_type == "photo":
        text = f"PHOTO:{m.photo[-1].file_id}\n{text}"
    table("payment_receipts").insert({"order_id": order_id, "telegram_id": m.from_user.id, "text": text}).execute()
    for admin in ADMIN_IDS:
        al = lang_of_tg(admin)
        k = types.InlineKeyboardMarkup()
        k.add(types.InlineKeyboardButton(t(al, "approve_btn"), callback_data=f"ok:{order_id}"))
        notify(admin, f"{t(al, 'pay_card')}\nID: {order_id}\n{esc(text)}", k)
    bot.send_message(m.chat.id, "✅ " + t(lang_of(get_user(m.from_user)), "receipt_ok"))

@bot.pre_checkout_query_handler(func=lambda q: True)
def precheckout(q):
    ok, err = True, None
    try:
        payload = q.invoice_payload or ""
        if payload.startswith("order:"):
            ok, err = precheck_order(payload.split(":", 1)[1], q)
    except Exception as e:
        print("precheckout check failed:", e)      # never block a payment because of OUR error
    try:
        if ok:
            bot.answer_pre_checkout_query(q.id, ok=True)
        else:
            bot.answer_pre_checkout_query(q.id, ok=False, error_message=err or "Unavailable")
    except Exception as e:
        print("precheckout answer failed:", e)

@bot.message_handler(content_types=["successful_payment"])
def successful_payment(m):
    sp = m.successful_payment
    payload = sp.invoice_payload
    if payload.startswith("order:"):
        handle_order_payment(m, payload.split(":", 1)[1])
        return
    if payload.startswith("prod:"):
        if not record_charge(sp.telegram_payment_charge_id, "prod", payload, None, m.from_user.id, sp.total_amount, sp.currency):
            return
        _, pid, user_id = payload.split(":", 2)
        p = product(pid)
        if p:
            deliver_product(m.chat.id, p)
            bot.send_message(m.chat.id, "✅ " + t(lang_of(get_user(m.from_user)), "delivered"))
        return
    if payload.startswith("plan:"):
        parts = payload.split(":")
        plan_id, user_id = parts[1], parts[2]
        if not record_charge(sp.telegram_payment_charge_id, "plan", plan_id, user_id, m.from_user.id, sp.total_amount, sp.currency):
            return
        shop_id = parts[3] if len(parts) > 3 and parts[3] != "none" else None
        plan = plan_by_id(plan_id)
        if plan:
            ends = activate_plan(user_id, shop_id, plan)
            lg = lang_of(get_user(m.from_user))
            bot.send_message(m.chat.id, f"✅ {t(lg, 'sub_until')} {fmt_date(lg, ends.isoformat(), with_time=False)}")
        return

@bot.message_handler(content_types=["photo", "document", "video", "animation"])
def media_step(m):
    if m.chat.id in WAIT:
        on_text(m)
        return
    relay_deal(m)
@bot.message_handler(commands=["menu", "panel", "shops", "support"])
def menu_commands(m):
    user = get_user(m.from_user)
    WAIT.pop(m.chat.id, None)
    if not user.get("language_set"):
        ask_language(m.chat.id)
        return
    if m.text.startswith("/panel"):
        ask_panel(m.chat.id, lang_of(user), m.from_user.id)
        return
    if gate_onboarding(m, user):
        return
    if m.text.startswith("/shops"):
        customer_action(Click(m), user, lang_of(user), "shops")
        return
    if m.text.startswith("/support"):
        customer_action(Click(m), user, lang_of(user), "support")
        return
    send_home(m.chat.id, user, m.from_user.id)

class Click:
    def __init__(self, message):
        self.message = message
        self.from_user = message.from_user
        self.id = "0"
        self.data = ""

MENU_KEYS = ("owner_btn", "admin_btn", "switch_panel", "income_btn", "shop", "shops", "channels", "channels_btn", "plans", "plans_btn", "my_sub_btn", "my_shop_btn", "products_btn", "my_channel_btn", "cart", "orders", "support", "language", "manage_orders_btn", "admins", "admin_stats", "my_support", "pay_method")

def is_exact_menu_text(text):
    """Only the real keyboard buttons. Used while a form is open, so a review or an
    address that merely contains the word 'orders' can't hijack the form."""
    return (text or "").strip() in labels(*MENU_KEYS)

def is_menu_text(text):
    raw = (text or "").strip()
    if is_exact_menu_text(raw):
        return True
    folded = raw.replace("🛍", "").replace("📦", "").replace("🛒", "").replace("🎫", "").replace("🌐", "").replace("⭐", "").replace("📣", "").replace("📊", "").replace("👑", "").replace("🏪", "").replace("🔁", "").strip()
    keys = ("فروشگاه من", "محصولات", "اشتراک من", "کانال من", "سبد خرید", "سفارش", "پشتیبانی", "زبان", "درآمد", "کانال", "تغییر پنل", "مدیریت سفارش", "My shop", "Products", "My subscription", "My channel", "Cart", "Orders", "Support", "Language", "Revenue", "Shops", "Switch panel")
    return any(k.lower() in folded.lower() for k in keys)

def handle_menu(m):
    try:
        bot.clear_step_handler_by_chat_id(m.chat.id)
    except Exception:
        pass
    WAIT.pop(m.chat.id, None)
    user = get_user(m.from_user)
    lang = lang_of(user)
    text = m.text or ""
    folded = text.replace("🛍", "").replace("📦", "").replace("🛒", "").replace("🎫", "").replace("🌐", "").replace("⭐", "").replace("📣", "").replace("📊", "").replace("👑", "").replace("🏪", "").replace("🔁", "").strip().lower()
    fake = Click(m)
    if text in labels("owner_btn", "admin_btn") or folded in ("پنل مالک", "پنل ادمین", "owner panel", "admin panel"):
        send_home(m.chat.id, user, m.from_user.id)
    elif text in labels("manage_orders_btn") or "مدیریت سفارش" in folded or "manage orders" in folded:
        show_manage_orders(m.chat.id, user, m.from_user.id, lang)
    elif text in labels("switch_panel") or "تغییر پنل" in folded or "switch panel" in folded:
        ask_panel(m.chat.id, lang, m.from_user.id)
    elif text in labels("income_btn") or folded in ("درآمد", "revenue"):
        owner_action(fake, user, lang, "revenue")
    elif text in labels("my_shop_btn") or "فروشگاه من" in folded or "my shop" in folded:
        seller_action(fake, user, lang, "shop")
    elif text in labels("shop", "shops") or folded in ("فروشگاه‌ها", "فروشگاه ها", "shops"):
        if is_owner(m.from_user.id):
            owner_action(fake, user, lang, "shops")
        else:
            customer_action(fake, user, lang, "shops")
    elif text in labels("channels_btn", "channels") or folded in ("کانال‌ها", "کانال ها", "channels"):
        owner_action(fake, user, lang, "channels")
    elif text in labels("plans_btn", "plans") or folded in ("اشتراک‌ها", "اشتراک ها", "plans"):
        owner_action(fake, user, lang, "plans")
    elif text in labels("admins") or "ادمین" in folded or "admins" in folded:
        owner_action(fake, user, lang, "admins")
    elif text in labels("admin_stats") or "آمار" in folded or "stats" in folded:
        owner_action(fake, user, lang, "stats")
    elif text in labels("my_support") or "پشتیبانی من" in folded or "my support" in folded or "support id" in folded:
        if is_owner(m.from_user.id):
            owner_action(fake, user, lang, "support")
        else:
            seller_action(fake, user, lang, "support")
    elif text in labels("pay_method") or "شیوه" in folded or "method" in folded or "sales method" in folded:
        seller_action(fake, user, lang, "method")
    elif text in labels("my_sub_btn") or "اشتراک من" in folded or "my subscription" in folded:
        seller_action(fake, user, lang, "sub")
    elif text in labels("products_btn") or folded in ("محصولات", "products"):
        seller_action(fake, user, lang, "products")
    elif text in labels("my_channel_btn") or "کانال من" in folded or "my channel" in folded:
        seller_action(fake, user, lang, "channel")
    elif text in labels("cart") or "سبد" in folded or folded == "cart":
        show_cart(m.chat.id, user, lang)
    elif text in labels("orders") or "سفارش" in folded or "orders" in folded:
        show_orders(m.chat.id, user)
    elif text in labels("support") or "پشتیبانی" in folded or folded == "support":
        customer_action(fake, user, lang, "support")
    elif text in labels("language") or folded in ("زبان", "language"):
        ask_language(m.chat.id)
    else:
        bot.send_message(m.chat.id, t(lang, "choose"))

@bot.message_handler(func=lambda m: m.content_type == "text" and not (m.text or "").startswith("/"))
def menu_text(m):
    try:
        user = get_user(m.from_user)
        if m.chat.id in WAIT:
            if is_exact_menu_text(m.text or ""):
                handle_menu(m)
            else:
                on_text(m)
            return
        if gate_onboarding(m, user):            # language first, then panel
            return
        if is_menu_text(m.text or ""):
            handle_menu(m)
            return
        if relay_deal(m):
            return
        handle_menu(m)
    except Exception as e:
        print("menu failed:", e)
        try:
            bot.send_message(m.chat.id, t("fa", "err_generic") + "\n" + t("en", "err_generic"))
        except Exception:
            pass

setup_commands()


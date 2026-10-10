from datetime import datetime, timedelta, timezone
from db import table, one
from config import ADMIN_IDS, REVIEW_LIMIT, REPORT_LIMIT, REVIEW_REQUIRES_PURCHASE, MAX_CART_QTY
from payments import stars_amount

OWNER_ID = 6914909647

def _now():
    return datetime.now(timezone.utc)

def get_user(tg_user):
    row = one("users", {"telegram_id": tg_user.id})
    if row:
        return row
    payload = {
        "telegram_id": tg_user.id,
        "username": tg_user.username,
        "first_name": tg_user.first_name,
        "language": "fa",
        "language_set": False,
        "wallet_balance": 0,
        "points": 0,
        "role": "owner" if tg_user.id in ADMIN_IDS else "user",
        "trial_used": False,
    }
    res = table("users").insert(payload).execute()
    if not res.data:
        raise RuntimeError("users insert returned no row. Use the Supabase service_role key and run schema_update.sql.")
    return res.data[0]

def set_language(user_id, lang):
    return table("users").update({"language": lang, "language_set": True}).eq("id", user_id).execute()

def is_owner(tg_id):
    if int(tg_id) == OWNER_ID or int(tg_id) in ADMIN_IDS:
        return True
    row = one("users", {"telegram_id": tg_id})
    return bool(row and row.get("role") == "owner")

def is_admin(tg_id):
    if is_owner(tg_id):
        return True
    row = one("users", {"telegram_id": tg_id})
    return bool(row and row.get("role") in ("owner", "admin", "manager"))

def panel_of(tg_id):
    if int(tg_id) == OWNER_ID or int(tg_id) in ADMIN_IDS:
        return "owner"
    return get_setting(f"panel:{tg_id}", "")

def set_panel(tg_id, panel):
    set_setting(f"panel:{tg_id}", panel)
    if panel == "admin":
        set_user_role(tg_id, "admin")
    elif panel == "customer":
        set_user_role(tg_id, "user")

def is_seller(user):
    if not user:
        return False
    if user.get("role") in ("admin", "manager"):
        return True
    return panel_of(user.get("telegram_id")) == "admin"

def accept_admin(user):
    set_user_role(user["telegram_id"], "admin")
    set_panel(user["telegram_id"], "admin")
    fresh = one("users", {"id": user["id"]}) or user
    trial = start_trial(fresh, None)
    return trial

def get_setting(key, default=""):
    row = one("settings", {"key": key})
    return row.get("value") if row and row.get("value") is not None else default

def set_setting(key, value):
    existing = one("settings", {"key": key})
    if existing:
        return table("settings").update({"value": value}).eq("key", key).execute()
    return table("settings").insert({"key": key, "value": value}).execute()

def list_admins():
    return table("users").select("*").in_("role", ["admin", "manager", "owner"]).execute().data

def set_user_role(telegram_id, role):
    row = one("users", {"telegram_id": int(telegram_id)})
    if not row:
        return None
    table("users").update({"role": role}).eq("id", row["id"]).execute()
    return row

def categories(parent_id=None):
    q = table("categories").select("*").eq("active", True).order("sort_order")
    if parent_id is None:
        q = q.is_("parent_id", "null")
    else:
        q = q.eq("parent_id", parent_id)
    return q.execute().data

def products(category_id=None):
    q = table("products").select("*").eq("active", True).order("created_at", desc=True)
    if category_id:
        q = q.eq("category_id", category_id)
    return q.execute().data

def product(product_id):
    return one("products", {"id": product_id})

def cart(user_id):
    return table("cart_items").select("*, products(*)").eq("user_id", user_id).execute().data

def add_cart(user_id, product_id, qty=1):
    p = product(product_id)
    if not p:
        return None
    existing = table("cart_items").select("*").eq("user_id", user_id).eq("product_id", product_id).limit(1).execute().data
    if existing:
        new_qty = existing[0]["quantity"] + qty
        return table("cart_items").update({"quantity": new_qty}).eq("id", existing[0]["id"]).execute().data[0]
    return table("cart_items").insert({"user_id": user_id, "product_id": product_id, "quantity": qty}).execute().data[0]

def remove_cart(user_id, item_id):
    return table("cart_items").delete().eq("user_id", user_id).eq("id", item_id).execute()

def clear_cart(user_id):
    return table("cart_items").delete().eq("user_id", user_id).execute()

def create_order(user, payment_method):
    items = cart(user["id"])
    if not items:
        return None
    subtotal = sum(float(x["products"]["price"]) * x["quantity"] for x in items)
    order = table("orders").insert({
        "user_id": user["id"],
        "status": "pending",
        "payment_status": "unpaid",
        "payment_method": payment_method,
        "subtotal": subtotal,
        "total": subtotal,
    }).execute().data[0]
    for x in items:
        p = x["products"]
        table("order_items").insert({
            "order_id": order["id"],
            "product_id": p["id"],
            "product_name": p["name_fa"],
            "quantity": x["quantity"],
            "unit_price": p["price"],
            "digital_delivery": p.get("digital_content"),
        }).execute()
    clear_cart(user["id"])
    return order

def mark_paid(order_id, transaction_id=None):
    data = {"payment_status": "paid", "status": "paid"}
    if transaction_id:
        data["transaction_id"] = transaction_id
    return table("orders").update(data).eq("id", order_id).execute()

def stats():
    orders = table("orders").select("total,payment_status,created_at").eq("payment_status", "paid").execute().data
    revenue = sum(float(x["total"]) for x in orders)
    return {"orders": len(orders), "revenue": revenue}

def apply_coupon(code, subtotal):
    c = one("coupons", {"code": code.upper()})
    if not c or not c.get("active"):
        return {"ok": False, "discount": 0}
    if c.get("expires_at"):
        try:
            if datetime.fromisoformat(c["expires_at"].replace("Z", "+00:00")) < _now():
                return {"ok": False, "discount": 0}
        except Exception:
            pass
    if c.get("max_uses") is not None and c.get("used_count", 0) >= c["max_uses"]:
        return {"ok": False, "discount": 0}
    discount = subtotal * float(c["value"]) / 100 if c.get("kind") == "percent" else min(subtotal, float(c["value"]))
    return {"ok": True, "discount": discount, "coupon": c}

def update_order_status(order_id, status):
    return table("orders").update({"status": status}).eq("id", order_id).execute()

def approve_card_payment(order_id):
    return mark_paid(order_id, "CARD_TRANSFER")

def customer_orders(user_id):
    return table("orders").select("*").eq("user_id", user_id).order("created_at", desc=True).execute().data

def my_shop(user_id):
    rows = table("shops").select("*").eq("owner_user_id", user_id).eq("active", True).limit(1).execute().data
    return rows[0] if rows else None

def all_shops():
    return table("shops").select("*").order("created_at", desc=True).execute().data

def shop_by_id(shop_id):
    return one("shops", {"id": shop_id})

def create_shop(user, title):
    existing = my_shop(user["id"])
    if existing:
        return existing, False
    res = table("shops").insert({
        "owner_user_id": user["id"],
        "title": title,
        "support_username": user.get("support_username") or "",
        "active": True,
    }).execute()
    shop = res.data[0]
    trial = start_trial(user, shop["id"])
    if user.get("role") not in ("owner", "admin", "manager"):
        table("users").update({"role": "admin"}).eq("id", user["id"]).execute()
    return shop, trial

def shop_products(shop_id):
    return table("products").select("*").eq("shop_id", shop_id).eq("active", True).order("created_at", desc=True).execute().data

def add_shop_product(shop_id, payload):
    data = {
        "shop_id": shop_id,
        "name_fa": payload["name_fa"],
        "name_en": payload.get("name_en") or payload["name_fa"],
        "price": payload.get("stars_price") or 0,
        "stars_price": payload.get("stars_price") or 0,
        "stock": int(payload["stock"]) if payload.get("stock") is not None else 999,
        "active": True,
        "product_type": payload.get("product_type") or "digital",
        "description_fa": payload.get("description"),
        "description_en": payload.get("description"),
        "pay_method": payload.get("pay_method") or "stars",
        "banner_file_id": payload.get("banner_file_id"),
        "banner_type": payload.get("banner_type"),
        "product_file_id": payload.get("product_file_id"),
        "product_file_type": payload.get("product_file_type"),
        "digital_content": payload.get("digital_content"),
    }
    res = table("products").insert(data).execute()
    return res.data[0] if res.data else None

def set_shop_pay_method(shop_id, method):
    return table("shops").update({"pay_method": method}).eq("id", shop_id).execute()

def product_method(p, shop=None):
    return (p or {}).get("pay_method") or (shop or {}).get("pay_method") or "stars"

def create_deal(product_row, customer, seller):
    res = table("deals").insert({
        "product_id": product_row["id"],
        "shop_id": product_row.get("shop_id"),
        "customer_id": customer["id"],
        "seller_id": seller["id"],
        "status": "open",
    }).execute()
    return res.data[0] if res.data else None

def deal_by_id(deal_id):
    return one("deals", {"id": deal_id})

def close_deal(deal_id, status):
    return table("deals").update({"status": status}).eq("id", deal_id).execute()

def add_review(product_id, user_id, comment):
    existing = table("product_reviews").select("*").eq("product_id", product_id).eq("user_id", user_id).limit(1).execute().data
    payload = {"product_id": product_id, "user_id": user_id, "rating": 5, "comment": comment}
    if existing:
        return table("product_reviews").update({"comment": comment}).eq("id", existing[0]["id"]).execute()
    return table("product_reviews").insert(payload).execute()

def add_report(product_id, user_id, reason):
    return table("product_reports").insert({
        "product_id": product_id,
        "user_id": user_id,
        "reason": reason,
    }).execute()

def product_feedback(product_id):
    reviews = table("product_reviews").select("comment,created_at").eq("product_id", product_id).order("created_at", desc=True).limit(5).execute().data
    reports = table("product_reports").select("reason,created_at").eq("product_id", product_id).order("created_at", desc=True).limit(5).execute().data
    return reviews, reports

def set_shop_channel(shop_id, channel_id, username):
    return table("shops").update({
        "required_channel_id": channel_id,
        "required_channel_username": username,
    }).eq("id", shop_id).execute()

def clear_shop_channel(shop_id):
    return set_shop_channel(shop_id, "", "")

def set_support(user_id, support):
    table("users").update({"support_username": support}).eq("id", user_id).execute()
    shop = my_shop(user_id)
    if shop:
        table("shops").update({"support_username": support}).eq("id", shop["id"]).execute()

def list_plans():
    return table("plans").select("*").eq("active", True).order("days").execute().data

def add_plan(name_fa, name_en, days, stars):
    res = table("plans").insert({
        "name_fa": name_fa,
        "name_en": name_en,
        "days": int(days),
        "stars": int(stars),
        "active": True,
    }).execute()
    return res.data[0] if res.data else None

def deactivate_plan(plan_id):
    return table("plans").update({"active": False}).eq("id", plan_id).execute()

def plan_by_id(plan_id):
    return one("plans", {"id": plan_id})

def active_subscription(user_id):
    rows = table("subscriptions").select("*").eq("user_id", user_id).eq("status", "active").order("ends_at", desc=True).execute().data
    now = _now()
    for row in rows:
        try:
            ends = datetime.fromisoformat(row["ends_at"].replace("Z", "+00:00"))
        except Exception:
            continue
        if ends > now:
            return row
    return None

def shop_has_active_sub(shop):
    if not shop:
        return False
    return bool(active_subscription(shop["owner_user_id"]))

def start_trial(user, shop_id):
    if user.get("trial_used"):
        return False
    ends = _now() + timedelta(days=3)
    table("subscriptions").insert({
        "user_id": user["id"],
        "shop_id": shop_id,
        "status": "active",
        "is_trial": True,
        "ends_at": ends.isoformat(),
    }).execute()
    table("users").update({"trial_used": True}).eq("id", user["id"]).execute()
    return True

def activate_plan(user_id, shop_id, plan):
    current = active_subscription(user_id)
    start = _now()
    if current:
        try:
            start = datetime.fromisoformat(current["ends_at"].replace("Z", "+00:00"))
        except Exception:
            start = _now()
    ends = start + timedelta(days=int(plan["days"]))
    table("subscriptions").insert({
        "user_id": user_id,
        "shop_id": shop_id,
        "plan_id": plan["id"],
        "status": "active",
        "is_trial": False,
        "ends_at": ends.isoformat(),
    }).execute()
    return ends

def cancel_subscription(user_id):
    return table("subscriptions").update({"status": "cancelled"}).eq("user_id", user_id).eq("status", "active").execute()

def revenue_text():
    data = stats()
    subs = table("subscriptions").select("id,is_trial,status").eq("status", "active").execute().data
    return data, subs

def admin_sales():
    shops = all_shops()
    paid_ids = {o["id"] for o in table("orders").select("id").eq("payment_status", "paid").execute().data}
    all_items = table("order_items").select("order_id,product_id,quantity,unit_price").execute().data if paid_ids else []
    lines = []
    for shop in shops:
        owner = one("users", {"id": shop["owner_user_id"]}) or {}
        sub = active_subscription(shop["owner_user_id"])
        product_ids = [p["id"] for p in shop_products(shop["id"])]
        sold = 0
        total = 0
        for item in all_items:
            if item.get("order_id") in paid_ids and item.get("product_id") in product_ids:
                sold += int(item.get("quantity") or 0)
                total += float(item.get("unit_price") or 0) * int(item.get("quantity") or 0)
        lines.append({
            "shop": shop.get("title"),
            "admin": owner.get("telegram_id"),
            "orders": sold,
            "total": total,
            "sub": "active" if sub else "inactive",
        })
    return lines

def save_support_message(user_id, shop_id, target, message):
    return table("support_messages").insert({
        "from_user_id": user_id,
        "shop_id": shop_id,
        "target": target,
        "message": message,
    }).execute()

def public_shops():
    rows = []
    for shop in all_shops():
        if shop.get("active") and shop_has_active_sub(shop):
            rows.append(shop)
    return rows


# =====================================================================
# NEW: product types, stock, cart groups, orders, shipping, reviews
# (everything below is additive; nothing above changes behaviour except
#  the small fixes listed in README "تغییرات")
# =====================================================================

def iso_now():
    return _now().isoformat()

def owner_ids():
    return list(dict.fromkeys([int(x) for x in ADMIN_IDS] + [OWNER_ID]))

def user_by_id(user_id):
    return one("users", {"id": user_id}) if user_id else None

def user_by_tg(tg_id):
    return one("users", {"telegram_id": int(tg_id)})

def lang_of_tg(tg_id):
    try:
        row = user_by_tg(tg_id)
    except Exception:
        row = None
    return (row or {}).get("language") or "fa"

def is_duplicate_error(e):
    text = str(e).lower()
    return "23505" in text or "duplicate key" in text or "already exists" in text

# ---------------------------------------------------------------- products
def is_physical(p):
    return (p or {}).get("product_type") == "physical"

def product_price_stars(p):
    p = p or {}
    return int(p.get("stars_price") or p.get("price") or 0)

def max_qty(p):
    """Highest quantity one cart line may hold."""
    if not is_physical(p):
        return 1
    return max(0, min(int(p.get("stock") or 0), MAX_CART_QTY))

def product_of_shop(product_id, shop_id):
    p = product(product_id)
    return p if p and shop_id and p.get("shop_id") == shop_id else None

def set_product_stock(product_id, stock):
    return table("products").update({"stock": max(0, int(stock))}).eq("id", product_id).execute()

def deactivate_product(product_id):
    return table("products").update({"active": False}).eq("id", product_id).execute()

def deactivate_shop(shop_id):
    # also deactivate products
    table("products").update({"active": False}).eq("shop_id", shop_id).execute()
    return table("shops").delete().eq("id", shop_id).execute()

def deduct_stock(product_id, qty):
    """Atomic (compare-and-swap) stock decrement. False when there isn't enough."""
    for _ in range(5):
        p = product(product_id)
        if not p:
            return False
        cur = int(p.get("stock") or 0)
        if cur < qty:
            return False
        res = table("products").update({"stock": cur - qty}).eq("id", product_id).eq("stock", cur).execute()
        if res.data:
            return True
    return False

def add_stock(product_id, qty):
    for _ in range(5):
        p = product(product_id)
        if not p:
            return False
        cur = int(p.get("stock") or 0)
        res = table("products").update({"stock": cur + qty}).eq("id", product_id).eq("stock", cur).execute()
        if res.data:
            return True
    return False

# -------------------------------------------------------------------- cart
def add_to_cart(user, product_id):
    """Returns (status, item). status: ok | not_found | unavailable | own | out | limit | digital_once"""
    p = product(product_id)
    if not p or not p.get("active", True):
        return "not_found", None
    shop = shop_by_id(p["shop_id"]) if p.get("shop_id") else None
    if shop:
        if shop.get("owner_user_id") == user["id"]:
            return "own", None
        if not (shop.get("active") and shop_has_active_sub(shop)):
            return "unavailable", None
    if is_physical(p) and int(p.get("stock") or 0) <= 0:
        return "out", None
    existing = table("cart_items").select("*").eq("user_id", user["id"]).eq("product_id", product_id).limit(1).execute().data
    if existing:
        if not is_physical(p):
            return "digital_once", existing[0]
        new_qty = int(existing[0]["quantity"]) + 1
        if new_qty > max_qty(p):
            return "limit", existing[0]
        row = table("cart_items").update({"quantity": new_qty}).eq("id", existing[0]["id"]).execute().data[0]
        return "ok", row
    row = table("cart_items").insert({"user_id": user["id"], "product_id": product_id, "quantity": 1}).execute().data[0]
    return "ok", row

def change_cart_qty(user_id, item_id, delta):
    """Returns 'ok' | 'removed' | 'limit' | None (item not found)."""
    rows = table("cart_items").select("*, products(*)").eq("user_id", user_id).eq("id", item_id).limit(1).execute().data
    if not rows:
        return None
    row = rows[0]
    p = row.get("products") or {}
    new_qty = int(row["quantity"]) + delta
    if new_qty <= 0:
        table("cart_items").delete().eq("user_id", user_id).eq("id", item_id).execute()
        return "removed"
    if new_qty > max_qty(p):
        return "limit"
    table("cart_items").update({"quantity": new_qty}).eq("id", item_id).execute()
    return "ok"

def group_cart(items):
    """Split the cart per seller + payment method (each group = one order).
    method: 'stars' | 'custom' (decided by the seller) | 'platform' (shop-less products)."""
    groups, shops = {}, {}
    for x in items:
        p = x.get("products") or {}
        if not p:
            continue
        sid = p.get("shop_id")
        if sid and sid not in shops:
            shops[sid] = shop_by_id(sid)
        method = product_method(p, shops.get(sid)) if sid else "platform"
        key = f"{sid or '0'}:{method}"
        g = groups.setdefault(key, {"key": key, "shop": shops.get(sid), "shop_id": sid, "method": method, "items": []})
        g["items"].append(x)
    return list(groups.values())

def unit_price(p, method):
    if method == "custom":
        return 0
    if method == "stars":
        return product_price_stars(p)
    return float(p.get("price") or 0)

def group_total(g):
    return sum(unit_price(x["products"], g["method"]) * int(x["quantity"]) for x in g["items"])

def remove_cart_items(user_id, item_ids):
    for iid in item_ids:
        table("cart_items").delete().eq("user_id", user_id).eq("id", iid).execute()

# ------------------------------------------------------------------ orders
def order_by_id(order_id):
    return one("orders", {"id": order_id})

def order_items(order_id):
    return table("order_items").select("*").eq("order_id", order_id).execute().data

def create_order_for_lines(user, shop, lines, via, ship=None):
    """lines = [(product_row, qty)].  via = 'stars' | 'custom' | 'card'.
    Creates ONE order for ONE seller (never mixes sellers)."""
    requires = any(is_physical(p) for p, _ in lines)
    # price_mode: seller Stars price / custom (agreed in chat) / platform price (IRT, converted for Stars)
    price_mode = via if (via == "custom" or (via == "stars" and shop)) else "platform"
    currency = {"custom": "CUSTOM", "stars": "XTR"}.get(price_mode, "IRT")
    total = sum(unit_price(p, price_mode) * q for p, q in lines)
    row = {
        "user_id": user["id"],
        "shop_id": shop["id"] if shop else None,
        "seller_id": shop["owner_user_id"] if shop else None,
        "status": "pending",
        "payment_status": "unpaid",
        "payment_method": via,
        "currency": currency,
        "subtotal": total,
        "total": total,
        "requires_shipping": requires,
    }
    if requires and ship:
        row.update({
            "ship_name": ship.get("name"),
            "ship_phone": ship.get("phone"),
            "ship_address": ship.get("address"),
            "ship_postal_code": ship.get("postal") or None,
        })
    order = table("orders").insert(row).execute().data[0]
    table("order_items").insert([{
        "order_id": order["id"],
        "product_id": p["id"],
        "product_name": p["name_fa"],
        "product_name_en": p.get("name_en") or p["name_fa"],
        "quantity": q,
        "unit_price": unit_price(p, price_mode),
        "digital_delivery": None if is_physical(p) else p.get("digital_content"),
        "product_type": "physical" if is_physical(p) else "digital",
    } for p, q in lines]).execute()
    return order

def order_stars_amount(order):
    """How many Stars the invoice of this order must be."""
    if (order.get("currency") or "IRT") == "XTR":
        return max(1, int(round(float(order.get("total") or 0))))
    return stars_amount(float(order.get("total") or 0))

def claim_payment(order_id, transaction_id=None):
    """Atomically flips pending/unpaid -> paid. Returns the order row only for the
    FIRST caller, so a duplicated webhook can never fulfil an order twice."""
    data = {"payment_status": "paid", "status": "paid", "paid_at": iso_now()}
    if transaction_id:
        data["transaction_id"] = transaction_id
    res = table("orders").update(data).eq("id", order_id).eq("payment_status", "unpaid").eq("status", "pending").execute()
    return res.data[0] if res.data else None

def release_claim(order_id):
    return table("orders").update({"payment_status": "unpaid", "status": "pending", "paid_at": None, "transaction_id": None}).eq("id", order_id).execute()

def update_order(order_id, **fields):
    res = table("orders").update(fields).eq("id", order_id).execute()
    return res.data[0] if res.data else None

def deduct_order_stock(order, items):
    """Deduct stock of every physical line (all-or-nothing)."""
    done = []
    for it in items:
        if it.get("product_type") != "physical":
            continue
        q = int(it.get("quantity") or 1)
        if not deduct_stock(it["product_id"], q):
            for pid, dq in done:
                add_stock(pid, dq)
            return False
        done.append((it["product_id"], q))
    if done:
        table("orders").update({"stock_deducted": True}).eq("id", order["id"]).execute()
    return True

def restore_order_stock(order, items):
    fresh = order_by_id(order["id"]) or order
    if not fresh.get("stock_deducted"):
        return
    for it in items:
        if it.get("product_type") == "physical":
            add_stock(it["product_id"], int(it.get("quantity") or 1))
    table("orders").update({"stock_deducted": False}).eq("id", order["id"]).execute()

def _visible_orders(rows, only_ship):
    out = []
    for o in rows:
        if o.get("status") == "draft":
            continue
        if not (o.get("payment_status") == "paid" or o.get("payment_method") == "custom"):
            continue  # unpaid Stars invoices are the buyer's business, not the seller's
        if only_ship and not (o.get("status") == "paid" and o.get("requires_shipping")):
            continue
        out.append(o)
    return out

def seller_order_rows(seller_user_id, only_ship=False, limit=10):
    rows = table("orders").select("*").eq("seller_id", seller_user_id).order("created_at", desc=True).limit(80).execute().data
    return _visible_orders(rows, only_ship)[:limit]

def all_order_rows(only_ship=False, limit=10):
    rows = table("orders").select("*").order("created_at", desc=True).limit(120).execute().data
    return _visible_orders(rows, only_ship)[:limit]

def count_to_ship(seller_user_id=None):
    q = table("orders").select("id").eq("status", "paid").eq("requires_shipping", True)
    if seller_user_id:
        q = q.eq("seller_id", seller_user_id)
    return len(q.execute().data)

def revenue_by_currency():
    rows = table("orders").select("total,currency,payment_status").eq("payment_status", "paid").execute().data
    out = {}
    for x in rows:
        cur = x.get("currency") or "IRT"
        out[cur] = out.get(cur, 0) + float(x.get("total") or 0)
    return out

# ----------------------------------------------------------------- address
def get_address(user_id):
    return one("addresses", {"user_id": user_id})

def save_address(user_id, ship):
    return table("addresses").upsert({
        "user_id": user_id,
        "full_name": ship.get("name"),
        "phone": ship.get("phone"),
        "address": ship.get("address"),
        "postal_code": ship.get("postal") or None,
        "updated_at": iso_now(),
    }, on_conflict="user_id").execute()

def ship_from_address_row(row):
    return {"name": row.get("full_name"), "phone": row.get("phone"),
            "address": row.get("address"), "postal": row.get("postal_code") or ""}

# ------------------------------------------------------------------- deals
def create_order_deal(order, customer, seller, first_product, qty_total):
    res = table("deals").insert({
        "product_id": first_product["id"],
        "shop_id": order.get("shop_id"),
        "customer_id": customer["id"],
        "seller_id": seller["id"],
        "status": "open",
        "order_id": order["id"],
        "quantity": qty_total,
    }).execute()
    return res.data[0] if res.data else None

def claim_deal(deal_id, new_status):
    """open -> new_status exactly once (double taps must not deliver twice)."""
    res = table("deals").update({"status": new_status}).eq("id", deal_id).eq("status", "open").execute()
    return res.data[0] if res.data else None

def deal_for_order(order_id):
    rows = table("deals").select("*").eq("order_id", order_id).order("created_at", desc=True).limit(1).execute().data
    return rows[0] if rows else None

def open_deal_for_user(user_id, within_hours=48):
    """DB fallback for the in-memory chat map (survives restarts)."""
    cutoff = _now() - timedelta(hours=within_hours)
    rows = []
    for col in ("customer_id", "seller_id"):
        rows += table("deals").select("*").eq("status", "open").eq(col, user_id).execute().data
    fresh = []
    for d in rows:
        try:
            created = datetime.fromisoformat(str(d["created_at"]).replace("Z", "+00:00"))
        except Exception:
            continue
        if created >= cutoff:
            fresh.append(d)
    fresh.sort(key=lambda d: d["created_at"], reverse=True)
    return fresh[0] if fresh else None

# ---------------------------------------------------- payments idempotency
def record_charge(charge_id, kind, ref, user_id, tg_id, amount, currency="XTR"):
    """True the first time a Telegram charge id is seen, False for a duplicate
    webhook delivery. Infrastructure errors never block a real payment."""
    if not charge_id:
        return True
    try:
        table("payments_ledger").insert({
            "charge_id": charge_id, "kind": kind, "ref": str(ref), "user_id": user_id,
            "telegram_id": int(tg_id) if tg_id else None, "amount": int(amount or 0), "currency": currency,
        }).execute()
        return True
    except Exception as e:
        if is_duplicate_error(e):
            return False
        print("ledger unavailable:", e)
        return True

# ------------------------------------------------------ reviews & reports
def _count(tbl, product_id, user_id):
    return len(table(tbl).select("id").eq("product_id", product_id).eq("user_id", user_id).execute().data)

def has_purchased(user_id, product_id):
    paid = table("orders").select("id").eq("user_id", user_id).eq("payment_status", "paid").execute().data
    ids = [o["id"] for o in paid]
    if ids:
        hit = table("order_items").select("id").in_("order_id", ids).eq("product_id", product_id).limit(1).execute().data
        if hit:
            return True
    legacy = table("deals").select("id").eq("customer_id", user_id).eq("product_id", product_id).eq("status", "paid").limit(1).execute().data
    return bool(legacy)

def feedback_gate(kind, product_id, user):
    """(ok, reason_key). One review and up to REPORT_LIMIT reports per person per product."""
    p = product(product_id)
    if not p:
        return False, "not_found"
    shop = shop_by_id(p["shop_id"]) if p.get("shop_id") else None
    if kind == "review":
        if shop and shop.get("owner_user_id") == user["id"]:
            return False, "own_review"
        if _count("product_reviews", product_id, user["id"]) >= REVIEW_LIMIT:
            return False, "review_limit"
        if REVIEW_REQUIRES_PURCHASE and not has_purchased(user["id"], product_id):
            return False, "review_need_purchase"
        return True, None
    if _count("product_reports", product_id, user["id"]) >= REPORT_LIMIT:
        return False, "report_limit"
    return True, None

def submit_review(product_id, user, comment):
    ok, why = feedback_gate("review", product_id, user)
    if not ok:
        return False, why
    n = _count("product_reviews", product_id, user["id"])
    try:
        table("product_reviews").insert({"product_id": product_id, "user_id": user["id"], "rating": 5,
                                         "comment": comment, "seq": n + 1}).execute()
    except Exception as e:
        if is_duplicate_error(e):
            return False, "review_limit"
        raise
    return True, None

def submit_report(product_id, user, reason):
    ok, why = feedback_gate("report", product_id, user)
    if not ok:
        return False, why
    n = _count("product_reports", product_id, user["id"])
    try:
        table("product_reports").insert({"product_id": product_id, "user_id": user["id"],
                                         "reason": reason, "seq": n + 1}).execute()
    except Exception as e:
        if is_duplicate_error(e):
            return False, "report_limit"
        raise
    return True, None

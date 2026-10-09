from datetime import datetime, timedelta, timezone
from db import table, one
from config import ADMIN_IDS

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
    return one("shops", {"owner_user_id": user_id})

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

def add_shop_product(shop_id, name_fa, name_en, price, stock):
    res = table("products").insert({
        "shop_id": shop_id,
        "name_fa": name_fa,
        "name_en": name_en,
        "price": price,
        "stock": stock,
        "active": True,
    }).execute()
    return res.data[0] if res.data else None

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
    orders = table("orders").select("user_id,total,payment_status").eq("payment_status", "paid").execute().data
    lines = []
    for shop in shops:
        owner = one("users", {"id": shop["owner_user_id"]}) or {}
        sub = active_subscription(shop["owner_user_id"])
        product_ids = [p["id"] for p in shop_products(shop["id"])]
        sold = 0
        total = 0
        items = table("order_items").select("product_id,quantity,unit_price").execute().data if product_ids else []
        for item in items:
            if item.get("product_id") in product_ids:
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

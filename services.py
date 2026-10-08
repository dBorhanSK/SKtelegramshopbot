from datetime import datetime, timezone
from db import table, one
from config import ADMIN_IDS

def get_user(tg_user):
    row = one("users", {"telegram_id": tg_user.id})
    if row:
        return row
    payload = {
        "telegram_id": tg_user.id,
        "username": tg_user.username,
        "first_name": tg_user.first_name,
        "language": "fa",
        "wallet_balance": 0,
        "points": 0,
        "role": "user",
    }
    return table("users").insert(payload).execute().data[0]

def set_language(user_id, lang):
    return table("users").update({"language": lang}).eq("id", user_id).execute()

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

def is_admin(tg_id):
    if tg_id in ADMIN_IDS:
        return True
    row = one("users", {"telegram_id": tg_id})
    return bool(row and row.get("role") in ("owner", "admin", "manager"))


def apply_coupon(code, subtotal):
    c = one("coupons", {"code": code.upper()})
    if not c or not c.get("active"):
        return {"ok": False, "discount": 0}
    if c.get("expires_at"):
        from datetime import datetime, timezone
        try:
            if datetime.fromisoformat(c["expires_at"].replace("Z","+00:00")) < datetime.now(timezone.utc):
                return {"ok": False, "discount": 0}
        except Exception:
            pass
    if c.get("max_uses") is not None and c.get("used_count",0) >= c["max_uses"]:
        return {"ok": False, "discount": 0}
    discount = subtotal * float(c["value"]) / 100 if c.get("kind")=="percent" else min(subtotal, float(c["value"]))
    return {"ok": True, "discount": discount, "coupon": c}

def update_order_status(order_id, status):
    return table("orders").update({"status": status}).eq("id", order_id).execute()

def approve_card_payment(order_id):
    return mark_paid(order_id, "CARD_TRANSFER")

def customer_orders(user_id):
    return table("orders").select("*").eq("user_id", user_id).order("created_at", desc=True).execute().data

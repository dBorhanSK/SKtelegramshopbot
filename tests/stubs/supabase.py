"""Tiny in-memory PostgREST/supabase-py look-alike (enough for the bot)."""
import re, uuid, copy
from datetime import datetime, timezone

DB = {}
DEFAULTS = {
    "products": {"active": True, "stock": 0, "product_type": "digital", "stars_price": 0, "price": 0},
    "orders": {"stock_deducted": False, "requires_shipping": False, "currency": "IRT", "total": 0, "subtotal": 0},
    "order_items": {"product_type": "digital", "quantity": 1},
    "shops": {"active": True},
    "deals": {"status": "open"},
    "cart_items": {"quantity": 1},
}
UNIQUE = {
    "users": [("telegram_id",)], "payments_ledger": [("charge_id",)],
    "product_reviews": [("product_id", "user_id", "seq")], "product_reports": [("product_id", "user_id", "seq")],
    "addresses": [("user_id",)], "bot_states": [("chat_id",)], "shops": [("owner_user_id",)],
    "cart_items": [("user_id", "product_id")], "settings": [("key",)],
}
MISSING_TABLES = set()

class R:
    def __init__(self, data): self.data = data

def now_iso():
    return datetime.now(timezone.utc).isoformat()

class Q:
    def __init__(self, name):
        if name in MISSING_TABLES: raise Exception(f"relation {name} does not exist")
        self.name, self.op, self.f, self.ord, self.lim, self.payload, self.cols, self.conflict = name, "select", [], None, None, None, "*", None
    def select(self, cols="*"): self.op, self.cols = "select", cols; return self
    def insert(self, d): self.op, self.payload = "insert", d; return self
    def update(self, d): self.op, self.payload = "update", d; return self
    def delete(self): self.op = "delete"; return self
    def upsert(self, d, on_conflict=None): self.op, self.payload, self.conflict = "upsert", d, on_conflict; return self
    def eq(self, c, v): self.f.append(("eq", c, v)); return self
    def neq(self, c, v): self.f.append(("neq", c, v)); return self
    def in_(self, c, v): self.f.append(("in", c, list(v))); return self
    def is_(self, c, v): self.f.append(("is", c, None)); return self
    def order(self, c, desc=False): self.ord = (c, desc); return self
    def limit(self, n): self.lim = n; return self
    def _match(self, row):
        for op, c, v in self.f:
            x = row.get(c)
            if op == "eq" and x != v: return False
            if op == "neq" and x == v: return False
            if op == "in" and x not in v: return False
            if op == "is" and x is not None: return False
        return True
    def _check_unique(self, rows, new, ignore=None):
        for cols in UNIQUE.get(self.name, []):
            if any(new.get(c) is None for c in cols): continue
            for r in rows:
                if r is ignore: continue
                if all(r.get(c) == new.get(c) for c in cols):
                    raise Exception(f'duplicate key value violates unique constraint (23505) {self.name}{cols}')
    def execute(self):
        rows = DB.setdefault(self.name, [])
        if self.op == "insert":
            items = self.payload if isinstance(self.payload, list) else [self.payload]
            out = []
            for it in items:
                row = {"id": str(uuid.uuid4()), "created_at": now_iso(), **copy.deepcopy(DEFAULTS.get(self.name, {})), **copy.deepcopy(it)}
                if self.name in ("payments_ledger", "bot_states", "settings"): row.pop("id", None) if "id" not in it else None
                self._check_unique(rows, row)
                rows.append(row); out.append(copy.deepcopy(row))
            return R(out)
        if self.op == "upsert":
            key = self.conflict
            ex = next((r for r in rows if key and r.get(key) == self.payload.get(key)), None)
            if ex: ex.update(copy.deepcopy(self.payload)); return R([copy.deepcopy(ex)])
            row = {"id": str(uuid.uuid4()), "created_at": now_iso(), **copy.deepcopy(self.payload)}
            self._check_unique(rows, row); rows.append(row); return R([copy.deepcopy(row)])
        matched = [r for r in rows if self._match(r)]
        if self.op == "update":
            for r in matched: r.update(copy.deepcopy(self.payload))
            return R(copy.deepcopy(matched))
        if self.op == "delete":
            for r in matched: rows.remove(r)
            return R(copy.deepcopy(matched))
        out = copy.deepcopy(matched)
        if self.ord:
            c, d = self.ord; out.sort(key=lambda r: (r.get(c) is None, r.get(c)), reverse=d)
        if self.lim is not None: out = out[: self.lim]
        for rel in re.findall(r"(\w+)\(\*\)", self.cols):
            fk = rel[:-1] + "_id"
            for r in out:
                r[rel] = next((copy.deepcopy(x) for x in DB.get(rel, []) if x["id"] == r.get(fk)), None)
        return R(out)

class Client:
    def table(self, name): return Q(name)

def create_client(url, key): return Client()

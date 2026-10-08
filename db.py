from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_KEY are required")

# کلید جدید Supabase (sb_publishable / sb_secret) هم با create_client کار میکند
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def table(name):
    return supabase.table(name)

def one(name, filters):
    q = table(name).select("*")
    for k, v in filters.items():
        q = q.eq(k, v)
    r = q.limit(1).execute()
    return r.data[0] if r.data else None

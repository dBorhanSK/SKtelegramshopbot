import os
from dotenv import load_dotenv

load_dotenv()

def csv_env(name):
    return [x.strip() for x in os.getenv(name, "").split(",") if x.strip()]

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
BASE_URL = os.getenv("BASE_URL", "").rstrip("/")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "change_me")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
ADMIN_IDS = [int(x) for x in csv_env("ADMIN_IDS") if x.isdigit()]

SHOP_TITLE_FA = os.getenv("SHOP_TITLE_FA", "فروشگاه من")
SHOP_TITLE_EN = os.getenv("SHOP_TITLE_EN", "My Shop")

SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "").lstrip("@")
REQUIRED_CHANNEL_ID = os.getenv("REQUIRED_CHANNEL_ID", "")
REQUIRED_CHANNEL_USERNAME = os.getenv("REQUIRED_CHANNEL_USERNAME", "").lstrip("@")

CARD_NUMBER = os.getenv("CARD_NUMBER", "")
CARD_HOLDER = os.getenv("CARD_HOLDER", "")
ZARINPAL_MERCHANT_ID = os.getenv("ZARINPAL_MERCHANT_ID", "")
ZARINPAL_CALLBACK_URL = os.getenv("ZARINPAL_CALLBACK_URL", "")

CURRENCY = os.getenv("CURRENCY", "IRT")
STAR_TO_RIAL = int(os.getenv("STAR_TO_RIAL", "1000"))

# ===================== NEW: limits & safety =====================
def _int_env(name, default, lo, hi):
    try:
        v = int(os.getenv(name, str(default)))
    except ValueError:
        v = default
    return max(lo, min(hi, v))

# Reviews / reports each user may submit per product (database allows at most 2).
REVIEW_LIMIT = _int_env("REVIEW_LIMIT", 1, 1, 2)
REPORT_LIMIT = _int_env("REPORT_LIMIT", 2, 1, 2)
# Only people who really bought the product can review it (set to 0 to disable).
REVIEW_REQUIRES_PURCHASE = os.getenv("REVIEW_REQUIRES_PURCHASE", "1").strip().lower() not in ("0", "false", "no", "off")
# Max quantity of one physical product in a single cart line.
MAX_CART_QTY = _int_env("MAX_CART_QTY", 10, 1, 100)
# Unfinished forms (address, product wizard...) are forgotten after this many minutes.
STATE_TTL_MIN = _int_env("STATE_TTL_MIN", 30, 1, 1440)

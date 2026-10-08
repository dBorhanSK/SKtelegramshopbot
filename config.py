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

# Telegram Shop Bot — فارسی / English

ربات فروشگاهی تلگرام با معماری مناسب Render + Supabase.

## امکانات
- فارسی و English با انتخاب زبان
- Flask + Telegram Webhook
- Supabase PostgreSQL
- پنل مدیریت داخل تلگرام با نقش‌ها
- دسته‌بندی چندسطحی و کاتالوگ
- عکس، توضیح، قیمت، موجودی
- سبد خرید
- Telegram Stars
- کارت‌به‌کارت با ثبت رسید
- درگاه آنلاین با ساختار قابل اتصال (زرین‌پال)
- فاکتور و سفارش
- کانال اجباری
- تایید سفارش توسط ادمین
- کوپن تخفیف
- کیف پول داخلی
- امتیاز کاربر
- آمار فروش
- پیام‌رسانی گروهی
- قیمت‌گذاری تبلیغات کانال/بنر
- پیگیری وضعیت سفارش
- تیکت پشتیبانی
- ارسال خودکار فایل/کد برای محصولات دیجیتال پس از پرداخت
- پنل مدیریت وب ساده

## ساختار
- `app.py`: Flask و Webhook
- `bot.py`: منطق Telegram
- `db.py`: دسترسی Supabase
- `services.py`: منطق فروشگاه
- `config.py`: تنظیمات
- `schema.sql`: جداول Supabase
- `templates/admin.html`: پنل وب
- `render.yaml`: تنظیمات Render

## نصب
1. این پروژه را در GitHub قرار دهید.
2. در Supabase یک پروژه بسازید و محتوای `schema.sql` را در SQL Editor اجرا کنید.
3. Environment Variable های فایل `.env.example` را در Render تنظیم کنید.
4. سرویس Render را به GitHub وصل کنید.
5. بعد از Deploy، آدرس:
   `https://YOUR-SERVICE.onrender.com`
   را در `BASE_URL` بگذارید.
6. آدرس webhook:
   `https://YOUR-SERVICE.onrender.com/telegram-webhook`
   باید توسط ربات تنظیم شود. برنامه در startup این کار را انجام می‌دهد.

## نکته مهم درباره Sleep در Render
وقتی سرویس Free به خواب می‌رود، ارسال یک Update از Telegram به endpoint وبهوک باعث درخواست به سرویس می‌شود و Render می‌تواند آن را بیدار کند. بنابراین کاربر لازم نیست جداگانه سایت را باز کند؛ اولین پیام/کلیک Telegram خودش درخواست webhook ایجاد می‌کند. این موضوع وابسته به رفتار فعلی پلن Render است.

## اجرای محلی
```bash
pip install -r requirements.txt
python app.py
```

برای HTTPS محلی می‌توانید از Cloudflare Tunnel یا ngrok استفاده کنید.

## امنیت
- توکن و رمزها را داخل GitHub قرار ندهید.
- `ADMIN_PASSWORD` فقط برای ورود اولیه پنل وب است.
- برای تولید واقعی، مقدار `ADMIN_PASSWORD` را قوی انتخاب کنید.
- فایل‌های دیجیتال در دیتابیس به‌صورت URL یا متن نگهداری می‌شوند. برای فایل‌های خصوصی بهتر است Storage خصوصی Supabase یا فضای امن دیگری استفاده شود.

import html.parser, re
from . import types

class ApiTelegramException(Exception): pass

class _HTMLCheck(html.parser.HTMLParser):
    ALLOWED = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "code", "pre", "a", "tg-spoiler"}
    def __init__(self): super().__init__(); self.stack = []
    def handle_starttag(self, tag, attrs):
        if tag not in self.ALLOWED: raise ApiTelegramException(f"can't parse entities: unsupported start tag <{tag}>")
        self.stack.append(tag)
    def handle_endtag(self, tag):
        if not self.stack or self.stack.pop() != tag: raise ApiTelegramException(f"can't parse entities: bad end tag </{tag}>")

def check_html(text):
    p = _HTMLCheck(); p.feed(text); p.close()
    if p.stack: raise ApiTelegramException("can't parse entities: unclosed tag")

class Msg:
    def __init__(self, **kw): self.__dict__.update(kw)
    def __getattr__(self, k): return None

class TeleBot:
    def __init__(self, token, parse_mode=None):
        self.parse_mode = parse_mode; self.sent = []; self.msg_handlers = []; self.cb_handlers = []; self.pcq_handlers = []
        self.refunds = []; self.blocked = set(); self.members = {}
    # ---- registration
    def message_handler(self, commands=None, regexp=None, func=None, content_types=None, **kw):
        def deco(fn):
            self.msg_handlers.append((commands, func, content_types or ["text"], fn)); return fn
        return deco
    def callback_query_handler(self, func, **kw):
        def deco(fn): self.cb_handlers.append((func, fn)); return fn
        return deco
    def pre_checkout_query_handler(self, func, **kw):
        def deco(fn): self.pcq_handlers.append((func, fn)); return fn
        return deco
    # ---- dispatch (same first-match-wins rule as pyTelegramBotAPI)
    def dispatch_message(self, m):
        for commands, func, cts, fn in self.msg_handlers:
            if m.content_type not in cts: continue
            if commands is not None:
                if not (m.content_type == "text" and (m.text or "").startswith("/")): continue
                cmd = m.text.split()[0][1:].split("@")[0]
                if cmd not in commands: continue
            if func is not None and not func(m): continue
            return fn(m)
    def dispatch_callback(self, c):
        for func, fn in self.cb_handlers:
            if func(c): return fn(c)
    def dispatch_precheckout(self, q):
        for func, fn in self.pcq_handlers:
            if func(q): return fn(q)
    # ---- outgoing API with Telegram's real limits
    def _rec(self, method, chat_id, text=None, reply_markup=None, **extra):
        if chat_id in self.blocked: raise ApiTelegramException("Forbidden: bot was blocked by the user")
        if reply_markup is not None and hasattr(reply_markup, "keyboard"):
            for row in reply_markup.keyboard:
                for b in row:
                    if isinstance(b, str):
                        if not b: raise ApiTelegramException("empty button text")
                        continue
                    if not b.text: raise ApiTelegramException("empty button text")
                    if getattr(b, "callback_data", None) and len(b.callback_data.encode()) > 64: raise ApiTelegramException("BUTTON_DATA_INVALID " + b.callback_data)
        self.sent.append({"method": method, "chat_id": chat_id, "text": text, "markup": reply_markup, **extra})
    def send_message(self, chat_id, text, parse_mode=None, reply_markup=None, **kw):
        if not text: raise ApiTelegramException("message text is empty")
        if len(text) > 4096: raise ApiTelegramException("message is too long")
        if (parse_mode if parse_mode is not None else self.parse_mode) == "HTML": check_html(text)
        self._rec("send_message", chat_id, text, reply_markup)
    def _media(self, m, chat_id, fid, caption=None, reply_markup=None, **kw):
        if caption and len(caption) > 1024: raise ApiTelegramException("message caption is too long")
        if caption: check_html(caption)
        self._rec(m, chat_id, caption, reply_markup, file_id=fid)
    def send_photo(self, chat_id, fid, caption=None, reply_markup=None, **kw): self._media("send_photo", chat_id, fid, caption, reply_markup)
    def send_video(self, chat_id, fid, caption=None, reply_markup=None, **kw): self._media("send_video", chat_id, fid, caption, reply_markup)
    def send_document(self, chat_id, fid, caption=None, reply_markup=None, **kw): self._media("send_document", chat_id, fid, caption, reply_markup)
    def send_invoice(self, chat_id, title, description, invoice_payload, provider_token, currency, prices, **kw):
        assert 1 <= len(title) <= 32, f"invoice title length {len(title)}"
        assert 1 <= len(description) <= 255, f"invoice description length {len(description)}"
        assert len(invoice_payload.encode()) <= 128
        assert currency == "XTR" and len(prices) == 1 and prices[0].amount >= 1
        self._rec("send_invoice", chat_id, title, None, description=description, payload=invoice_payload, amount=prices[0].amount)
    def answer_callback_query(self, *a, **kw): pass
    def answer_pre_checkout_query(self, qid, ok, error_message=None): self.sent.append({"method": "pcq", "ok": ok, "err": error_message})
    def edit_message_text(self, text, chat_id, message_id, reply_markup=None, **kw):
        check_html(text); self._rec("edit_message_text", chat_id, text, reply_markup)
    def copy_message(self, to, frm, mid, **kw): self._rec("copy_message", to, "<copied>", None)
    def get_chat_member(self, ch, uid): return Msg(status=self.members.get((ch, uid), "member"))
    def get_me(self): return Msg(username="TestShopBot")
    def set_my_commands(self, *a, **kw): pass
    def set_webhook(self, **kw): return True
    def clear_step_handler_by_chat_id(self, *a): pass
    def refund_star_payment(self, user_id, telegram_payment_charge_id):
        self.refunds.append((user_id, telegram_payment_charge_id)); return True
    def process_new_updates(self, updates): pass

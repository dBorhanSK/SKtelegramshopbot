class _Obj:
    def __getattr__(self, k): return None
class ReplyKeyboardMarkup:
    def __init__(self, resize_keyboard=None, is_persistent=None, **kw): self.keyboard = []
    def row(self, *b): self.keyboard.append(list(b)); return self
    def add(self, *b): self.keyboard += [[x] for x in b]; return self
class InlineKeyboardButton:
    def __init__(self, text, url=None, callback_data=None, **kw): self.text, self.url, self.callback_data = text, url, callback_data
class InlineKeyboardMarkup:
    def __init__(self, **kw): self.keyboard = []
    def row(self, *b): self.keyboard.append(list(b)); return self
    def add(self, *b): self.keyboard += [[x] for x in b]; return self
class BotCommand:
    def __init__(self, command, description): self.command, self.description = command, description
class LabeledPrice:
    def __init__(self, label, amount): self.label, self.amount = label, amount
class Update:
    @staticmethod
    def de_json(d): return d

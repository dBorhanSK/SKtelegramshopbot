import re, sys
src = open(__import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "run.py")).read().split("OWNER, SELLER, CUST, CUST2")[0]
exec(src)
LAT = re.compile(r"[A-Za-z]{3,}")
def journey(lang, seller, cust, names):
    nf, ne, dsc = names
    say(seller, "/start"); press(seller, "lang_" + lang); press(seller, "panel_admin")
    press(seller, "sel:shop"); say(seller, "Shop"+lang)
    shop = [s for s in rows("shops") if s["title"] == "Shop"+lang][0]
    for (ptype, method) in (("physical", "stars"), ("digital", "stars"), ("physical", "custom")):
        press(seller, "sel:newprod"); say(seller, nf+ptype+method); say(seller, ne+ptype+method); say(seller, dsc); media(seller, "photo", "B")
        press(seller, "pt:"+ptype); press(seller, "pm:"+method)
        if method == "stars": say(seller, "20")
        if ptype == "physical": say(seller, "4")
        else: say(seller, "CODE123")
    ps = [p for p in rows("products") if p["shop_id"] == shop["id"]]
    press(seller, "sel:products"); press(seller, "sel:orders"); press(seller, "sel:sub"); press(seller, "sel:method")
    say(cust, "/start"); press(cust, "lang_" + lang); press(cust, "panel_customer")
    press(cust, "cus:shops"); press(cust, "sh:" + shop["id"])
    for p in ps: press(cust, "pr:" + p["id"]); press(cust, "add:" + p["id"])
    press(cust, "add:" + ps[1]["id"])
    press(cust, "cart")
    press(cust, f"co:{shop['id']}:stars"); say(cust, "a"); say(cust, "Ali Test"); say(cust, "x"); say(cust, "09123456789"); say(cust, "ab"); say(cust, "Some Street 12, City, Country"); say(cust, "12345"); press(cust, "ad:ok")
    inv = [x for x in bot.sent if x["method"] == "send_invoice" and x["chat_id"] == cust][-1]
    precheck(cust, inv["payload"], inv["amount"]); pay(cust, inv["payload"], inv["amount"], "AUD"+lang)
    o = [x for x in rows("orders") if x.get("transaction_id") == "AUD"+lang][0]
    press(cust, "orders"); press(cust, "od:"+o["id"]); press(seller, "od:"+o["id"]); press(seller, "ol:ship")
    press(seller, "sg:"+o["id"]); say(seller, "TRK999"); press(cust, "od:"+o["id"]); press(cust, "rc:"+o["id"])
    press(cust, f"co:{shop['id']}:custom"); press(cust, "ad:use")
    d = rows("deals")[-1]; say(cust, "hi"); say(seller, "ok"); press(seller, "cf:"+d["id"]); press(cust, "orders")
    press(cust, "rd:"+o["id"]); press(cust, "rv:"+ps[1]["id"]); say(cust, "nice item"); press(cust, "rv:"+ps[1]["id"]); press(cust, "rp:"+ps[1]["id"]); say(cust, "bad"); say(cust, "x")
    press(cust, "support"); press(cust, "cus:support"); press(cust, "sup:seller"); say(cust, "help me")
    # a second paid order then cancel/refund
    press(cust, "add:"+ps[0]["id"]); press(cust, f"co:{shop['id']}:stars"); press(cust, "ad:use")
    inv = [x for x in bot.sent if x["method"] == "send_invoice" and x["chat_id"] == cust][-1]; pay(cust, inv["payload"], inv["amount"], "AUD2"+lang)
    o2 = [x for x in rows("orders") if x.get("transaction_id") == "AUD2"+lang][0]
    press(seller, "cn:"+o2["id"]); press(seller, "cy:"+o2["id"])
    press(cust, "add:"+ps[0]["id"]); press(cust, f"co:{shop['id']}:stars"); press(cust, "ad:use"); o3 = [x for x in rows("orders") if x["status"]=="pending" and x["user_id"]==o["user_id"]][-1]
    press(cust, "po:"+o3["id"]); press(cust, "cn:"+o3["id"]); press(cust, "cy:"+o3["id"])
    press(seller, "mp:"+ps[0]["id"]); press(seller, "ms:"+ps[0]["id"]); say(seller, "9"); press(seller, "mr:"+ps[0]["id"]); press(seller, "mx:"+ps[0]["id"])
    press(seller, "language"); press(seller, "home") ; say(seller, "/menu"); say(cust, "/menu"); say(cust, "/shops"); say(cust, "/support")
    return seller, cust

res = {}
for lang, sel, cus, names in (("en", 701, 702, ("Shoe ", "Shoe ", "Nice and strong")), ("fa", 801, 802, ("کفش ", "-", "خوب و محکم"))):
    journey(lang, sel, cus, names)
bad = 0
for lang, uids in (("en", (701, 702)), ("fa", (801, 802))):
    seen = set()
    for x in bot.sent:
        if x.get("chat_id") not in uids: continue
        txt = x.get("text") or ""
        if x["method"] == "send_invoice": txt += " " + x.get("description", "")
        for row in (x.get("markup").keyboard if x.get("markup") else []):
            for b in row: txt += " " + (b if isinstance(b, str) else b.text)
        # strip user-provided content so only OUR strings are judged
        for junk in ("Shoe", "Ali Test", "Some Street 12, City, Country", "Nice and strong", "nice item", "help me", "TRK999", "CODE123", "Shop"+lang, "کفش", "خوب و محکم", "physical", "digital", "stars", "custom", "09123456789", "12345", "bad"):
            txt = txt.replace(junk, "")
        if lang == "en":
            hit = PERSIAN.findall(txt)
            key = "".join(hit[:12])
        else:
            hit = [w for w in LAT.findall(txt) if w not in ("XTR",)]
            key = " ".join(hit)
        if hit and key not in seen:
            seen.add(key); bad += 1
            print(f"[{lang}] mixed-language: {txt.strip()[:140]!r} -> {key}")
print("language audit done; messages with mixing:", bad)

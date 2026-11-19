#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
signal_glossary.py -- Persian explanations for every signal, message and node
=============================================================================

One single source of truth, used twice:

  * the HTML tester, which shows a (i) button next to every signal and writes the
    explanation into a popup;
  * the CANoe panel, which gets the same text as a control tooltip.

None of the source files carries a description: the network map exported from
the official databases has an empty Comment column for all 1078 signals, and the
binding workbook only knows which widget suits a signal.  So the text here is
**built from the signal name and its metadata**, not copied from the OEM
database:

  * a token glossary translates the name pieces (Ems -> موتور, Lamp -> چراغ, ...)
  * the metadata (message, cycle, unit, range, kind) is rendered as a fact line
  * the node section explains what the ECU does in the car

Every sentence says what is true for this signal.  Nothing here pretends to know
an OEM bit-level meaning that the data does not contain.

Run standalone to see the coverage report:

    python tools/signal_glossary.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "can_tester" / "assets" / "signal_map.json"
OUT_JSON = ROOT / "can_tester" / "assets" / "descriptions.json"
OUT_JS = ROOT / "can_tester" / "assets" / "descriptions.js"

# --------------------------------------------------------------------------- #
# nodes
# --------------------------------------------------------------------------- #
NODE_INFO = {
    "ABS": ("ترمز ضدقفل و کنترل پایداری",
            "دورِ چرخ‌ها را می‌خواند و از لغزش و قفل‌شدن چرخ جلوگیری می‌کند. سیگنال‌های Active/EBD/TCS و ESC وضعیت لحظه‌ای مداخله‌اش را می‌گویند."),
    "EMS": ("مدیریت موتور",
            "دور موتور، بار، دمای آب، موقعیت دریچه گاز و گشتاور را می‌فرستد. اصلی‌ترین منبع داده برای نمایشگر و برای بقیه ECUهاست."),
    "EPS": ("فرمان برقی",
            "گشتاور کمکی فرمان را تأمین می‌کند. سیگنال‌های Warning و Fault وضعیت سالم‌بودن سیستم فرمان را نشان می‌دهند."),
    "TCU": ("کنترل جعبه‌دنده",
            "دنده، حالت رانندگی و دمای گیربکس را می‌فرستد و درخواست کاهش گشتاور می‌دهد تا تعویض دنده نرم انجام شود."),
    "ICU": ("دستگاه نشانگر (پشت آمپر)",
            "کیلومتر، سفر، مصرف سوخت و چراغ‌های هشدار را جمع می‌کند و روی صفحه نمایش می‌دهد."),
    "PEPS": ("ورود و استارت بدون کلید",
            "تشخیص کلید در دست، تأیید مالکیت و اجازه استارت. سیگنال‌های Button و Authentication وضعیت کلید و احراز هویت را می‌گویند."),
    "TPMS": ("فشار باد چرخ‌ها",
            "فشار و دمای هر چرخ را گزارش می‌کند و لامپ هشدار باد را روشن می‌کند."),
    "ITPMS": ("فشار باد غیرمستقیم",
            "بدون سنسور داخل چرخ، از روی سرعت چرخ‌ها افت باد را حدس می‌زند."),
    "DIAG": ("درخواست تشخیص عیب",
            "فریم‌های درخواست UDS/OBD را می‌فرستد تا ECUها پاسخ عیب و شناسه بدهند."),
    "ICN": ("کلاستر / صفحه نشانگر",
            "روی شبکه کم‌سرعت، وضعیت چراغ‌ها، سفر، دمای آب و تنظیمات نمایش را می‌فرستد."),
    "HVAC": ("تهویه و کولر",
            "وضعیت کولر، دمای تنظیم‌شده، سرعت فن و وضعیت دریچه‌ها را گزارش می‌کند."),
    "MMS": ("چندرسانه‌ای",
            "نسخه نرم‌افزار، پروفایل صوتی و درخواست‌های دیاگ خودش را می‌فرستد."),
    "RBG": ("رادیو و بلوتوث",
            "وضعیت رادیو، پخش و اتصال بلوتوث را گزارش می‌کند."),
}

# --------------------------------------------------------------------------- #
# token glossary: English name piece -> (Persian, note)
# The note is only used when the token is meaningful on its own.
# --------------------------------------------------------------------------- #
TOKENS = {
    # node / block ids
    "abs": ("ABS", "کنترل ترمز و پایداری"),
    "ems": ("EMS", "مدیریت موتور"),
    "eps": ("EPS", "فرمان برقی"),
    "epas": ("EPAS", "فرمان برقی"),
    "esc": ("ESC", "کنترل پایداری"),
    "tcu": ("TCU", "جعبه‌دنده"),
    "icu": ("ICU", "دستگاه نشانگر"),
    "peps": ("PEPS", "ورود بدون کلید"),
    "tpms": ("TPMS", "فشار باد چرخ"),
    "itpms": ("ITPMS", "فشار باد غیرمستقیم"),
    "diag": ("دیباگ", "تشخیص عیب"),
    "icn": ("ICN", "کلاستر"),
    "hvac": ("HVAC", "تهویه و کولر"),
    "mms": ("MMS", "چندرسانه‌ای"),
    "rbg": ("RBG", "رادیو و بلوتوث"),
    "nbcm": ("NBCM", "بدنه و شبکه"),
    "bcm": ("BCM", "کنترل بدنه"),
    "sas": ("SAS", "سنسور زاویه فرمان"),
    "imm": ("IMM", "ایموبیلایزر"),
    "immo": ("IMMO", "ایموبیلایزر"),

    # what the value is
    "counter": ("شمارنده", "با هر ارسال یکی زیاد می‌شود؛ گیرنده از پرشِ آن بسته‌شدن فریم را می‌فهمد"),
    "cnt": ("شمارنده", "با هر ارسال یکی زیاد می‌شود"),
    "tgccounter": ("شمارنده TGC", "شمارنده محافظت از پیام"),
    "rollcntr": ("شمارنده چرخشی", "شمارنده‌ای که تا سقف می‌رود و صفر می‌شود"),
    "checksum": ("چک‌سام", "جمع کنترلی برای تشخیص خرابی داده"),
    "crc": ("CRC", "کد تشخیص خطای داده"),
    "pcnt": ("شمارنده کارکرد", "تعداد دفعات وقوع"),

    # faults
    "fault": ("خطا", "وقتی ۱ شود یعنی آن بخش ایراد دارد"),
    "faultlamp": ("چراغ خطا", "روشن‌شدن لامپ هشدار در آمپر"),
    "faultlmp": ("چراغ خطا", "روشن‌شدن لامپ هشدار"),
    "error": ("خطا", ""),
    "err": ("خطا", ""),
    "failure": ("خرابی", ""),
    "invalid": ("نامعتبر", "مقدار فعلی معتبر نیست و نباید استفاده شود"),
    "absent": ("غایب", "نبودن یا قطع‌بودن مؤلفه"),
    "loss": ("از دست رفتن", "قطع ارتباط با آن بخش"),
    "comloss": ("قطع ارتباط", "گیرنده دیگر فریم این ECU را نمی‌بیند"),
    "com": ("ارتباط", ""),
    "busoff": ("Bus Off", "کنترلر CAN از باس جدا شده و تا ریست برنمی‌گردد"),
    "bus": ("باس", ""),
    "timeout": ("تایم‌اوت", "طولانی‌شدن فاصله فریم‌ها"),
    "warn": ("هشدار", ""),
    "warning": ("هشدار", ""),
    "alarm": ("آلارم", ""),
    "alarmlamp": ("چراغ هشدار", "لامپ قرمز/زرد هشدار روی آمپر"),
    "dtc": ("کد عیب DTC", "شناسه خطای ذخیره‌شده"),
    "uds": ("UDS", "پروتکل تشخیص عیب"),
    "diagnostic": ("تشخیص عیب", ""),
    "diagmode": ("حالت دیباگ", "حالت سرویس/تشخیص"),

    # states
    "active": ("فعال", "در این لحظه کار می‌کند"),
    "static": ("ثابت", ""),
    "dynamic": ("پویا", ""),
    "state": ("وضعیت", ""),
    "states": ("وضعیت", ""),
    "status": ("وضعیت", ""),
    "st": ("وضعیت", ""),
    "mode": ("حالت", ""),
    "on": ("روشن", ""),
    "off": ("خاموش", ""),
    "set": ("تنظیم", ""),
    "change": ("تغییر", ""),
    "enable": ("فعال‌سازی", ""),
    "disable": ("غیرفعال", ""),
    "disablestatus": ("وضعیت غیرفعالی", ""),
    "ind": ("نشانگر", ""),
    "indication": ("نشانگر", ""),
    "valid": ("معتبر", "۱ یعنی مقدار قابل استفاده است"),
    "progress": ("در حال انجام", ""),

    # commands
    "req": ("درخواست", "این ECU از دیگری کاری می‌خواهد"),
    "request": ("درخواست", ""),
    "resp": ("پاسخ", "جواب درخواست رسیده"),
    "response": ("پاسخ", ""),
    "answer": ("پاسخ", ""),
    "chall": ("چالش", "چالش احراز هویت برای کلید"),
    "auth": ("احراز هویت", ""),
    "dialog": ("دیالوگ", "تبادل پیام برای تأیید دسترسی"),
    "command": ("فرمان", ""),
    "cmd": ("فرمان", ""),
    "learnskreq": ("درخواست یادگیری کلید", ""),
    "teachpinreq": ("درخواست تعریف پین", ""),
    "teachskreq": ("درخواست تعریف کلید", ""),
    "reset": ("ریست", "شروع دوباره و صفرشدن مقادیر"),
    "maint": ("نگهداری", ""),
    "test": ("تست", ""),

    # vehicle data
    "speed": ("سرعت", "km/h"),
    "vehiclespeed": ("سرعت خودرو", "km/h"),
    "wheel": ("چرخ", ""),
    "wheelspeed": ("سرعت چرخ", "km/h"),
    "rpm": ("دور موتور", "RPM"),
    "gear": ("دنده", ""),
    "gearshiftinhibit": ("ممانعت تعویض دنده", "در این وضعیت تعویض دنده مجاز نیست"),
    "clutchpedalstatus": ("وضعیت پدال کلاچ", "۰ رها، ۱ نیم‌فشرده، ۲ فشرده"),
    "brakepedalstatus": ("وضعیت پدال ترمز", "۰ رها، ۱ نیم‌فشرده، ۲ فشرده"),
    "virtualaccpedal": ("پدال گاز مجازی", "درصد فشردن پدال"),
    "accpedal": ("پدال گاز", ""),
    "torque": ("گشتاور", "Nm یا درصد"),
    "enginethrottleposition": ("موقعیت دریچه گاز", "درصد"),
    "engineintakeairtemp": ("دمای هوای ورودی", "درجه"),
    "engineactualtorque": ("گشتاور واقعی موتور", "درصد"),
    "enginefrictiontorque": ("گشتاور اصطکاکی موتور", "درصد"),
    "enginestatus": ("وضعیت موتور", ""),
    "catalyst": ("کاتالیست", ""),
    "heating": ("گرم‌کن", ""),
    "cycle": ("چرخه", ""),
    "drivingcycle": ("چرخه رانندگی", "دور رانندگی از ایدل تا جاده"),
    "fuel": ("سوخت", ""),
    "cng": ("CNG", "سوخت گاز"),
    "tank": ("باک", ""),
    "temp": ("دما", "درجه سانتی‌گراد"),
    "temperature": ("دما", "درجه سانتی‌گراد"),
    "pressure": ("فشار", ""),
    "pressureinvalid": ("فشار نامعتبر", ""),
    "odo": ("کیلومتر کل", ""),
    "mileage": ("مسافت", ""),
    "dist": ("مسافت", ""),
    "trip1": ("سفر ۱", "کیلومترشمار قابل صفر کردن"),
    "trip2": ("سفر ۲", "کیلومترشمار قابل صفر کردن"),
    "hour": ("ساعت", ""),
    "hours": ("ساعت", ""),
    "hourmeter": ("ساعت‌شمار", ""),
    "minutes": ("دقیقه", ""),
    "seconds": ("ثانیه", ""),
    "date": ("تاریخ", ""),
    "time": ("زمان", ""),
    "day": ("روز", ""),
    "month": ("ماه", ""),
    "year": ("سال", ""),
    "yawrate": ("نرخ چرخش حول محور عمودی", "deg/s"),
    "pitchangle": ("زاویه پیچ", "درجه"),
    "rollangle": ("زاویه رول", "درجه"),
    "longacceleration": ("شتاب طولی", "m/s²"),
    "longaccelerationvalid": ("اعتبار شتاب طولی", ""),
    "sensor": ("سنسور", ""),
    "position": ("موقعیت", ""),
    "tp": ("موقعیت دریچه", "درجه"),
    "inside": ("داخل", ""),
    "key": ("کلید", ""),
    "lamp": ("چراغ", "لامپ روی آمپر"),
    "backlight": ("نور پس‌زمینه", ""),
    "low": ("کم", ""),
    "level": ("سطح", ""),
    "num": ("تعداد", ""),
    "n": ("تعداد", ""),
    "index": ("شماره", ""),
    "id": ("شناسه", ""),
    "ident": ("شناسه", ""),
    "info": ("اطلاعات", ""),
    "data": ("داده", ""),
    "msg": ("پیام", "متن یا شناسه پیام"),
    "message": ("پیام", ""),
    "tab": ("جدول", "جدول داده داخل نرم‌افزار"),
    "edition": ("نسخه", ""),
    "ver": ("نسخه", ""),
    "version": ("نسخه", ""),
    "network": ("شبکه", ""),
    "frame": ("فریم", ""),
    "dig1": ("دیجیتال ۱", ""),
    "dig2": ("دیجیتال ۲", ""),
    "unit1": ("واحد ۱", ""),
    "unit2": ("واحد ۲", ""),
    "unit3": ("واحد ۳", ""),
    "nas": ("NAS", "شبکه‌ای‌نشدن"),
    "nm": ("مدیریت شبکه", "فریم‌های بیدارباش و خواب"),
    "nb": ("نویز باس", ""),
    "nerr": ("خطای شبکه", ""),
    "ctl": ("کنترل", ""),
    "func": ("عملکرد", ""),
    "absesp": ("ABS/ESP", ""),
    "sup": ("پشتیبان", "فریم نظارتی"),
    "broadcast": ("همگانی", "برای همه ECUها"),
    "ssb": ("SSB", ""),
    "gsi": ("نشانگر تعویض دنده", ""),
    "tco": ("TCO", ""),
    "mcylinder": ("چندسیلندر", ""),
    "road": ("جاده", ""),
    "finder": ("یابنده", ""),
    "pas": ("فرمان کمکی", ""),
    "ecu": ("ECU", "کنترل‌کننده"),
    "sw": ("کلید", "سوئیچ نرم‌افزاری"),
    "tx": ("ارسال", "این گره فرستنده است"),
    "button": ("دکمه", ""),
    "learnt": ("یادگرفته", ""),
    "brake": ("ترمز", ""),
    "mcylinder": ("سیلندر اصلی", ""),
    "emergbrakestatus": ("وضعیت ترمز اضطراری", ""),
    "escdisablestatus": ("وضعیت غیرفعالی ESC", ""),
    "escerror": ("خطای ESC", ""),
    "hacactive": ("فعال بودن HAC", "کمک در سربالایی"),
    "hacerror": ("خطای HAC", ""),
    "tcsactive": ("فعال بودن TCS", "کنترل کشش"),
    "tcsdisablestatus": ("وضعیت غیرفعالی TCS", ""),
    "tcserror": ("خطای TCS", ""),
    "torqreductvalid": ("اعتبار کاهش گشتاور", ""),
    "torquereducttype": ("نوع کاهش گشتاور", ""),
    "torquereductvalue": ("مقدار کاهش گشتاور", ""),
    "esp": ("ESP", "کنترل پایداری"),
    "cruise": ("کروز", "کنترل سرعت ثابت"),
    "ac": ("کولر", ""),
    "gasp": ("پدال گاز", ""),
    "ctl": ("کنترل", ""),
    "networkmanagement": ("مدیریت شبکه", "فریم‌های بیدارباش و خواب باس"),
    "management": ("مدیریت", ""),
    "ebd": ("EBD", "توزیع الکترونیکی ترمز"),
    "tcs": ("TCS", "کنترل کشش"),
    "hac": ("HAC", "کمک شروع در سربالایی"),
    "vaccumpump": ("پمپ خلأ", ""),
    "maxbrktorq": ("حداکثر گشتاور ترمز", ""),
    "engtorqloss": ("افت گشتاور موتور", ""),
    "enginefulecutoff": ("قطع سوخت موتور", ""),
    "accpedalerror": ("خطای پدال گاز", ""),
    "airconditioncommand2": ("فرمان کولر ۲", ""),
    "gearengagedstatus": ("وضعیت درگیر بودن دنده", ""),
    "indicatedenginetorque1": ("گشتاور نشان‌داده‌شده ۱", ""),
    "mileage": ("مسافت", ""),
    "f": ("F", ""),
}

# messages that need a specific sentence; anything else is explained by tokens
MSG_INFO = {
    "HS_ID_ABS": "وضعیت کلی ABS: فعال بودن، حالت دیباگ و چراغ‌های خطا.",
    "HS_ID_ABS_BRAKE": "وضعیت پدال ترمز، فشار ترمز و درگیری ترمز اضطراری.",
    "HS_ID_ABS_ESP_SUP": "فریم نظارتی ABS/ESP: خطا، قطع ارتباط و شمارنده Bus Off.",
    "HS_ID_EMS1": "داده‌های اصلی موتور: دور، پدال گاز و کلاچ، گشتاور و درصد بار.",
    "HS_ID_EPS1": "وضعیت فرمان برقی و گشتاور کمکی.",
    "HS_ID_EMS_RESET_RESP": "پاسخ موتور به درخواست ریست.",
}

UNIT_NOTE = {
    "km/h": "کیلومتر بر ساعت",
    "%": "درصد",
    "°C": "درجه سانتی‌گراد",
    "deg": "درجه",
    "rpm": "دور بر دقیقه",
    "Nm": "نیوتن‌متر",
    "bar": "بار",
    "V": "ولت",
    "mA": "میلی‌آمپر",
    "km": "کیلومتر",
    "L": "لیتر",
    "s": "ثانیه",
}

KIND_NOTE = {
    "bool": "دو حالته: ۰ = خاموش/غیرفعال، ۱ = روشن/فعال",
    "enum": "چندحالته؛ معنی هر عدد در DBC تعریف می‌شود",
    "num": "عددی",
}

_CACHE: dict | None = None


def _clean_tokens(signal: str, node: str) -> list[str]:
    """Split a signal name into lower-case tokens, dropping the net and node prefix."""
    name = re.sub(r"^(Hs|Ls)(_ID)?_", "", signal, flags=re.I)
    parts = [p for p in re.split(r"[_\.]", name) if p]
    if parts and parts[0].lower() == node.lower().replace(" ", ""):
        parts = parts[1:]
    return [p.lower() for p in parts]


def _split_camel(token: str) -> list[str]:
    """``brakepedalstatus1`` -> ['brake','pedal','status','1'] using the glossary."""
    if token in TOKENS:
        return [token]
    out, i = [], 0
    low = token.lower()
    while i < len(low):
        for j in range(len(low), i, -1):
            if low[i:j] in TOKENS:
                out.append(low[i:j])
                i = j
                break
        else:
            # no known piece here: take a single character to avoid an endless loop
            out.append(low[i])
            i += 1
    return out


def explain(sig: dict) -> dict:
    """Build the explanation record for one signal."""
    node, msg, name = sig["node"], sig["msg"], sig["sig"]
    node_fa, node_note = NODE_INFO.get(node, (node, ""))

    pieces, notes = [], []
    for raw in _clean_tokens(name, node):
        for tok in _split_camel(raw):
            if tok.isdigit():
                continue
            if tok in TOKENS:
                fa, note = TOKENS[tok]
                if fa not in pieces:
                    pieces.append(fa)
                if note and note not in notes:
                    notes.append(note)

    # a name piece the glossary does not know (Ac_Gasp) is not invented: such a
    # record gets free text instead, and says so.
    free = bool(pieces) and len(pieces) <= 1 and len(_clean_tokens(name, node)) > 1
    title = " · ".join(pieces) if pieces else name

    facts = [f"گره: {node} — {node_fa}", f"پیام: {msg}"]
    if sig.get("cycle"):
        facts.append(f"چرخه ارسال: هر {sig['cycle']} میلی‌ثانیه")
    facts.append(f"شبکه: {'HS (High-Speed)' if sig['net'] == 'HS' else 'LS (Low-Speed)'}")
    facts.append(KIND_NOTE.get(sig["kind"], "عددی"))
    if sig["kind"] != "bool":
        unit = sig["unit"] or "بدون واحد"
        rng = f"{_fmt(sig['min'])} تا {_fmt(sig['max'])}"
        facts.append(f"بازه: {rng} {unit}".strip())
    else:
        facts.append("بازه: ۰ یا ۱")
    if sig.get("def") not in (None, ""):
        facts.append(f"مقدار پیش‌فرض: {_fmt(sig['def'])}")

    msg_note = MSG_INFO.get(msg)
    if not msg_note:
        msg_note = f"فریم {msg} که {node} روی شبکه {sig['net']} می‌فرستد."
    if node_note:
        msg_note += f" {node_note}"

    if free:
        title = f"{name} — {node}"
        msg_note = (f"{node_fa} این سیگنال را در فریم {msg} می‌فرستد. نامش در مجموعه"
                    f" داده اصلی توضیح داده نشده، پس معنی بیت‌به‌بیت آن را نمی‌سازیم؛"
                    f" فقط مشخصات فنی همین فریم و بازه مقدار معتبر است.")
    return {
        "title": title,
        "name": name,
        "node": node,
        "nodeTitle": node_fa,
        "message": msg,
        "net": sig["net"],
        "cycle": sig.get("cycle") or 0,
        "kind": sig["kind"],
        "unit": sig["unit"] or "",
        "min": sig["min"],
        "max": sig["max"],
        "about": msg_note,
        "free": free,
        "notes": notes,
        "facts": facts,
    }


def _fmt(v) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return str(int(f)) if f == int(f) else f"{f:.3f}".rstrip("0").rstrip(".")


def build() -> dict:
    """All explanations, keyed by the signal id (node:message:signal)."""
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    data = json.loads(MAP.read_text(encoding="utf-8"))
    out = {"nodes": {}, "signals": {}}
    for node, (fa, note) in NODE_INFO.items():
        out["nodes"][node] = {"title": fa, "about": note}
    # 21 signal names appear in two messages (LS_ICN_ODO is carried by both
    # LS_ID_DENA_ODO_IC and LS_ID_ICNI2_IC), so the key is name + message.
    for sig in data["signals"]:
        out["signals"][sig["id"]] = explain(sig)
    _CACHE = out
    return out


def tooltip_text(rec: dict, limit: int = 1000) -> str:
    """One-line text for a CANoe tooltip: what it is, then the facts."""
    head = f"{rec['title']} — {rec['node']} / {rec['message']}"
    body = [rec["about"]] + rec["notes"] + rec["facts"]
    text = head + "\n" + "\n".join(b for b in body if b)
    if len(text) > limit:                       # a tooltip has to stay readable
        text = text[: limit - 1].rstrip() + "…"
    return text


def write_outputs() -> Path:
    """Write the JSON and the .js twin the HTML tester loads (file:// has no fetch)."""
    recs = build()
    payload = {"meta": {"source": "tools/signal_glossary.py",
                        "note": "built from signal names + metadata; the OEM "
                                "Comment column is empty for all 1078 signals",
                        "count": len(recs["signals"])},
               "nodes": recs["nodes"], "signals": recs["signals"]}
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    OUT_JS.write_text(
        "/* AUTO-GENERATED by tools/signal_glossary.py - do not edit by hand.\n"
        "   Explanations for every signal, shown by the (i) button in the tester. */\n"
        "window.NBCM_DESCRIPTIONS = "
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8")
    return OUT_JSON


if __name__ == "__main__":
    write_outputs()
    recs = build()
    sigs = recs["signals"]
    with_notes = sum(1 for r in sigs.values() if r["notes"])
    generic = [n for n, r in sigs.items() if not r["notes"]]
    print(f"wrote {OUT_JSON.relative_to(ROOT)} and {OUT_JS.relative_to(ROOT)}")
    print(f"signals explained : {len(sigs)}")
    print(f"with extra notes  : {with_notes} ({with_notes / len(sigs):.0%})")
    print(f"title from tokens : {sum(1 for r in sigs.values() if r['title'] != r['name'])}")
    print(f"\nno note beyond the fact line: {len(generic)}")
    for n in generic[:10]:
        print(f"   {n}  ->  {sigs[n]['title']}")
    print("\n--- three examples ---")
    for n in list(sigs)[:1] + list(sigs)[100:101] + list(sigs)[300:301]:
        r = sigs[n]
        print(f"\n{n}\n  title : {r['title']}\n  about : {r['about']}")
        print("  notes : " + " | ".join(r["notes"]))
        print("  facts : " + " | ".join(r["facts"]))

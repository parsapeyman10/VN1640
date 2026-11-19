#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
signal_states.py -- what each value of a signal *means* and *does*
==================================================================

The first version of the explanations said what a signal is ("EMS · خطا") and
listed its metadata.  That is not enough: a user staring at a panel needs to know
what happens when the value is 0 and what happens when it is 1, what moves it,
and what to look at in the Trace when it moves.

Nothing in the source data defines those meanings
-------------------------------------------------
Checked, not assumed: the network map exported from the official databases has
no `VAL_` table for any of the 1078 signals, and its Comment column is empty.
A DBC value table is the only thing that states "0 = released, 1 = pressed"
authoritatively, and it is not in the files we have.

So each entry below carries an honest `conf`:

  * ``mechanical`` -- true by construction, no interpretation involved:
    a boolean is 0/1, a counter increments, a checksum is a checksum, a
    physical range maps to its unit.
  * ``convention`` -- read from the signal's name and the naming rules these
    databases follow (``*_Lamp``, ``*_COM_LOSS``, ``*_Nerr`` ...).  It is how
    these signals behave on Stellantis/TARA-style networks, but it is an
    interpretation, and the UI says so on every such line.

If a real DBC with `VAL_` tables arrives, ``load_val_tables()`` reads it and those
definitions win over everything here.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# --------------------------------------------------------------------------- #
# value tables, if a real .dbc is dropped in
# --------------------------------------------------------------------------- #
def load_val_tables(dbc_path: Path | None = None) -> dict[str, dict[int, str]]:
    """Read ``VAL_ <id> <signal> <n> "text" ... ;`` lines from a DBC.

    Returns ``{signal name: {value: text}}``.  This is the only authoritative
    source of state meanings, so when it exists it is used instead of the
    conventions below.
    """
    import glob
    out: dict[str, dict[int, str]] = {}
    paths = [dbc_path] if dbc_path else [
        Path(p) for p in glob.glob(str(ROOT / "NBCM_CAN_Simulation_Package" / "**" / "*.dbc"),
                                   recursive=True)]
    for p in paths:
        if not p or not Path(p).exists():
            continue
        text = Path(p).read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r'^VAL_\s+\d+\s+(\w+)\s+(.+?);', text, re.M | re.S):
            name, body = m.group(1), m.group(2)
            vals = re.findall(r'(-?\d+)\s+"([^"]*)"', body)
            if vals:
                out[name] = {int(v): t for v, t in vals}
    return out


def _st(v: str, label: str, effect: str) -> dict:
    """One row of a state table."""
    return {"v": v, "label": label, "effect": effect}


# --------------------------------------------------------------------------- #
# the state model, by family
# --------------------------------------------------------------------------- #
# match() gets the bare signal name (Hs_/Ls_ prefix removed) and the record.
# Order matters: the first family that matches wins, so put the specific ones
# before the general ones.
FAMILIES: list[dict] = [

    # --- network management
    {
        "key": "nm",
        "match": r"(_nm_st|nm_state|network_management)",
        "name": "وضعیت مدیریت شبکه",
        "conf": "convention",
        "meaning": "وضعیت بیداری گره روی شبکه‌ی مدیریتی (NM): بیدار و در حال تبادل، یا خواب.",
        "states": [
            _st("0", "بیدار", "گره روی باس فعال است و فریم‌هایش را می‌فرستد"),
            _st("1", "خواب", "گره به خواب رفته؛ فریم‌های عادی‌اش قطع می‌شود و فقط NM می‌ماند"),
        ],
        "when": "بعد از بی‌حرکتی خودرو همه گره‌ها یکی‌یکی خواب می‌روند؛ با باز شدن در یا "
                "بیدار شدن NBCM دوباره بیدار می‌شوند.",
        "observe": "اگر گرهی خواب بماند و بیدار نشود، بقیه آن را «غایب» می‌بینند و "
                   "`*_NBCM_DYN_ABSENT` بالا می‌رود.",
        "test": "سوئیچ OFFLINE همان گره را بزنید؛ وضعیت NM آن باید ثابت بماند و بقیه به غیبت برسند.",
    },

    # --- supervision
    {
        "key": "absent",
        "match": r"(absent|_comloss|com_loss|_nerr|bus_error|_busoff|bus_off)",
        "name": "نظارت بر حضور گره",
        "conf": "convention",
        "meaning": "فرستنده‌ی این سیگنال نظارت می‌کند که طرف مقابل (معمولاً NBCM) به‌موقع فریم "
                   "می‌فرستد یا نه. این سیگنال نتیجه‌ی آن نظارت است.",
        "states": [
            _st("0", "سالم", "طرف مقابل به‌موقع می‌رسد؛ فرستنده در وضعیت عادی کار می‌کند"),
            _st("1", "غایب / قطع", "فرستنده فریم طرف مقابل را ندیده؛ وارد حالت جانشین (limp) می‌شود"),
        ],
        "when": "وقتی فاصله‌ی دو فریم طرف مقابل از حد مجاز (معمولاً چند صد میلی‌ثانیه) بیشتر شود.",
        "observe": "با قطع NBCM یا قطع گره‌ی مقابل، این بیت باید بعد از چند چرخه ۱ شود و "
                   "سیگنال‌های جانشین (مثل سرعت پیش‌فرض) فعال شوند.",
        "test": "در پنل گره‌ی مقابل را OFFLINE کنید و تایمر تب Monitor را تماشا کنید: ابتدا age بالا "
                "می‌رود، بعد این بیت ۱ می‌شود.",
    },

    # --- fault flag
    {
        "key": "fault",
        "match": r"(error|fault|failure|invalid|err|defaut)",
        "name": "پرچم خطا",
        "conf": "convention",
        "meaning": "این سیگنال می‌گوید آن بخش سالم است یا ایراد دارد. معمولاً تشخیص داخلیِ "
                   "خودِ ECU پشت آن است، نه ورودی راننده.",
        "states": [
            _st("0", "سالم", "بخش مربوطه کار می‌کند؛ هیچ پیام خطایی روی آمپر نمی‌آید"),
            _st("1", "خطا", "ECU خطا را تشخیص داده؛ ممکن است چراغ هشدار روشن کند و "
                            "مقدار جانشین بفرستد"),
        ],
        "when": "با تشخیص خودِ ECU (قطع سنسور، مقدار خارج از محدوده، خطای داخلی).",
        "observe": "در Trace وقتی این بیت ۱ می‌شود، معمولاً چند سیگنال دیگر همان فریم هم "
                   "مقدار جانشین می‌گیرند — همان لحظه را نگاه کنید.",
        "test": "این بیت را دستی ۱ کنید و ببینید کدام چراغ/سیگنال پایین‌دستی در پنل NBCM عوض می‌شود.",
    },

    # --- warning lamp
    {
        "key": "lamp",
        "match": r"(lamp|lmp|_mil\b|warninglight)",
        "name": "چراغ هشدار آمپر",
        "conf": "convention",
        "meaning": "فرمان روشن/خاموش شدن یک لامپ روی صفحه‌ی نشانگر. مسیرش معمولاً "
                   "ECU ← ICN ← لامپ است.",
        "states": [
            _st("0", "خاموش", "لامپ خاموش است؛ راننده چیزی نمی‌بیند"),
            _st("1", "روشن", "لامپ روشن است؛ راننده هشدار را می‌بیند و ممکن است بوق/پیام هم بیاید"),
        ],
        "when": "وقتی ECU مربوطه خطا یا شرایط هشدار را تشخیص دهد، یا در تست زمانی که شما "
                "دستی ۱ می‌کنید.",
        "observe": "چراغ در پنل به‌صورت LED نمایش داده می‌شود؛ اگر LED سبز شد ولی لامپ واقعی "
                   "روشن نشد، مشکل در مسیر ICN است نه در این سیگنال.",
        "test": "برای دیدن اثر، در تب همان گره NBCM کلید LED را بزنید و در Trace ببینید آیا بیت "
                "مربوطه در فریم ICN هم همان لحظه ۱ می‌شود.",
    },

    # --- multi-level warning
    {
        "key": "warning",
        "match": r"(warning|warn|alarm|_indication|opindication)",
        "name": "هشدار (چندسطحی)",
        "conf": "convention",
        "meaning": "شدت هشدار؛ بیشتر از دو حالت دارد و معنی هر عدد به جدول مقدار همان DBC "
                   "بستگی دارد.",
        "states": [
            _st("0", "بی‌هشدار", "هیچ هشداری فعال نیست"),
            _st("1", "هشدار سطح ۱", "هشدار ملایم؛ معمولاً پیام روی صفحه، بدون بوق"),
            _st("2", "هشدار سطح ۲", "هشدار جدی‌تر؛ ممکن است بوق و لامپ زرد"),
            _st("3", "هشدار بحرانی", "لامپ قرمز و بوق؛ راننده باید اقدام کند"),
        ],
        "when": "با شدت گرفتن شرایط (مثلاً فشار باد که کم و کم‌تر می‌شود).",
        "observe": "وقتی از ۱ به ۳ می‌رود، معمولاً یک سیگنال «فعال بودن» جدا هم ۱ می‌شود.",
        "test": "مقادیر ۰ تا بیشینه را پشت‌سرهم بنویسید و ببینید کدام سطح، کدام LED/پیام را "
                "روشن می‌کند.",
    },

    # --- function active
    {
        "key": "active",
        "match": r"(_active|active$|_enable|enable$|_act\b)",
        "name": "فعال بودن یک عملکرد",
        "conf": "convention",
        "meaning": "می‌گوید آن عملکرد همین حالا در حال مداخله است یا نه — نه اینکه سالم است.",
        "states": [
            _st("0", "غیرفعال", "سیستم دخالت نمی‌کند؛ رفتار عادی خودرو"),
            _st("1", "فعال", "سیستم در همین لحظه دارد کار می‌کند (ترمز می‌گیرد، گشتاور کم می‌کند…)"),
        ],
        "when": "فقط در لحظه‌ی مداخله، مثلاً وقتی چرخ می‌لغزد یا پدال ترمز فشرده می‌شود.",
        "observe": "بر خلاف پرچم خطا، این بیت باید لحظه‌ای باشد؛ اگر همیشه ۱ بماند یعنی "
                   "یا مداخله ادامه دارد یا سیگنال گیر کرده.",
        "test": "در سناریوی رانندگی، لحظه‌ی ترمزگیری را در Trace ببینید: سرعت پایین می‌آید و "
                "همان بازه این بیت ۱ می‌شود.",
    },

    # --- pedal state
    {
        "key": "pedal",
        "match": r"(pedalstatus|pedal_status|brakepedal|clutchpedal)",
        "name": "وضعیت پدال",
        "conf": "convention",
        "meaning": "وضعیت پدال ترمز یا کلاچ به‌صورت چندحالته، نه فقط فشرده/رها.",
        "states": [
            _st("0", "رها", "پدال آزاد است؛ کروز و استارت بدون کلید مجاز"),
            _st("1", "فشرده", "پدال تا ته فشرده شده"),
            _st("2", "نیمه", "پدال کمی فشرده؛ برخی ECUها این حالت را «نامعتبر» می‌گیرند"),
            _st("3", "نامعتبر", "دو سنسور پدال با هم نمی‌خوانند؛ ECU خطا ثبت می‌کند"),
        ],
        "when": "با فشردن/رها کردن پدال توسط راننده یا سناریو.",
        "observe": "پرش از ۰ به ۳ (بدون دیدن ۱ یا ۲) یعنی دو سوئیچ پدال ناهماهنگ‌اند — "
                   "همان چیزی که ECU به‌عنوان خطای سنسور ثبت می‌کند.",
        "test": "۰ و ۳ را پشت‌سرهم بگذارید و ببینید کدام سیگنال خطا در همان فریم یا فریم بعدی ۱ می‌شود.",
    },

    # --- gear
    {
        "key": "gear",
        "match": r"(gear|gsi)",
        "name": "دنده",
        "conf": "convention",
        "meaning": "دنده‌ی درگیر یا درخواست دنده. معنی دقیق هر عدد به جدول مقدار DBC وابسته است.",
        "states": [
            _st("0", "پارک (P)", "خودرو پارک است؛ قفل فرمان آزاد"),
            _st("1", "دنده عقب (R)", "چراغ دنده عقب روشن، دوربین فعال"),
            _st("2", "خلاص (N)", "گشتاور به چرخ نمی‌رسد"),
            _st("3", "دنده جلو (D)", "دنده‌ی درایو؛ خودرو حرکت می‌کند"),
            _st("4..7", "دنده‌های دستی/دیگر", "بسته به گیربکس؛ در DBC تعریف می‌شود"),
        ],
        "when": "با تعویض دنده توسط راننده یا فرمان TCU.",
        "observe": "در حین تعویض دنده، TCU معمولاً هم‌زمان درخواست کاهش گشتاور می‌دهد؛ "
                   "آن دو را با هم ببینید.",
        "test": "دنده را از ۰ به ۳ تغییر دهید و ببینید سرعت و دور در سناریو واکنش می‌دهند یا نه.",
    },

    # --- reset request
    {
        "key": "reset",
        "match": r"(reset|req_reset)",
        "name": "درخواست ریست",
        "conf": "convention",
        "meaning": "یک گره از گره‌ی دیگر می‌خواهد مقادیر/وضعیتش را از نو شروع کند. این یک "
                   "فرمان است، نه گزارش وضعیت.",
        "states": [
            _st("0", "بدون درخواست", "هیچ ریستی خواسته نشده"),
            _st("1", "درخواست فعال", "گیرنده باید مقدار خودش را صفر/از نو کند"),
        ],
        "when": "هنگام تعریف کلید، پاک کردن سفر، یا بازیابی بعد از خطا.",
        "observe": "این بیت معمولاً یک چرخه ۱ می‌ماند و برمی‌گردد؛ اگر ۱ بماند گیر کرده است.",
        "test": "۱ کنید و ببینید کدام مقدار (کیلومتر سفر، شمارنده…) صفر می‌شود.",
    },

    # --- diagnosis
    {
        "key": "diag",
        "match": r"(diag|uds|dtc|diagnostic)",
        "name": "کانال تشخیص عیب",
        "conf": "convention",
        "meaning": "درخواست یا پاسخ تشخیصی (UDS/OBD). این‌ها داده‌ی عادی خودرو نیستند؛ "
                   "ابزار تست با آن‌ها با ECU حرف می‌زند.",
        "states": [
            _st("0", "بی‌فعالیت", "هیچ درخواست/پاسخی روی این کانال نیست"),
            _st("1", "فعال", "یک درخواست تشخیصی در جریان است؛ ECU باید پاسخ بدهد"),
        ],
        "when": "وقتی ابزار دیاگ وصل شود یا خودرو در حالت سرویس باشد.",
        "observe": "اگر این بیت ۱ بماند و پاسخ نیاید، ECU در حالت دیاگ گیر کرده و "
                   "ممکن است فریم‌های عادی‌اش را کم کند.",
        "test": "درخواست را ۱ کنید و پاسخ (`*_DIAG_RESP`) را در Trace ببینید.",
    },

    # --- authentication
    {
        "key": "auth",
        "match": r"(auth|learn|learnt|teach|chall|immo|immobil)",
        "name": "احراز هویت و تعریف کلید",
        "conf": "convention",
        "meaning": "جریان تأیید مالکیت کلید: چالش، پاسخ، نتیجه. تعریف کلید جدید هم از همین "
                   "مسیر انجام می‌شود.",
        "states": [
            _st("0", "تأیید نشده", "کلید شناسایی نشده؛ استارت و باز کردن قفل ممکن نیست"),
            _st("1", "در جریان", "چالش رد و بدل شده و منتظر پاسخ است"),
            _st("2+", "تأیید شده", "کلید معتبر است؛ خودرو اجازه‌ی استارت می‌دهد"),
        ],
        "when": "با نزدیک شدن کلید، فشردن دکمه‌ی استارت، یا شروع فرآیند تعریف کلید.",
        "observe": "اگر چند ثانیه در «در جریان» بماند، یعنی پاسخ طرف مقابل نرسیده — "
                   "همان‌جا را در Trace دنبال کنید.",
        "test": "توالی ۰ ← ۱ و بعد نتیجه را دستی ۰ بگذارید تا مسیر خطا را ببینید.",
    },

    # --- tyre pressure
    {
        "key": "tpms",
        "match": r"(tire|tyre|tpms|itpms)",
        "name": "وضعیت فشار باد",
        "conf": "convention",
        "meaning": "وضعیت هر چرخ: سالم، کم‌باد، نشتی، یا باتری سنسور. شدت آن در چند سطح می‌آید.",
        "states": [
            _st("0", "سالم", "فشار در محدوده؛ هیچ هشداری نیست"),
            _st("1", "هشدار ملایم", "باد کم شده؛ لامپ زرد"),
            _st("2", "نشتی", "افت سریع فشار؛ هشدار فوری"),
            _st("3+", "بحرانی/خطای سنسور", "فشار خیلی کم یا سنسور بی‌پاسخ"),
        ],
        "when": "با افت فشار واقعی، یا در تست وقتی مقدار فشار را پایین می‌آورید.",
        "observe": "افت فشار باید هم‌زمان با بالا رفتن دما یا کاهش فشار همان چرخ بیاید، "
                   "وگرنه سنسور مشکل دارد نه لاستیک.",
        "test": "فشار یک چرخ را زیر حد ببرید؛ ببینید لامپ TPMS چند سطح بعد روشن می‌شود.",
    },

    # --- climate
    {
        "key": "hvac",
        "match": r"(hvac|_ac_|_sht_|aircondition|blower)",
        "name": "تهویه و کولر",
        "conf": "convention",
        "meaning": "وضعیت یا فرمان کولر/بخاری: روشن بودن کمپرسور، سرعت فن، وضعیت دریچه.",
        "states": [
            _st("0", "خاموش", "کمپرسور/فن خاموش است"),
            _st("1", "روشن", "کمپرسور یا فن در حال کار است (بار موتور بالا می‌رود)"),
        ],
        "when": "با فشردن کلید A/C یا تغییر دمای تنظیم‌شده.",
        "observe": "روشن شدن کولر معمولاً در EMS هم دیده می‌شود (درخواست افزایش دور بی‌کاری).",
        "test": "کلید A/C را ۱ کنید و ببینید دور موتور در سناریو کمی بالا می‌رود یا نه.",
    },

    # --- service reminder
    {
        "key": "maintenance",
        "match": r"(maint|change_oil|change_airf|service_)",
        "name": "یادآور سرویس",
        "conf": "convention",
        "meaning": "می‌گوید وقت تعویض روغن/فیلتر رسیده یا نه. معمولاً از کیلومتر و زمان "
                   "محاسبه می‌شود و در حافظه می‌ماند.",
        "states": [
            _st("0", "سرویس لازم نیست", "تا موعد بعدی فاصله هست"),
            _st("1", "سرویس لازم است", "پیام «تعویض روغن» روی صفحه می‌آید و تا ریست می‌ماند"),
        ],
        "when": "با رسیدن کیلومتر به حد، یا با درخواست ریست سرویس.",
        "observe": "این بیت بعد از ۱ شدن خودش برنمی‌گردد؛ فقط ریست آن را صفر می‌کند — "
                   "برخلاف پرچم‌های خطا.",
        "test": "۱ کنید، بعد `*_Maint_Reset_Req` را ۱ کنید و ببینید صفر می‌شود.",
    },

    # --- multi-frame transport
    {
        "key": "frameindex",
        "match": r"(frame_index|frame_nb|msg_tab|_tab_)",
        "name": "حمل چندفریمی",
        "conf": "convention",
        "meaning": "فریم‌های عیب/پیام بلند در چند بسته می‌آیند. این دو عدد می‌گویند این بسته "
                   "چندم از چند است.",
        "states": [
            _st("0..N", "شماره بسته", "با هم یعنی کدام تکه از پیام را می‌بینید"),
        ],
        "when": "فقط وقتی یک پیام بلند (مثل کد عیب یا متن) ارسال می‌شود.",
        "observe": "اگر بسته‌ها ناقص برسند، پیام مونتاژ نمی‌شود و در پنل خالی می‌ماند.",
        "test": "شماره را عوض کنید و ببینید متن/کد در پنل عوض می‌شود.",
    },

    # --- odometer
    {
        "key": "trip",
        "match": r"(trip|odometer|_odo|mileage|_dist)",
        "name": "کیلومترشمار",
        "conf": "mechanical",
        "meaning": "مسافت طی‌شده. سفرها با درخواست ریست صفر می‌شوند، کیلومتر کل معمولاً نه.",
        "states": [
            _st("0", "صفر", "سفر تازه ریست شده"),
            _st("*", "عددی", "با حرکت خودرو زیاد می‌شود؛ واحد کیلومتر"),
        ],
        "when": "با حرکت خودرو؛ ریست فقط با درخواست صریح.",
        "observe": "اگر با حرکت خودرو زیاد نشود ولی سرعت بالا باشد، یعنی همین سیگنال در "
                   "مسیر محاسبه مشکل دارد.",
        "test": "سناریوی رانندگی را اجرا کنید و ببینید عدد با سرعت بالا می‌رود.",
    },

    # --- speed
    {
        "key": "speed",
        "match": r"(vehiclespeed|_speed|wheelspeed|_vss|speed_)",
        "name": "سرعت",
        "conf": "mechanical",
        "meaning": "سرعت خودرو یا سرعت یک چرخ. یکی از پرکاربردترین سیگنال‌های شبکه است: "
                   "آمپر، ABS، گیربکس و کروز همه به آن نگاه می‌کنند.",
        "states": [
            _st("0", "ایست", "خودرو ساکن است"),
            _st("1..250", "در حرکت", "کیلومتر بر ساعت"),
        ],
        "when": "با حرکت خودرو یا سناریوی رانندگی.",
        "observe": "اگر سرعت بالا باشد ولی چرخ‌ها هم‌سرعت نباشند، ABS خطای سنسور چرخ می‌دهد.",
        "test": "در پنل مقدار را ۶۰ بگذارید و ببینید چه سیگنال‌های دیگری (دنده، دور) واکنش می‌دهند.",
    },

    # --- engine rpm
    {
        "key": "rpm",
        "match": r"(_rpm|engine_rpm|_speed_rpm)",
        "name": "دور موتور",
        "conf": "mechanical",
        "meaning": "دور میل‌لنگ در دقیقه. منبع اصلی آن EMS است.",
        "states": [
            _st("0", "خاموش", "موتور نمی‌چرخد"),
            _st("700..900", "دور بی‌کاری", "حالت عادی ایست"),
            _st("1000..6500", "در حرکت", "با پدال گاز و دنده بالا می‌رود"),
        ],
        "when": "با پدال گاز، دنده و بار موتور.",
        "observe": "دور بی‌کاریِ پرش‌دار یا صفر شدن ناگهانی، نشانه‌ی قطع فریم EMS است.",
        "test": "در سناریو ببینید دور با سرعت هم‌خوان است یا نه؛ اگر یکی جلو بیفتد، "
                "یکی از دو فریم تأخیر دارد.",
    },

    # --- temperature
    {
        "key": "temp",
        "match": r"(temp|temperature|_water|_coolant)",
        "name": "دما",
        "conf": "mechanical",
        "meaning": "دمای یک بخش (آب، هوا، گیربکس، سنسور). واحد و بازه در همان سیگنال آمده است.",
        "states": [
            _st("*", "عددی", "درجه سانتی‌گراد؛ بالا رفتن آن معمولاً هشدار دمای آب را فعال می‌کند"),
        ],
        "when": "با گرم شدن موتور در طول رانندگی.",
        "observe": "اگر دما از بازه بیرون بزند (مثلاً ۲۰۰ درجه)، سیگنال نامعتبر می‌شود و "
                   "ECU مقدار جانشین می‌گذارد.",
        "test": "دما را تا نزدیک بیشینه ببرید و ببینید چراغ هشدار آب روشن می‌شود.",
    },

    # --- pressure
    {
        "key": "pressure",
        "match": r"(pressure|_press|bar\b)",
        "name": "فشار",
        "conf": "mechanical",
        "meaning": "فشار یک مدار (ترمز، باد چرخ، روغن).",
        "states": [
            _st("*", "عددی", "با واحد همان سیگنال؛ بیرون از بازه یعنی سنسور یا مدار ایراد دارد"),
        ],
        "when": "با فشردن ترمز، تغییر باد چرخ، یا تغییر بار.",
        "observe": "فشار ثابت در حالی که ورودی عوض می‌شود، یعنی مسیر سنسور قطع است.",
        "test": "مقدار را در بازه تغییر دهید و سیگنال «معتبر بودن» همان فریم را ببینید.",
    },

    # --- torque
    {
        "key": "torque",
        "match": r"(torque|torq|_nm\b)",
        "name": "گشتاور",
        "conf": "mechanical",
        "meaning": "گشتاور موتور یا درخواست گشتاور از گیربکس. معمولاً درصدی یا نیوتن‌متر است.",
        "states": [
            _st("*", "عددی", "مثبت = کشش، منفی = ترمز موتور"),
        ],
        "when": "با پدال گاز، تعویض دنده (کاهش گشتاور)، و مداخله‌ی ESC.",
        "observe": "افت ناگهانی گشتاور بدون تغییر پدال، یعنی TCU یا ESC درخواست کاهش داده است.",
        "test": "درخواست کاهش گشتاور TCU را ۱ کنید و ببینید گشتاور واقعی پایین می‌آید.",
    },

    # --- counters
    {
        "key": "counter",
        "match": r"(counter|cnt|rollcntr|pcnt|tgccounter)$|_(counter|cnt)\b",
        "name": "شمارنده پیام",
        "conf": "mechanical",
        "meaning": "شمارنده‌ای که فرستنده با هر ارسال یک واحد بالا می‌برد و در انتها صفر می‌شود. "
                   "گیرنده از روی آن می‌فهمد فریم تازه است یا همان فریم قدیمی دوباره رسیده.",
        "states": [
            _st("*", "عددی", "هر ارسال +۱؛ اگر چند فریم پشت‌سرهم عدد ثابت بماند یعنی فرستنده گیر کرده"),
        ],
        "when": "با هر چرخه‌ی ارسال همان پیام تغییر می‌کند؛ به سناریو یا ورودی راننده ربطی ندارد.",
        "observe": "در Trace عدد باید پرش داشته باشد. اگر پرش نداشت ولی فریم می‌رسد، فرستنده‌اش "
                   "قفل شده — نمونه‌ی کلاسیک خطای نرم‌افزاری ECU.",
        "test": "در پنل یک گره را OFFLINE کنید: شمارنده‌ی آن گره صفر/ثابت می‌ماند و بقیه ادامه می‌دهند.",
    },

    # --- checksums
    {
        "key": "checksum",
        "match": r"(checksum|crc)",
        "name": "چک‌سام فریم",
        "conf": "mechanical",
        "meaning": "جمع کنترلی روی بایت‌های فریم. گیرنده آن را دوباره حساب می‌کند و اگر جور نشد، "
                   "کل فریم را دور می‌ریزد.",
        "states": [
            _st("*", "عددی", "هر تغییر داده در فریم، چک‌سام را هم عوض می‌کند"),
        ],
        "when": "هر بار که یکی از سیگنال‌های همان فریم عوض شود.",
        "observe": "اگر چک‌سام را دستی مقدار ثابت بدهید، گیرنده فریم را نامعتبر می‌بیند و "
                   "سیگنال‌های دیگرِ آن فریم هم بی‌اثر می‌شوند. برای تست این کار مفید است.",
        "test": "یک سیگنال دیگر از همان فریم را عوض کنید و ببینید چک‌سام همراه آن تغییر می‌کند.",
    },

    # --- clock / calendar (the dashboard's own time base)
    {
        "key": "clock",
        "match": r"(date_(day|month|year)|time_(hours|minutes|seconds)|_hour|_minute|_second)",
        "name": "ساعت و تاریخ",
        "conf": "mechanical",
        "meaning": "ساعت و تاریخ داخلی نشانگر. مقدارش روی نمایشگر می‌رود و در حافظه می‌ماند.",
        "states": [
            _st("*", "بازه", "هر عدد یک واحد واقعی است: ساعت ۰..۲۳، دقیقه و ثانیه ۰..۵۹، ماه ۱..۱۲، روز ۱..۳۱"),
        ],
        "when": "خودش بالا می‌رود. با خاموش شدن کامل برق ممکن است صفر شود یا از حافظه برگردد.",
        "observe": "اگر ساعت بعد از هر بار خاموش/روشن به صفر برگردد، بک‌آپ حافظه‌ی نشانگر کار نمی‌کند — یک خطای واقعی که در تست دوام دیده می‌شود.",
        "test": "مقدار را روی ۲۳:۵۹ بگذارید؛ بعد از یک دقیقه باید ۰۰:۰۰ و روز بعدی شود.",
    },

    # --- software version
    {
        "key": "version",
        "match": r"(version_(major|minor)|_sw_ver|software_version)",
        "name": "نسخه نرم‌افزار",
        "conf": "mechanical",
        "meaning": "شماره نسخه‌ی نرم‌افزار آن گره. ثابت است و فقط با فلش عوض می‌شود.",
        "states": [
            _st("*", "بازه", "major و minor کنار هم نسخه را می‌سازند"),
        ],
        "when": "هیچ چیز در حین کار آن را عوض نمی‌کند؛ اگر عوض شود یعنی گره ری‌فلش شده است.",
        "observe": "در شروع تست نسخه‌ها را ثبت کنید. تغییر غیرمنتظره یعنی کسی فایل را عوض کرده و نتیجه‌ی تست قبلی دیگر معتبر نیست.",
        "test": "مقدار را با نسخه‌ی اعلام‌شده در مستندات مقایسه کنید.",
    },

    # --- node identity on the bus
    {
        "key": "identity",
        "match": r"(ecu_num|_nas_cnt|sw_ident|backlight|_debug[0-9])",
        "name": "شناسه و تنظیمات گره",
        "conf": "convention",
        "meaning": "شناسه یا پارامتر ثابت یک گره (شماره ECU، شناسه نرم‌افزار، شدت نور پشت‌آمپر).",
        "states": [
            _st("*", "بازه", "عدد شناسه؛ معنای هر کد در جدول شبکه آمده، نه در نام سیگنال"),
        ],
        "when": "معمولاً ثابت است؛ نور پشت‌آمپر با دیمر یا چراغ‌ها عوض می‌شود.",
        "observe": "اگر شناسه‌ی دو گره یکی باشد، فریم‌ها قاطی می‌شوند و یکی از گره‌ها «غایب» دیده می‌شود در حالی که فیزیکاً وصل است.",
        "test": "شناسه‌ها را از Trace بردارید و با نقشه‌ی شبکه مقایسه کنید.",
    },

    # --- a function that can be switched off
    {
        "key": "disable",
        "match": r"(disable|_inhib|inhibit|_on_off)",
        "name": "غیرفعال بودن یک عملکرد",
        "conf": "convention",
        "meaning": "می‌گوید یک عملکرد عمداً خاموش شده است یا نه — که با «خراب بودن» فرق دارد.",
        "states": [
            _st("0", "فعال", "عملکرد اجازه‌ی کار دارد"),
            _st("1", "غیرفعال", "عملکرد عمداً کنار گذاشته شده؛ اگر لازم شود مداخله نمی‌کند"),
        ],
        "when": "با کلید خاموش‌کن، خطای یک سیستم دیگر، یا درخواست راننده.",
        "observe": "این را با پرچم خطا اشتباه نگیرید: غیرفعال بودن خطا نیست، ولی اگر بی‌دلیل ۱ بماند یعنی کسی خاموشش کرده و در تستِ عملکرد نتیجه منفی می‌گیرید.",
        "test": "کلید مربوطه را بزنید و ببینید این بیت و پرچم خطای همان سیستم چه رفتاری می‌کنند.",
    },

    # --- engine specific states
    {
        "key": "engine",
        "match": r"(engine|_rpm|catalyst|warmup|fuelcut|idle|_mil|starter|mono_bi_fuel|cruise)",
        "name": "وضعیت موتور",
        "conf": "convention",
        "meaning": "وضعیت کاری موتور: روشن/خاموش، بی‌کاری، قطع سوخت، گرم شدن، یا کاتالیست.",
        "states": [
            _st("0", "شرط برقرار نیست", "آن وضعیت فعال نیست"),
            _st("1", "شرط برقرار است", "موتور در آن وضعیت کار می‌کند"),
            _st(">1", "حالت چندسطحی", "اگر بازه بیشتر از ۱ است، کد وضعیت است و به جدول سازنده نیاز دارد"),
        ],
        "when": "با استارت، گاز، دمای موتور و درخواست کروز.",
        "observe": "برچسب‌هایی مثل CutOff یا WarmUp باید کوتاه و گذرا باشند؛ اگر یکی همیشه ۱ بماند یعنی شرطِ خروجش برقرار نمی‌شود.",
        "test": "سناریوی رانندگی را روشن کنید و ببینید در فاز شتاب و ترمز کدام وضعیت عوض می‌شود.",
    },

    # --- a value that only says whether a request is usable
    {
        "key": "validity",
        "match": r"(valid|_ctl\b|status$)",
        "name": "معتبر بودن یک مقدار",
        "conf": "convention",
        "meaning": "می‌گوید مقدار همراه آن قابل استفاده است یا نه — نه اینکه خودِ سیستم سالم است.",
        "states": [
            _st("0", "نامعتبر", "گیرنده باید مقدار را نادیده بگیرد و مقدار جانشین بگذارد"),
            _st("1", "معتبر", "مقدار قابل استفاده است"),
        ],
        "when": "وقتی محاسبه کامل شود، سنسور خطا بدهد، یا فرستنده مقدار را به‌روز نکند.",
        "observe": "اگر مقدار همراه معتبر است ولی عدد بی‌معنی است، مشکل در محاسبه است نه در این بیت. اگر نامعتبر شد، ببینید گیرنده چه مقدار جانشینی می‌گذارد.",
        "test": "سنسور مربوطه را قطع یا OFFLINE کنید و ببینید این بیت ۰ می‌شود و مقدار جانشین می‌آید.",
    },

    # --- switches the driver operates directly
    {
        "key": "driver_switch",
        "match": r"(ssb_sw|buttonst|switchst|doorlockreq|doorunlockreq|trunkreq|key_inside|brakeswitch|clutchswitch|driverbutton|passerngerbutton)",
        "name": "کلید یا سوئیچ راننده",
        "conf": "convention",
        "meaning": "وضعیت یک کلید که خود راننده یا سرنشین فشار می‌دهد (دکمه‌ی استارت، قفل در، پدال).",
        "states": [
            _st("0", "رها / باز", "کلید فشرده نشده است"),
            _st("1", "فشرده / بسته", "کلید همین حالا فعال است"),
        ],
        "when": "فقط با عمل راننده؛ در شبیه‌سازی با نوشتن دستی همان سیگنال.",
        "observe": "این بیت باید با رها کردن کلید به ۰ برگردد. اگر ۱ بماند، ECU فرمان را دائمی می‌بیند — مثلاً قفل در باز می‌ماند یا استارت تکرار می‌شود.",
        "test": "بیت را ۱ و بعد ۰ کنید و ببینید واکنش گره‌ی مقابل (قفل، روشن شدن، پیام) درست تکرار می‌شود.",
    },

    # --- position / driving mode
    {
        "key": "position",
        "match": r"(_tp_position|gear|shift|driver_?mode|powermode|syspowmode)",
        "name": "وضعیت یا موقعیت انتخاب‌شده",
        "conf": "convention",
        "meaning": "موقعیت انتخاب‌شده: دنده، حالت رانندگی، یا وضعیت تغذیه. یک کد گسسته است، نه عدد پیوسته.",
        "states": [
            _st("0", "حالت پایه", "پارک/خنثی یا کمترین حالت"),
            _st("1", "حالت دوم", "یک پله بالاتر از پایه؛ کدام حالت، بسته به همان سیگنال است"),
            _st(">1", "حالت‌های بعدی", "هر عدد یک موقعیت مشخص؛ ترتیبش را باید از جدول خودرو گرفت"),
        ],
        "when": "با اهرم دنده، دکمه‌ی حالت رانندگی، یا تغییر وضعیت برق.",
        "observe": "پرش مستقیم بین دو حالت دور (مثلاً ۰ به ۳ بدون عبور از ۱ و ۲) یعنی سیگنال یا کد عوض شده — همان‌جا را نگاه کنید.",
        "test": "حالت‌ها را یکی‌یکی عوض کنید و ببینید گره‌ی مقابل در هر حالت چه می‌کند.",
    },

    # --- generic yes/no when nothing more specific matched
    {
        "key": "flag",
        "match": r".",
        "name": "بیت وضعیت (۰/۱)",
        "conf": "convention",
        "meaning": "یک بیت ۰/۱ که نامش می‌گوید کدام وضعیت را نشان می‌دهد؛ معنای دقیق ۰ و ۱ در فایل DBC تعریف نشده است.",
        "states": [
            _st("0", "شرط برقرار نیست", "آن وضعیت یا درخواست فعال نیست"),
            _st("1", "شرط برقرار است", "آن وضعیت یا درخواست فعال است"),
        ],
        "when": "بسته به همان وضعیت؛ اگر در شبیه‌سازی حرکت نکند، ورودی‌اش وصل نیست.",
        "observe": "دو چیز را ببینید: آیا با عمل مربوطه عوض می‌شود، و آیا بعد از عمل به حالت اول برمی‌گردد. ماندن روی ۱ یعنی شرطِ بازگشت برقرار نمی‌شود.",
        "test": "عمل مربوطه را انجام دهید و همین بیت را در Trace تماشا کنید.",
    },

    # --- numeric fallback
    {
        "key": "numeric",
        "match": r".",          # fallback: must stay last
        "name": "مقدار عددی",
        "conf": "mechanical",
        "meaning": "یک کمیت عددی که فرستنده‌ی این پیام می‌فرستد. معنی دقیق هر عدد به جدول "
                   "مقدار DBC وابسته است.",
        "states": [
            _st("*", "عددی", "در بازه‌ی همان سیگنال؛ بیرون از بازه نامعتبر است"),
        ],
        "when": "بسته به نام سیگنال؛ در هر چرخه‌ی ارسال فریم.",
        "observe": "مقدار ثابت در حالی که ورودی عوض شده، یعنی مسیر این سیگنال قطع است.",
        "test": "مقدار را در دو انتهای بازه بگذارید تا ببینید مصرف‌کننده‌اش واکنش می‌دهد.",
    }
]
_BARE = re.compile(r"^(Hs|Ls)(_ID)?_", re.I)


def bare_name(sig: str) -> str:
    """``Hs_Abs_COM_Loss`` -> ``Abs_COM_Loss``."""
    return _BARE.sub("", sig)


def family_for(signal: str, kind: str, vmax: float) -> dict:
    """The state family that explains this signal."""
    bare = bare_name(signal)
    low = bare.lower()
    _PHYS = {"speed", "rpm", "temp", "pressure", "torque", "trip"}
    statusy = re.search(r"(status|state|mode|req|flag|ind|valid|st)$", low)
    for fam in FAMILIES:
        if re.search(fam["match"], low):
            if statusy and fam["key"] in _PHYS:
                # "Speed_limiterStatus" is about the limiter, not about speed
                for alt in FAMILIES:
                    if alt["key"] in ("flag", "validity"):
                        return alt
            return fam
    return FAMILIES[-1]


def _clip_states(states: list[dict], vmax: float) -> list[dict]:
    """Drop state rows that lie outside the signal's own enum range."""
    out = []
    for s in states:
        v = s["v"]
        if v == "*":
            out.append(s)
            continue
        m = re.match(r"^(\d+)", v)
        if m and float(m.group(1)) <= vmax:
            out.append(s)
    return out or states[:2]


def describe_states(signal: str, kind: str, vmin: float, vmax: float,
                    factor: float = 1.0, offset: float = 0.0,
                    unit: str = "") -> dict:
    """Everything the UI needs to show value semantics for one signal."""
    fam = family_for(signal, kind, vmax)
    states = fam["states"]
    # A table that names values the signal cannot take ("level 3" on a 0..1
    # signal) is wrong text, so the effect lines are trimmed to the real range:
    # the generic sentence survives, the invented level numbers do not.
    if kind == "bool" or (kind == "enum" and vmax <= 1):
        kept = [st for st in states if st["v"] in ("0", "1", "*")]
        fam = dict(fam)
        if len(kept) < 2:
            # the family describes levels this signal does not have; say ۰/۱ and
            # keep the family's own wording as the explanation of each side
            base = kept[0] if kept else states[0]
            other = "فعال / برقرار" if base["v"] == "0" else "غیرفعال / برقرار نیست"
            kept = [{"v": "0", "label": "شرط برقرار نیست",
                     "effect": base.get("effect") or "آن وضعیت فعال نیست"},
                    {"v": "1", "label": "شرط برقرار است",
                     "effect": (other if base["v"] == "1" else base.get("effect") or
                                "آن وضعیت فعال است")}]
        fam["states"] = kept
        if len(states) > 2:
            # the prose described levels this signal cannot reach
            fam["meaning"] = "این سیگنال فقط دو حالت دارد: ۰ و ۱."
            fam["observe"] = ""
        elif fam.get("observe") and re.search(r"[۲-۹]|سطح|بحرانی", fam["observe"]):
            # talks about levels this signal cannot reach: keep the actionable
            # half of the sentence instead of dropping the effect entirely
            first = re.split(r"[؛.]", fam["observe"])[0].strip()
            fam["observe"] = (first + ".") if len(first) > 25 else ""
        states = fam["states"]
    elif kind == "enum":
        fam = dict(fam)
        fam["states"] = _clip_states(states, vmax)
        states = fam["states"]
    scaled_early = abs(factor - 1.0) > 1e-12 or abs(offset) > 1e-12
    if kind == "num":
        # A numeric signal has no discrete states, so the table is one range row.
        # The tooltip drops it when its tail already prints "خام .. → ..".
        lo, hi = (vmin * factor + offset, vmax * factor + offset) if scaled_early \
            else (vmin, vmax)
        states = [_st(f"{lo:g} .. {hi:g}", "بازه",
                      "هر عددی در این بازه معتبر است؛ بیرون از آن مقدار جانشین می‌آید"
                      + (f" — مقدار فیزیکی با واحد {unit}" if scaled_early and unit else ""))]
    # The workbook's Min/Max are RAW values while Factor/Offset convert to the
    # physical value with the stated unit, so both are reported: "0..4095 raw"
    # is right and "0..4095 Km/h" is not (no wheel spins that fast).
    scaled = abs(factor - 1.0) > 1e-12 or abs(offset) > 1e-12
    phys = None
    if scaled:
        lo, hi = vmin * factor + offset, vmax * factor + offset
        phys = {"min": round(lo, 4), "max": round(hi, 4), "unit": unit,
                "factor": factor, "offset": offset}

    # No separate "what to watch" sentence?  The per-value effects already say
    # what each state does, so they become the effect line rather than nothing.
    observe = fam.get("observe") or ""
    if not observe and states:
        bits = [f"{st['v']} → {st['effect']}" for st in states[:2] if st.get("effect")]
        observe = " · ".join(bits)

    return {
        "key": fam["key"],
        "family": fam["name"],
        "conf": fam["conf"],
        "meaning": fam["meaning"],
        "states": states,
        "raw": {"min": vmin, "max": vmax},
        "physical": phys,
        "when": fam.get("when", ""),
        "observe": observe,
        "test": fam.get("test", ""),
    }


if __name__ == "__main__":
    import json
    data = json.loads((ROOT / "can_tester" / "assets" / "signal_map.json")
                      .read_text(encoding="utf-8"))
    vals = load_val_tables()
    print(f"value tables found in .dbc files: {len(vals)}")
    from collections import Counter
    fams = Counter()
    for s in data["signals"]:
        d = describe_states(s["sig"], s["kind"], s["min"], s["max"])
        fams[d["family"]] += 1
    print(f"\n{len(fams)} families cover {sum(fams.values())} signals:")
    for k, v in fams.most_common():
        print(f"  {v:4}  {k}")
    print("\n--- examples ---")
    for name in ("Hs_Eps_COM_Loss", "Hs_Abs_Esp_Warning", "Hs_Abs_VehicleSpeed",
                 "Hs_Ems_BrakePedalStatus1", "Ls_Icn_Stop_Lamp", "Hs_Abs_Counter"):
        found = [x for x in data["signals"] if x["sig"] == name]
        if not found:
            continue
        s = found[0]
        d = describe_states(s["sig"], s["kind"], s["min"], s["max"])
        print(f"\n{name}  [{d['family']} / {d['conf']}]")
        print("  " + d["meaning"])
        for st in d["states"]:
            print(f"    {st['v']:>8} = {st['label']:22} {st['effect']}")

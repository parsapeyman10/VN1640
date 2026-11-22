#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scenario_help.py -- what each control and each scenario actually does
=====================================================================

The first explanation pass described signals.  It did not answer the question a
user asks with their hand on a switch: *what will happen if I flip this?*

Every entry here is written from what the code really does, not from intent:

  * the four scenario phases and their timings come from the constants at the
    top of ``NBCM_Full_Restbus_Simulation.can`` (SPEED_URBAN 50, SPEED_HIGHWAY
    110, T_IDLE 3000 ms, T_URBAN 10000 ms, T_HIGHWAY 15000 ms, accel 1.25 and
    decel 1.75 km/h per 10 ms tick), read by ``_scenario_constants()`` so this
    text cannot quietly drift away from the CAPL;
  * the OFFLINE behaviour comes from the ``if (OFFLINE_X) return;`` guards that
    wrap every sender function;
  * DRIVE_MODE comes from NBCM_TesterBridge.can.

Each item carries ``kind``: ``switch`` (value you set), ``scenario`` (something
that runs on its own) or ``readout`` (value you only watch).
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAPL = ROOT / "NBCM_Full_Restbus_Simulation.can"


def _scenario_constants() -> dict:
    """Read the scenario timings out of the CAPL, so the text stays true."""
    out = {"urban": 50.0, "highway": 110.0, "t_idle": 3000,
           "t_urban": 10000, "t_highway": 15000, "accel": 1.25, "decel": 1.75}
    if not CAPL.exists():
        return out
    text = CAPL.read_text(encoding="utf-8", errors="replace")
    wanted = {"SPEED_URBAN": "urban", "SPEED_HIGHWAY": "highway",
              "T_IDLE_MS": "t_idle", "T_URBAN_MS": "t_urban",
              "T_HIGHWAY_MS": "t_highway", "ACCEL_RATE": "accel",
              "DECEL_RATE": "decel"}
    for name, key in wanted.items():
        m = re.search(rf"{name}\s*=\s*([\d.]+)", text)
        if m:
            out[key] = float(m.group(1)) if "." in m.group(1) else int(m.group(1))
    return out


def _s(v) -> str:
    """Persian-friendly number: whole numbers without a decimal tail."""
    return str(int(v)) if float(v) == int(v) else f"{v:g}"


def scenario_help() -> dict:
    """All page-level help: scenarios, switches, readouts, nodes, tabs."""
    c = _scenario_constants()

    scenario = [
        {
            "id": "SCENARIO_RUNNING",
            "title": "سناریوی رانندگی (چرخه‌ی شهری/جاده‌ای)",
            "kind": "switch",
            "states": [
                {"v": "1", "label": "روشن", "effect": "باس یک خودروی در حال حرکت را می‌بیند؛ "
                 "سرعت و دور موتور خودکار بالا و پایین می‌روند"},
                {"v": "0", "label": "خاموش", "effect": "سرعت روی همان مقدار می‌ماند؛ اگر "
                 "MANUAL_SPEED_MODE هم ۰ باشد، خودرو ایست است"},
            ],
            "how": (
                f"چهار فاز پشت سر هم: {_s(c['t_idle']/1000)} ثانیه ایست (دور {_s(800)})، "
                f"شتاب تا {_s(c['urban'])} km/h در شهر، {_s(c['t_urban']/1000)} ثانیه ثابت روی "
                f"{_s(c['urban'])}، شتاب تا {_s(c['highway'])}، {_s(c['t_highway']/1000)} ثانیه "
                f"ثابت روی {_s(c['highway'])}، بعد ترمز تا ایست. شتاب "
                f"{_s(c['accel'])} km/h در هر ۱۰ms و ترمز {_s(c['decel'])} است."
            ),
            "effect": (
                "با روشن شدنش این‌ها هم‌زمان تغییر می‌کنند: سرعت خودرو، دور موتور، دنده، "
                "کیلومتر کل و سفر، و در ادامه چراغ‌های وابسته به سرعت. اگر در Trace فقط "
                "سرعت عوض شود ولی دور نه، یعنی فریم EMS جدا از فریم ABS می‌رسد."
            ),
            "watch": "تب Dashboard (گیج سرعت و دور) و تب Monitor (سن همه‌ی پیام‌ها).",
            "caution": "اگر DRIVE_MODE = ۱ باشد، خروجی تستر روی خروجی سناریو می‌نشیند و "
                       "ممکن است مقدار سناریو دیده نشود. برای دیدن سناریو، DRIVE_MODE = ۰ بگذارید.",
        },
        {
            "id": "MANUAL_SPEED_MODE",
            "title": "سرعت دستی",
            "kind": "switch",
            "states": [
                {"v": "1", "label": "روشن", "effect": f"سناریو کنار می‌رود و سرعت همان "
                 f"MANUAL_SPEED_KMH می‌شود؛ مقدار ثابت می‌ماند"},
                {"v": "0", "label": "خاموش", "effect": "کنترل به سناریو (یا ایست) برمی‌گردد"},
            ],
            "how": "سناریو در هر تیک ۱۰ms اول MANUAL_SPEED_MODE را چک می‌کند؛ اگر ۱ باشد "
                   "همان عدد را می‌گذارد و فازها را جلو نمی‌برد.",
            "effect": "سرعت ثابت می‌ماند، دور موتور هم روی مقدار متناسب همان سرعت قفل "
                      "می‌شود. کیلومترشمار با همان سرعت بالا می‌رود.",
            "watch": "عدد MANUAL_SPEED_KMH را عوض کنید و ببینید گیج سرعت در همان تیک "
                     "جابه‌جا می‌شود.",
            "caution": "برای دیدن اثر، SCENARIO_RUNNING را هم روشن بگذارید؛ وگرنه هیچ‌کدام "
                       "سرعت را نمی‌نویسند.",
        },
        {
            "id": "MANUAL_SPEED_KMH",
            "title": "مقدار سرعت دستی",
            "kind": "value",
            "states": [
                {"v": "0", "label": "ایست", "effect": "خودرو ساکن؛ دور روی بی‌کاری می‌ماند"},
                {"v": f"1..{_s(c['highway']+40)}", "label": "در حرکت", "effect":
                 "کیلومتر بر ساعت؛ روی سرعت خودرو، دور موتور و کیلومترشمار اثر می‌گذارد"},
            ],
            "how": "فقط وقتی MANUAL_SPEED_MODE = ۱ خوانده می‌شود.",
            "effect": "همان مسیر سرعت سناریو را می‌رود، پس همه‌ی مصرف‌کننده‌های سرعت "
                      "(آمپر، ABS، گیربکس) با هم عوض می‌شوند.",
            "watch": "اگر عدد را بیرون از بازه بگذارید، سیگنال نامعتبر می‌شود و "
                     "`VehicleSpeed_Invalid` باید ۱ شود.",
            "caution": "این عدد سرعت واقعی خودرو را در پنل NBCM عوض نمی‌کند اگر "
                       "DRIVE_MODE = ۱ باشد؛ در آن حالت تستر اولویت دارد.",
        },
        {
            "id": "DRIVE_MODE",
            "title": "مالکیت باس (restbus یا تستر)",
            "kind": "switch",
            "states": [
                {"v": "0", "label": "restbus", "effect": "سناریو صاحب سیگنال‌هاست؛ "
                 "نوشتن دستی از پنل/HTML روی باس نمی‌رود"},
                {"v": "1", "label": "تستر", "effect": "هر مقدار شما از پنل یا HTML "
                 "مستقیم روی فریم می‌نشیند و سناریو کنار می‌رود"},
            ],
            "how": "در NBCM_TesterBridge.can خوانده می‌شود؛ پل هم همان را به HTML "
                   "گزارش می‌دهد.",
            "effect": "تعیین می‌کند کدام مقدار برنده است. اگر فکر می‌کنید سوئیچ کار "
                      "نمی‌کند، اول این را چک کنید — نه سوئیچ را.",
            "watch": "در HTML نشانگر «دستی/باس» کنار هر سیگنال همین وضعیت را می‌گوید.",
            "caution": "با DRIVE_MODE = ۱، سناریو هم‌چنان محاسبه می‌شود ولی مقدارش "
                       "بازنویسی می‌شود؛ برای دیدن سناریو آن را ۰ کنید.",
        },
    ]

    switches = [
        {
            "id": "OFFLINE_<NODE>",
            "title": "قطع یک گره از باس",
            "kind": "switch",
            "states": [
                {"v": "0", "label": "وصل", "effect": "گره همه‌ی فریم‌هایش را طبق "
                 "cycle time می‌فرستد"},
                {"v": "1", "label": "قطع", "effect": "همه‌ی تابع‌های Send آن گره "
                 "بی‌درنگ برمی‌گردند؛ هیچ فریمی از آن نمی‌رسد"},
            ],
            "how": "هر تابع ارسال با `if (OFFLINE_<NODE>) return;` شروع می‌شود، پس "
                   "قطع شدن کامل و آنی است — نه کم‌کم.",
            "effect": (
                "در گره‌ی مقصد: سن پیام‌ها بالا می‌رود، بعد از حدود نیم ثانیه پرچم "
                "`*_COM_LOSS` یا `*_ABSENT` طرف مقابل ۱ می‌شود و مقادیر جانشین فعال "
                "می‌شوند. اگر گره‌ای که قطع کرده‌اید فرستنده‌ی سرعت باشد، آمپر و گیربکس "
                "هم مقدار پیش‌فرض می‌گیرند."
            ),
            "watch": "تب Monitor: عدد age برای آن گره بالا می‌رود و LED قرمز می‌شود.",
            "caution": "قطع کردن EMS و ABS با هم، بیشترین شباهت را به «خودروی خاموش» "
                       "دارد؛ برای تست سناریوهای واقعی، یکی‌یکی قطع کنید.",
        },
        {
            "id": "SCENARIO_RESET",
            "title": "ریست سناریو",
            "kind": "value",
            "states": [
                {"v": "*", "label": "دکمه", "effect": "فاز به ایست و زمان‌ها به صفر "
                 "برمی‌گردد"},
            ],
            "how": "در HTML دکمه‌ی ریست کنار «سناریوی رانندگی»؛ همان مقدار "
                   "SCENARIO_RUNNING را ۰ و ۱ نمی‌کند، فقط فاز را صفر می‌کند.",
            "effect": "سرعت به ۰ و دور به بی‌کاری برمی‌گردد، بعد چرخه از فاز ایست شروع "
                      "می‌شود.",
            "watch": "اگر سناریو «گیر کرده» بود (مثلاً سرعت روی ۱۱۰ ماند)، این را بزنید.",
            "caution": "ریست کردن سناریو، OFFLINE گره‌ها را برنمی‌گرداند.",
        },
    ]

    readouts = [
        {"id": "HB_<NODE>", "title": "قلب تپنده‌ی گره",
         "kind": "readout",
         "states": [{"v": "1", "label": "زنده", "effect": "فریم این گره در ۵۰۰ms گذشته دیده شده"},
                    {"v": "0", "label": "مرده", "effect": "فریمی نرسیده؛ گره قطع است"}],
         "how": "شمارنده‌ی ۱۰۰ms سلامت را از سن آخرین فریم می‌سازد.",
         "effect": "فقط نمایش است؛ چیزی را کنترل نمی‌کند.",
         "watch": "برای دیدن OFFLINE یک گره، این سریع‌ترین نشانه است.",
         "caution": "خاموش بودن این LED همیشه یعنی قطع گره نیست؛ اگر اندازه‌گیری "
                    "متوقف باشد همه خاموش می‌شوند."},
        {"id": "AGE_<NODE>", "title": "سن آخرین فریم",
         "kind": "readout",
         "states": [{"v": "0..500", "label": "سالم", "effect": "در محدوده‌ی عادی"},
                    {"v": ">500", "label": "مشکوک", "effect": "دیرتر از cycle time رسیده"},
                    {"v": "بزرگ", "label": "قطع", "effect": "گره فرستنده نیست"}],
         "how": "هر ۱۰۰ms به‌روز می‌شود.",
         "effect": "فقط نمایش؛ مقدار آن معیار تایم‌اوت شماست.",
         "watch": "برای تست تایم‌اوت واقعی، همین عدد را در تب Monitor تماشا کنید.",
         "caution": "عدد همیشه یک تیک عقب است؛ انتظار دقت میلی‌ثانیه‌ای نداشته باشید."},
        {"id": "TC_RESULT_PASS / FAIL", "title": "نتیجه‌ی آخرین اجرای تست",
         "kind": "readout",
         "states": [{"v": "۰", "label": "هیچ", "effect": "تستی اجرا نشده یا همه رد شده‌اند"},
                    {"v": "n", "label": "تعداد", "effect": "شمارش پاس/رد همان اجرا"}],
         "how": "پل بعد از هر اجرای suite مقدارها را می‌نویسد (POST /api/verdict).",
         "effect": "فقط گزارش؛ روی باس اثری ندارد.",
         "watch": "این‌ها را در تب Tests پنل ببینید تا مطمئن شوید اجرای HTML به CANoe رسیده.",
         "caution": "اگر HTML تست اجرا کند ولی این‌ها صفر بمانند، پل به CANoe وصل نیست — "
                    "همان‌جا را در تب Link چک کنید."},
    ]

    tabs = [
        {"id": "Dashboard", "title": "داشبورد",
         "what": "گیج سرعت و دور، سوئیچ‌های سناریو و DRIVE_MODE، و سلامت ۱۳ گره."},
        {"id": "Nodes", "title": "گره‌ها",
         "what": "قطع/وصل هر گره با توضیح اثرش، و تعداد پیام/سیگنال هر گره."},
        {"id": "Monitor", "title": "پایش",
         "what": "جدول سن و قلب تپنده — جای دیدن تایم‌اوت واقعی."},
        {"id": "Tests", "title": "تست‌ها",
         "what": "شمارنده‌های PASS/FAIL و وضعیت مالکیت باس؛ اجرای کامل در HTML."},
        {"id": "<NODE>", "title": "تب هر گره",
         "what": "همه‌ی سیگنال‌های آن گره با مقدار، بازه و کنترل نوشتن؛ "
                 "علامت (i) روی هر سطر."},
    ]

    return {"scenario": scenario, "switches": switches, "readouts": readouts,
            "tabs": tabs, "constants": c}


if __name__ == "__main__":
    import json
    h = scenario_help()
    print("constants read from CAPL:", json.dumps(h["constants"], ensure_ascii=False))
    for section in ("scenario", "switches", "readouts"):
        print(f"\n=== {section} ({len(h[section])})")
        for item in h[section]:
            print(f"  {item['id']:28} {item['title']}")
            for st in item["states"]:
                print(f"      {st['v']:>10} = {st['label']:12} {st['effect'][:60]}")

# VN1640 — شبکه CAN خودرو (NBCM دنا)

شبیه‌سازی شبکه و **تستر HTML برای CANoe 12**.

## محتویات

| مسیر | توضیح |
|---|---|
| `NBCM_Full_Restbus_Simulation.can` | شبیه‌سازی کامل restbus هر ۱۳ گره (CAPL، CANoe 12) |
| `NBCM_Panel_Binding_Reference.xlsx` | مرجع بایندینگ پنل — **منبع حقیقت** سیگنال‌ها (۴۸۱ سیگنال / ۹۷ پیام) |
| `can_tester/` | **تستر HTML** — یک صفحه، بدون build step |
| `bridge/` | پل Python ↔ CANoe (COM) + رانر headless برای CI |
| `canoe/` | فایل‌های تولیدشده‌ی سمت CANoe: `.vsysvar`، نود CAPL پل و `panels/*.xvp` (۱۵ پنل) |
| `tools/` | تولید داده و کد از اکسل |
| `docs/README.md` | **راهنمای کامل تستر** (معماری، شروع سریع، عیب‌یابی) |
| `docs/how-to-add-to-canoe.md` | **افزودن پنل/متغیرها داخل CANoe 12** (همان دیالوگ Add Panel) |
| `tests/test_suite.json` | سوئیت تست مشترک بین مرورگر و CI |

## شروع در ۶۰ ثانیه (بدون CANoe)

```bash
python tools/build_data.py
python bridge/nbcm_bridge.py --sim
# مرورگر: http://127.0.0.1:8771/
```

## شروع با CANoe 12

```bash
pip install pywin32
python tools/build_capl.py
python bridge/nbcm_bridge.py --canoe --canoe-config "C:\CANoe\NBCM\NBCM.cfg"
```

سپس در CANoe فایل `canoe/NBCM_Test.vsysvar` را اضافه کنید و
`canoe/NBCM_TesterBridge.can` را به نود restbus بدهید. جزئیات: [`docs/README.md`](docs/README.md).

روی ویندوز: `bridge\run_windows.bat` (با CANoe) یا `bridge\run_sim.bat` (بدون CANoe).

## نکته‌ی مهم درباره‌ی «داخل CANoe»

CANoe 12 صفحه‌ی HTML را native نمایش نمی‌دهد و add-in API برای پنجره‌ی سفارشی ندارد
(این امکان در نسخه‌های بعدی آمد). بنابراین تستر در یک پنجره‌ی app-mode مرورگر
(`bridge/nbcm_window.py`) کنار CANoe و با گزینه‌ی always-on-top باز می‌شود؛ داده از طریق
پل و System Variables به باس می‌رسد. این محدودیت و دلیل انتخاب معماری در
[`docs/README.md`](docs/README.md#۱-واقعیتهای-canoe-12-که-طراحی-را-تعیین-کرد) توضیح داده شده است.

## پیش‌نیازها

- **بدون CANoe:** Python 3.9+ (فقط stdlib) و یک مرورگر مدرن.
- **با CANoe:** همان + CANoe 12 و `pywin32` روی ویندوز.

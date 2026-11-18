# NBCM CAN Tester — راهنمای کامل (CANoe 12)

تستر تست به‌صورت **یک اپلیکیشن HTML** ساخته شده که هم می‌تواند تنها با شبیه‌ساز داخلی کار کند،
هم از طریق یک پل سبک به **CANoe 12** و باس واقعی وصل شود. تمام تعریف‌های سیگنال/پیام/گره از
همان فایل مرجع شما (`NBCM_Panel_Binding_Reference.xlsx`) تولید می‌شوند، پس با تغییر DBC فقط
دوباره تولید می‌کنید و تستر با داده‌ی جدید بالا می‌آید.

---

## ۱) واقعیت‌های CANoe 12 که طراحی را تعیین کرد

قبل از هر چیز، سه نکته‌ی مستند و مهم — چون روی انتخاب معماری اثر مستقیم دارند:

| پرسش | پاسخ در CANoe 12 | نتیجه برای ما |
|---|---|---|
| آیا CANoe 12 می‌تواند یک صفحه HTML را **native** نمایش دهد؟ | **نه.** Panel Designer فقط کنترل‌های آماده (گیج، LED، سوئیچ، …) دارد و کنترل مرورگر/WebView ندارد. | HTML باید در یک پنجره‌ی کنار CANoe باز شود (`nbcm_window.py`). |
| آیا CANoe 12 **Add-in API** برای پنجره‌ی سفارشی دارد؟ | **نه.** مدل add-in/پنجره‌ی dockable در نسخه‌های بعدی اضافه شد. | به‌جای add-in از «پنجره‌ی app-mode مرورگر + always-on-top» استفاده می‌کنیم. |
| آیا COM می‌تواند مستقیم متغیرهای CAPL را بنویسد؟ | **نه.** COM سیگنال روی باس را می‌خواند/می‌نویسد، اما `long OFFLINE_ABS` یا `double Hs_Abs_VehicleSpeed` داخل CAPL از بیرون قابل نوشتن نیست. | مسیر مطمئن: **System Variable** + یک نود CAPL کوچک که آن‌ها را به restbus منتقل می‌کند. |

پس معماری «مدرن» و در عین حال قابل اتکا این است:

```
┌──────────────────────┐        WebSocket / HTTP         ┌────────────────────────┐
│  HTML Tester         │  <──────────────────────────>   │  nbcm_bridge.py        │
│  (index.html)        │      JSON، بدون وابستگی        │  Python 3، stdlib only │
└──────────────────────┘                                 └───────────┬────────────┘
                                                                     │ COM (pywin32)
                                                                     ▼
                                                          ┌────────────────────────┐
                                                          │  CANoe 12              │
                                                          │  NBCM_Test::<signal>   │
                                                          │  NBCM_TesterBridge.can │
                                                          │  restbus CAPL          │
                                                          └───────────┬────────────┘
                                                                     │ CAN
                                                                     ▼
                                                          ┌────────────────────────┐
                                                          │  VN1640A · NBCM (DUT)  │
                                                          └────────────────────────┘
```

---

## ۲) شروع سریع (بدون CANoe — برای طراحی تست)

```bash
# ۱. داده را از اکسل تولید کن (فقط وقتی اکسل/DBC عوض شد)
python tools/build_data.py

# ۲. پل را در حالت شبیه‌سازی بالا بیاور
python bridge/nbcm_bridge.py --sim

# ۳. مرورگر
#    http://127.0.0.1:8771/
```

روی ویندوز فقط `bridge\run_sim.bat` را دوبار کلیک کنید.
حالت Simulator کامل و خودبسنده است: سناریوی رانندگی، قطع/وصل گره، مانیتور Timeout و **همه‌ی
تست‌ها** بدون CANoe اجرا می‌شوند.

## ۳) شروع با CANoe 12 و باس واقعی

```bash
pip install pywin32
python tools/build_capl.py                       # ساخت vsysvar + CAPL
python bridge/nbcm_bridge.py --canoe --canoe-config "C:\CANoe\NBCM\NBCM.cfg"
```

کارهای یک‌باره در CANoe:

1. `canoe/NBCM_Test.vsysvar` را به کانفیگ اضافه کنید (Environment → System Variables → Import).
   راه جایگزین: `python tools/install_sysvars.py --save`
2. `canoe/NBCM_TesterBridge.can` را به **همان نود** restbus اضافه کنید
   (یا در `NBCM_Full_Restbus_Simulation.can` با `#include` صدا بزنید).
3. پنل‌ها: **Home → Panel → Add Panel…** و انتخاب `canoe/panels/NBCM_Smoke.xvp`
   سپس `NBCM_Test_Overview.xvp` — راهنمای کامل: [`how-to-add-to-canoe.md`](how-to-add-to-canoe.md).
4. استفاده روزمره و نوشتن تست: [`how-to-use.md`](how-to-use.md)
5. نسخهٔ PDF همهٔ مستندات: [`pdf/README.md`](pdf/README.md)
3. اگر نام کانال‌ها فرق دارد: تب «اتصال» → «نگاشت کانال» را پر کنید (HS/LS).
4. در تستر روی نشانگر **«کنترل: CANoe»** کلیک کنید تا `DRIVE_MODE=1` شود
   (یعنی تستر مالک سیگنال‌ها می‌شود؛ با کلیک دوباره به سناریوی CANoe برمی‌گردد).

### قرارداد سیگنال‌ها (مهم)

| System Variable | معنی |
|---|---|
| `NBCM_Test::<SignalName>` | مقدار همان سیگنال (۴۸۱ عدد) |
| `NBCM_Test::OFFLINE_<NODE>` | ۱ = آن گره دیگر روی باس نمی‌فرستد |
| `NBCM_Test::DRIVE_MODE` | ۰ = سناریوی CANoe مالک است، ۱ = تستر مالک است |
| `NBCM_Test::SCENARIO_RUNNING` / `MANUAL_SPEED_MODE` / `MANUAL_SPEED_KMH` | کنترل سناریوی رانندگی |

این متغیرها همان چیزی هستند که در Panel Designer هم با نوع `System Variable` قابل بایند شدن‌اند؛
لیست آماده در `canoe/panel_binding_systemvars.csv`.

---

## ۴) تستر چه می‌کند

**تب پنل کنترل** — هر ۴۸۱ سیگنال با کنترل مناسب (سوئیچ/اسلایدر/عدد/enum)، جستجو،
فیلتر «فقط Override»، «آزادسازی همه»، سناریوی رانندگی مشترک (سرعت/دور/سوخت/ODO) که
واقعاً روی باس نوشته می‌شود، و کارت اندازه‌گیری زنده.

**تب گره‌ها** — ۱۳ گره، قطع/وصل هر گره (`OFFLINE_*`)، و جدول **Echo/Timeout** با سن
هر پیام بر اساس `2.5 × cycle time`.

**تب تست‌ها** — اجرای تست‌ها با ورдикт PASS/FAIL/INCONC، اجرای همه/انتخاب‌شده/فقط FAILها،
لاگ زنده.

**تب سناریوها** — ویرایشگر JSON با اعتبارسنجی (نام سیگنال ناموجود را همان‌جا می‌گیرد)،
ذخیره محلی، ورود/خروج فایل.

**تب گزارش** — گزارش با شناسه اجرا/اپراتور/DUT، خروجی **JSON** و **JUnit XML** (برای CI).

### انواع step در سناریو

```jsonc
{ "wait": 500 }                                                   // انتظار
{ "settle": 350 }                                                 // همان wait، برای خوانایی
{ "set": { "Hs_Abs_VehicleSpeed": 60 } }                          // نوشتن سیگنال
{ "set": { "$offline": { "ABS": true } } }                        // قطع گره
{ "expect": { "signal": "Hs_Abs_Active", "op": "==", "value": 1 } }
{ "expect": { "offline": "ABS" } }   { "expect": { "online": "ABS" } }
{ "expect": { "fresh": "HS_ID_ABS", "within": 2000 } }            // Timeout
{ "expect": { "absent": "HS_ID_ABS", "within": 2500 } }
{ "require": { "signal": "Hs_Ems_Rpm", "op": ">", "value": 700, "timeout": 3000 } }
```

اپراتورها: `==  !=  >  >=  <  <=  ~=  exists  notexists`

---

## ۵) اجرای بدون مرورگر (CI)

همان `tests/test_suite.json` را می‌شود headless اجرا کرد — مناسب Jenkins/GitLab/Azure:

```bash
python bridge/run_suite.py --suite tests/test_suite.json \
       --bridge http://127.0.0.1:8771 \
       --take-control \
       --junit reports/junit.xml --report-dir reports
```

کد خروج: `0` = همه PASS، `1` = حداقل یک FAIL، `2` = خطای تنظیمات/عدم دسترسی به پل.

نمونه‌ی GitHub Actions در `.github/workflows/can-tests.yml` هست (روی runner ویندوزی
self-hosted که CANoe دارد).

---

## ۶) تولید مجدد داده‌ها

```
NBCM_Panel_Binding_Reference.xlsx
        │  python tools/build_data.py
        ▼
can_tester/assets/data.js          ← تستر مستقیم همین را می‌خواند (بدون build step)
can_tester/assets/signal_map.json  ← پل، رانر CI و ابزارها
        │  python tools/build_capl.py
        ▼
canoe/NBCM_Test.vsysvar
canoe/NBCM_TesterBridge.can
canoe/panel_binding_systemvars.csv
        │  python tools/build_xvp.py
        ▼
canoe/panels/*.xvp                 ← پنل‌های Panel Designer
```

اگر DBC عوض شد، فقط دو اسکریپت بالا را اجرا کنید؛ هیچ کد تستری دست‌کاری لازم نیست.

> نکته‌ی داده: در اکسل، برگه‌ی خلاصه برای ICN عدد **۹۱** سیگنال می‌گوید ولی برگه‌ی جزئیات
> **۱۰۶** ردیف دارد. تستر و گزارش‌ها از جزئیات استفاده می‌کنند و این ناسازگاری در خروجی
> `build_data.py` به‌صورت warning گزارش می‌شود.

---

## ۷) عیب‌یابی

| نشانه | علت | کار |
|---|---|---|
| نشانگر «Simulator» می‌ماند | پل بالا نیست | `python bridge/nbcm_bridge.py --canoe` |
| `pywin32 not installed` | نصب نشده | `pip install pywin32` |
| `system variables NOT available` | vsysvar اضافه نشده | `canoe/NBCM_Test.vsysvar` را import کنید |
| نوشتن روی باس اثر ندارد | `DRIVE_MODE=0` | کلیک روی «کنترل: CANoe» یا `--take-control` |
| Timeout همه‌ی پیام‌ها | نود restbus کامپایل نشده / Measurement متوقف | Trace و Write window را ببینید |
| مقدار نوشته‌شده clamp می‌شود | خارج از بازه‌ی فیزیکی سیگنال | برای تست خطا `raw: true` بفرستید |

---

## ۸) محدودیت‌های صادقانه

- پل روی **همان ویندوزی** اجرا می‌شود که CANoe نصب است؛ HTML می‌تواند از هر مرورگری باز شود
  ولی به پل روی همان ماشین وصل می‌شود (پیش‌فرض `127.0.0.1`).
- CANoe 12 خودش HTML را نمایش نمی‌دهد؛ «داخل CANoe» یعنی پنجره‌ی app-mode کنار آن
  (با always-on-top). برای نسخه‌های ۱۴+ که add-in دارند، می‌توان همین HTML را داخل پنجره‌ی
  dockable هاست کرد — لایه‌ی داده (پل) تغییری نمی‌کند.
- نرخ به‌روزرسانی زنده با `poll_hz` (پیش‌فرض ۴ Hz) کنترل می‌شود؛ COM برای مانیتورینگ
  چندهرتزی طراحی شده، نه برای نمونه‌برداری همگام دقیق.
- سیگنال‌هایی که در اکسل `Cycle = Event` دارند، برای پایش دوره‌ای ۱ ثانیه فرض شده‌اند؛
  اگر رفتار event-based واقعی لازم است، در restbus شرط ارسال را پیاده کنید.

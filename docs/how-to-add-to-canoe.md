# چطور داخل CANoe 12 اضافه/اجرا کنم؟

پاسخ کوتاه به عکس شما: آن دیالوگ (`.xvp; .ocx; .dll`) مال **پنل** است. پس باید یک فایل `.xvp`
داشته باشید — که حالا دارید. فایل HTML خودش را CANoe نمی‌تواند باز کند؛ HTML از بیرون
(مرورگر/پنجره‌ی کنار CANoe) اجرا می‌شود و داده را با System Variable به CANoe می‌دهد.

---

## آن دیالوگ چه چیزی قبول می‌کند؟

| گزینه | یعنی | برای شما |
|---|---|---|
| `*.xvp` — CANoe Panels | پنل Panel Designer (XML) | ✓ **این را انتخاب کنید**؛ ۱۵ فایل آماده است |
| `*.ocx / *.dll` — ActiveX Libraries | کنترل ActiveX سفارشی | ✗ لازم نیست؛ کنترل مرورگر قابل‌اتکا نیست |
| `*.cnp` — Panel Editor | فرمت قدیمی پنل (متنی، `VPanel`) | ⚠ کار می‌کند ولی **میراثی** است — توضیح پایین |

### دربارهٔ `.cnp` (چون پرسیدید)

`.cnp` هم متنی است و CANoe 12 آن را می‌خواند و به `.xvp` تبدیل می‌کند، اما ریسک‌هایی دارد:

- از CANoe **۱۹** به بعد تبدیل خودکار انجام نمی‌شود (باید در Panel Configuration فعالش کنید)
- Vector اعلام کرده پشتیبانی از تبدیل **در نسخه بعدی حذف می‌شود**
- برخی کنترل‌های جدید Panel Designer در `.cnp` وجود ندارند

من یک نمونهٔ `canoe/panels/NBCM_Smoke.cnp` هم تولید کرده‌ام؛ اگر باز شد، خیالتان راحت و
نسخهٔ `.xvp` معادلش هم همان کار را می‌کند. **توصیه: `.xvp`**.

---

## گام ۰ — سه فایل تولیدشده را بشناسید

```
canoe/NBCM_Test.vsysvar        ← تعریف ۴۷۸ متغیر (سیگنال‌ها + OFFLINE_* + کنترل‌ها)
canoe/NBCM_TesterBridge.can    ← نود CAPL: متغیرها را به restbus وصل می‌کند
canoe/panels/*.xvp             ← ۱۵ پنل آماده (Overview، Smoke، و یک پنل برای هر گره)
```

اگر از قبل نساخته‌اید:

```bash
python tools/build_data.py
python tools/build_capl.py     # vsysvar + CAPL
python tools/build_xvp.py      # پنل‌ها
```

---

## گام ۱ — System Variableها را اضافه کنید (بدون این، پنل‌ها خالی می‌مانند)

**راه اصلی (توصیه‌شده):**

1. CANoe → تب **Environment** → **System Variables**
2. دکمه/منوی **Import** → فایل `canoe/NBCM_Test.vsysvar` را انتخاب کنید
3. در پنجره‌ی متغیرها باید پوشه‌ی `NBCM_Test` با ۴۷۸ متغیر دیده شود
4. `Ctrl+S` (ذخیره‌ی کانفیگ)

**راه جایگزین اگر Import مشکل داشت** (CANoe باید باز و کانفیگ باز باشد):

```bash
python tools/install_sysvars.py --dry-run   # فقط نمایش
python tools/install_sysvars.py --save      # ساخت واقعی + ذخیره
```

> متغیرهای تکراری رد می‌شوند، پس اجرای دوباره بی‌خطر است.

---

## گام ۲ — پنل کلی را اضافه کنید (همان دیالوگ عکس شما)

فقط یک فایل لازم است: **`canoe/panels/NBCM_Main.xvp`**

| تب | چه دارد |
|---|---|
| **Dashboard** | دو گِیج (سرعت/RPM)، LCD، سناریوی رانندگی، کنترل منبع (DRIVE_MODE)، سلامت شبکه‌ی ۱۳ گره |
| **Nodes** | ۱۳ کلید قطع گره + LED سبز/قرمز برای هر کدام |
| **Monitor** | جدول Timeout: LED حامل + سن آخرین پیام (ms) برای هر گره |
| **Tests** | شمارش PASS/FAIL + LED نتیجه‌ی آخرین تست |
| **۱۳ تب گره** | همه‌ی سیگنال‌های هر گره: مقدار + کلید/LED یا عدد |

### شبیه‌سازی پشت پنل

پنل فقط نمایش و کنترل است؛ منطق در `NBCM_TesterBridge.can` است:

- `SCENARIO_RUNNING=1` → CAPL یک چرخه‌ی رانندگی می‌سازد (توقف → ۶۰ → ۱۲۰ → صفر، هر ۲۰ ثانیه)
- `MANUAL_SPEED_MODE=1` → سرعت از `MANUAL_SPEED_KMH` خوانده می‌شود
- `OFFLINE_<NODE>=1` → پیام‌های آن گره قطع می‌شود، LED قرمز و سن پیام بالا می‌رود
- `HB_<NODE>` / `AGE_<NODE>` → از `on message *` پر می‌شوند، پس **Timeout واقعی** را نشان می‌دهند

## گام ۲ب — پنل‌های تک‌گره (اختیاری)

1. CANoe → تب **Home** → گروه **Panel** → **Add Panel…**
2. در دیالوگ، فیلتر را روی `CANoe Panels (*.xvp)` بگذارید
3. اول **`NBCM_Smoke.xvp`** را اضافه کنید (کوچک است، برای تست سیم‌کشی)
4. بعد `NBCM_Test_Overview.xvp` و در صورت نیاز پنل هر گره (`NBCM_ABS.xvp` و …)
5. پنل به‌صورت پنجره‌ی داخل CANoe باز می‌شود؛ اگر باز نشد:
   **Home → Panel → Panel Configuration** و همان فایل را از آنجا اضافه کنید
6. `Ctrl+S`

### پنل Smoke چه چیزی را ثابت می‌کند؟

سه کنترل دارد: `DRIVE_MODE`، `OFFLINE_ABS` و نمایش `Hs_Abs_VehicleSpeed`.
سوئیچ را بزنید؛ اگر مقدار LCD عوض شد، یعنی **پنل ↔ System Variable ↔ CAPL** درست وصل است.

---

## گام ۳ — نود CAPL را وصل کنید

`canoe/NBCM_TesterBridge.can` باید در **همان network node** فایل
`NBCM_Full_Restbus_Simulation.can` کامپایل شود (چون به متغیرهای CAPL آن دسترسی می‌خواهد).

ساده‌ترین راه: در انتهای `NBCM_Full_Restbus_Simulation.can` این خط را اضافه کنید:

```c
#include "NBCM_TesterBridge.can"
```

سپس Measurement را Start کنید. در **Write** window باید ببینید:

```
[TesterBridge] active, namespace NBCM_Test
```

---

## گام ۴ — تستر HTML را کنار CANoe باز کنید

```bash
python bridge/nbcm_bridge.py --canoe --canoe-config "C:\CANoe\NBCM\NBCM.cfg"
python bridge/nbcm_window.py --always-on-top
```

یا فقط `bridge\run_windows.bat` را دوبار کلیک کنید.
در تستر، نشانگر **«کنترل: CANoe»** را بزنید تا `DRIVE_MODE=1` شود و تستر بتواند روی باس بنویسد.

---

## چرا پنل `.xvp` و HTML دو چیز جدا هستند؟

| | پنل `.xvp` (داخل CANoe) | تستر HTML (کنار CANoe) |
|---|---|---|
| محل اجرا | داخل خود CANoe | پنجره‌ی مرورگر |
| ورودی | همان دیالوگ `Add Panel` | آدرس `http://127.0.0.1:8771` |
| قابلیت | کنترل/نمایش سیگنال، آفلاین کردن گره | سناریو، رانر تست، ورдикт، گزارش JSON/JUnit |
| مناسب برای | کار روزمره و تحریک سریع | تست خودکار و مستندسازی |

هر دو از **یک قرارداد** استفاده می‌کنند: `NBCM_Test::<SignalName>` و `NBCM_Test::OFFLINE_<NODE>`.
پس هر کدام را جدا یا هم‌زمان می‌توانید استفاده کنید.

---

## اگر می‌خواهید پنل را خودتان بسازید (مطمئن‌ترین راه)

اگر از فایل‌های تولیدشده چیزی باز نشد، در ۲ دقیقه پنل خودتان را بسازید — بقیهٔ سیستم همان می‌ماند:

1. تب **Home** → **Panel** → **New Panel**
2. **File → Save** → نام `NBCM_Test.xvp` در پوشهٔ `Panels`
3. از **Tool Box** یک **Switch/Indicator** روی پنل بکشید
4. در **Properties** → `Symbol Filter` = **System Variable** → `Symbol` = `NBCM_Test` → `DRIVE_MODE`
5. یک **Numeric Up/Down** بگذارید و به `NBCM_Test::MANUAL_SPEED_KMH` ببندید
6. برای هر گره یک Switch بگذارید و به `NBCM_Test::OFFLINE_<NODE>` ببندید
7. **Save** — پنل خودش به کانفیگ اضافه می‌شود

نکتهٔ مهم: در Panel Designer هم `Symbol Filter` را روی **System Variable** بگذارید، نه Signal.
چون CAPL فقط متغیرهای خودش را می‌بیند و پل ما از طریق System Variable کار می‌کند.

## اگر CANoe دربارهٔ System Variable خطا داد

سه پیام مختلف وجود دارد و هر کدام علت جداگانه‌ای دارد:

| پیام CANoe | علت | وضعیت |
|---|---|---|
| `Duplicate System Variable /NBCM_Test/... Line N` | یک نام دو بار تعریف شده | **رفع شد** — اکسل ۲۱ نام را در دو پیام تکرار می‌کند؛ حالا یک متغیر با توضیح «also in: ...» |
| `The data model contains at least one error` | مدل داده ایراد دارد (نه تکراری) | **رفع شد** — دو قاعدهٔ CANoe رعایت نشده بود |
| `Error loading file ...` | فایل خوانده نشد | مسیر/دسترسی فایل |

### آن «at least one error» دقیقاً چه بود؟

CANoe این پیام را کلی می‌دهد و شمارهٔ خط نمی‌دهد. با مقایسهٔ فایل خودمان با فایل‌هایی
که خودِ CANoe نوشته بود، دو تخلف پیدا شد:

1. **`bitcount` برای `float` اجباری است و باید ۶۴ باشد.** من ۱۷۴ متغیر `float` را
   بدون `bitcount` می‌ساختم.
2. **`startValue` باید داخل `minValue..maxValue` باشد.** مثلاً `LS_ICN_ODO` مقدار
   شروع ۱۲٬۳۴۵٬۰۰۰ داشت ولی محدوده‌اش ۰..۱ بود.

شکل درست (از فایل واقعی CANoe):

```xml
<variable ... bitcount="64" isSigned="true" encoding="65001" type="float"
          startValue="0" minValue="0" maxValue="300" />
<variable ... bitcount="32" isSigned="true" encoding="65001" type="int"
          minValue="0" minValuePhys="0" maxValue="1" maxValuePhys="1"
          startValue="0" />
```

### چطور خودتان چک کنید

```bash
python tools/check_vsysvar.py        # همهٔ قواعدی که CANoe بررسی می‌کند
python tools/doctor.py               # بررسی کل پروژه
```

`check_vsysvar.py` اگر فایل ایراد داشته باشد با کد خطا خارج می‌شود و دقیقاً می‌گوید
کدام متغیر و کدام قاعده. برای دیدن تفاوت با فایل واقعی:

```bash
python tools/check_vsysvar.py --canonical   # ترتیب attributeها مثل CANoe
```

## اگر پنل باز نشد

| نشانه | علت | کار |
|---|---|---|
| پنل اضافه می‌شود ولی کنترل‌ها خالی‌اند | System Variableها import نشده‌اند | گام ۱ را انجام دهید |
| خطای نسخه/فرمت هنگام باز کردن | CANoe نسخه‌ی قدیمی‌تر از فایل | فایل‌ها با استمپ `8.5.80.0` ساخته شده‌اند؛ CANoe هنگام باز کردن upgrade می‌کند. اگر باز هم ایراد داد، `python tools/build_xvp.py --version 10.0.96.0` را امتحان کنید |
| تغییر سوئیچ روی باس اثر ندارد | `DRIVE_MODE=0` است | سوئیچ `DRIVE_MODE` در پنل Overview را روشن کنید |
| پنل کج/بزرگ‌تر از صفحه است | اندازه‌ی پنل بزرگ است | پنل‌های تک‌گره بلند هستند؛ در CANoe اندازه‌ی پنجره را بزرگ کنید یا از Overview استفاده کنید |

> صادقانه: قالب `.xvp` متن‌باز و مستند رسمی نیست. ساختار از روی پنل‌های واقعیِ نمونه‌های
> Vector بازسازی شده و XML آن معتبر است، اما اولین بار باید در CANoe خودتان باز و تأیید شود.
> اگر جایی ایراد گرفت، فایل را با Panel Designer باز و ذخیره کنید؛ از آن به بعد نسخه‌ی
> خودِ CANoe شما معتبر است.

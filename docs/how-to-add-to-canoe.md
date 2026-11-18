# چطور داخل CANoe 12 اضافه/اجرا کنم؟

پاسخ کوتاه به عکس شما: آن دیالوگ (`.xvp; .ocx; .dll`) مال **پنل** است. پس باید یک فایل `.xvp`
داشته باشید — که حالا دارید. فایل HTML خودش را CANoe نمی‌تواند باز کند؛ HTML از بیرون
(مرورگر/پنجره‌ی کنار CANoe) اجرا می‌شود و داده را با System Variable به CANoe می‌دهد.

---

## آن دیالوگ چه چیزی قبول می‌کند؟

| گزینه | یعنی | برای شما |
|---|---|---|
| `*.xvp` — CANoe Panels | پنل Panel Designer (XML) | ✅ همین را می‌خواهیم؛ ۱۵ فایل آماده است |
| `*.ocx / *.dll` — ActiveX Libraries | کنترل ActiveX سفارشی | ❌ لازم نیست؛ کنترل مرورگر قابل‌اتکا نیست |
| `*.cnp` — Panel Editor | فرمت قدیمی پنل | ❌ منسوخ؛ Panel Designer بهتر است |

---

## گام ۰ — سه فایل تولیدشده را بشناسید

```
canoe/NBCM_Test.vsysvar        ← تعریف ۴۹۹ متغیر (سیگنال‌ها + OFFLINE_* + کنترل‌ها)
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
3. در پنجره‌ی متغیرها باید پوشه‌ی `NBCM_Test` با ۴۹۹ متغیر دیده شود
4. `Ctrl+S` (ذخیره‌ی کانفیگ)

**راه جایگزین اگر Import مشکل داشت** (CANoe باید باز و کانفیگ باز باشد):

```bash
python tools/install_sysvars.py --dry-run   # فقط نمایش
python tools/install_sysvars.py --save      # ساخت واقعی + ذخیره
```

> متغیرهای تکراری رد می‌شوند، پس اجرای دوباره بی‌خطر است.

---

## گام ۲ — پنل را اضافه کنید (همان دیالوگ عکس شما)

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

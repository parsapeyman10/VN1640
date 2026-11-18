# فایل‌های سمت CANoe (تولیدشده)

این پوشه را دستی ویرایش نکنید؛ با `python tools/build_capl.py` از اکسل بازتولید می‌شود.

| فایل | کاربرد |
|---|---|
| `NBCM_Test.vsysvar` | تعریف ۴۹۹ System Variable: ۴۸۱ سیگنال + ۱۳ کلید `OFFLINE_<NODE>` + ۵ متغیر کنترل |
| `NBCM_TesterBridge.can` | نود CAPL که هر ۱۰۰ms مقادیر را بین restbus و System Variables جابه‌جا می‌کند |
| `panel_binding_systemvars.csv` | لیست آماده‌ی بایندینگ برای Panel Designer (نوع System Variable) |

## نصب در CANoe 12

1. `NBCM_Test.vsysvar` → منوی `Environment` / پنجره‌ی System Variables → **Import** (یا
   در کانفیگ به‌عنوان فایل اضافه شود). بعد از import، نشانی متغیرها
   `NBCM_Test::<SignalName>` است.
2. `NBCM_TesterBridge.can` باید در همان **network node** فایل
   `NBCM_Full_Restbus_Simulation.can` باشد (چون به متغیرهای CAPL آن دسترسی می‌خواهد).
   ساده‌ترین راه: در انتهای فایل restbus این خط را اضافه کنید:

   ```
   #include "NBCM_TesterBridge.can"
   ```

   یا در Simulation Setup یک نود جدا بسازید و هر دو فایل را به آن بدهید.
3. Measurment را Start کنید. در Write window باید ببینید:

   ```
   [TesterBridge] active, namespace NBCM_Test
   ```

## جهت جریان داده

```
DRIVE_MODE = 0   restbus → System Variables     (تستر فقط تماشا می‌کند)
DRIVE_MODE = 1   System Variables → restbus     (تستر مالک سیگنال‌ها است)
OFFLINE_<NODE>   همیشه از تستر خوانده می‌شود
```

`DRIVE_MODE` را از خود تستر (دکمه‌ی «کنترل: CANoe») یا با کلید `t` در CANoe عوض کنید.

## چرا System Variable و نه COM مستقیم؟

COM روی CANoe، سیگنال باس را می‌خواند/می‌نویسد اما متغیرهای CAPL
(مثل `long OFFLINE_ABS` یا `double Hs_Abs_VehicleSpeed`) از بیرون قابل نوشتن نیستند.
System Variable تنها رسانه‌ی مستند برای تبادل با برنامه‌های بیرونی است و هم COM، هم CAPL
(`@sysvar::...`)، هم Panel Designer آن را می‌فهمند.

# اجرا کردن تستر (launcher)

## سه راه، از ساده به دقیق

| راه | دستور | چه می‌کند |
|---|---|---|
| دوبار کلیک | `bridge\run_sim.bat` | تستر بدون CANoe |
| دوبار کلیک | `bridge\run_windows.bat` | تستر + CANoe 12 |
| خط فرمان | `python bridge/launcher.py sim` | همان، با پیام‌های کامل |

هر سه یک کار می‌کنند؛ `.bat`ها فقط Python را پیدا می‌کنند و `launcher.py` را صدا می‌زنند.

---

## چه اتفاقی می‌افتد

```
[1/3] starting the bridge: bridge/nbcm_bridge.py --sim --port 8770
      [10:44:01] websocket listening on ws://0.0.0.0:8770/
      [10:44:01] tester UI  : http://0.0.0.0:8771/
[ok] bridge at http://127.0.0.1:8771/
      mode=sim canoe=False sysvars=False driveMode=0
[3/3] opening the tester ...
```

`launcher.py` این کارها را می‌کند:

1. **بررسی فایل‌ها** — اگر `nbcm_bridge.py` نبود، دقیقاً می‌گوید کدام فایل گم است و کجا باید باشد
2. **اجرای پل** به‌صورت فرزند خودش (نه `start` جدا) تا بتواند منتظرش بماند و با Ctrl+C ببنددش
3. **انتظار واقعی** — هر ۰٫۴ ثانیه `/api/health` را می‌پرسد تا پل جواب بدهد (نه `timeout /t 3`)
4. **خواندن پورت واقعی** — پل اگر پورت مشغول باشد به پورت بعدی می‌رود؛ آدرس از خود پل پرسیده می‌شود
5. **باز کردن تستر** در پنجره‌ی app-mode؛ اگر نشد، مرورگر پیش‌فرض
6. **بستن پل** وقتی پنجره تستر بسته شد

---

## گزینه‌ها

```bash
python bridge/launcher.py sim              # بدون CANoe
python bridge/launcher.py canoe            # با CANoe
python bridge/launcher.py sim --dry-run    # فقط نشان بده چه می‌خواهد بکند
python bridge/launcher.py sim --no-window  # پنجره باز نکن، فقط URL را بده
python bridge/launcher.py sim --keep       # پل را بعد از بستن پنجره زنده نگه دار
python bridge/launcher.py canoe --canoe-config "C:\CANoe\NBCM\NBCM.cfg"
```

---

## پورت را عوض کردن

اگر ۸۷۷۰ مشغول است، فایل `bridge/config.local.json` را بسازید (در گیت نیست):

```json
{
  "port": 8780,
  "canoe": { "config_path": "C:\\CANoe\\NBCM\\NBCM.cfg" }
}
```

یا موقت:

```bat
set NBCM_PORT=8780
bridge\run_sim.bat
```

> آدرس تستر همیشه `port + 1` است. هیچ‌جا هاردکد نشده — `.bat` قبلی `127.0.0.1:8771`
> را ثابت داشت و اگر پورت عوض می‌شد مرورگر صفحه‌ی خالی می‌گرفت.

---

## خطاهای رایج و پیام واقعی‌شان

| پیام | معنی | کار |
|---|---|---|
| `[ERROR] missing next to this script: nbcm_bridge.py` | `.bat` را از پوشه‌ی دیگری اجرا کرده‌اید | فایل‌ها باید کنار هم در `bridge\` بمانند |
| `[ERROR] Python 3.8+ not found` | پایتون در PATH نیست | از python.org نصب و «Add python.exe to PATH» را تیک بزنید |
| `[ERROR] the bridge exited immediately (code 1)` | پل بالا نیامد؛ خروجی خودش بالاتر است | پورت مشغول است یا CANoe باز نیست |
| `[warn] port 8770 is already in use` | یک پل دیگر در حال اجراست | همان استفاده می‌شود، یا پورت را عوض کنید |
| `[warn] bridge reports: ...` | پل هست ولی CANoe را نمی‌بیند | `pip install pywin32` و باز بودن CANoe |
| `[warn] app window failed` | Edge/Chrome پیدا نشد | مرورگر پیش‌فرض باز می‌شود |

---

## چرا `.bat` قبلی کار نمی‌کرد

سه باگ واقعی، که هر سه با تست گرفته شدند:

1. **نام فایل غلط** — هر دو `.bat` می‌گفتند `bcm_bridge.py`، در حالی که فایل `nbcm_bridge.py`
   است. یعنی **هیچ‌کدام هرگز اجرا نشده بودند**.
2. **پورت و آدرس هاردکد** — `start "" "http://127.0.0.1:8771/"` بعد از `timeout /t 3`.
   اگر پورت عوض می‌شد یا پل دیر بالا می‌آمد، صفحه‌ی خالی.
3. **`endlocal` بدون `setlocal`** و **پایان خط LF** به‌جای CRLF.

علت ریشه‌ای: منطقِ غیرقابل‌تست داخل `.bat` بود. حالا `.bat` فقط ۱۵ خط است و همه‌ی
منطق در `bridge/launcher.py` است — که با `python tests/test_launchers.py` تست می‌شود
(۲۰ بررسی، شامل اجرای واقعی پل و پیدا کردن پورتش).

---

## عیب‌یابی سریع

```bash
python tools/check_bat.py            # ساختار فایل‌های .bat
python tools/find_bridge.py          # آدرس پل در حال اجرا
python tools/find_bridge.py --json   # وضعیت کامل
python bridge/nbcm_bridge.py --sim   # اجرای مستقیم پل، بدون launcher
```

/* ==========================================================================
   boot.js — start the tester
   ========================================================================== */
(function (global) {
  'use strict';
  const C = global.Core;

  document.addEventListener('DOMContentLoaded', async () => {
    try {
      global.Info.init();
      global.UI.init();
      global.Tests.init();
      const mode = C.settings.mode || 'sim';
      await C.connect(mode).catch(async (e) => {
        console.warn('connect failed, falling back to simulator', e);
        await C.connect('sim');
      });
      global.UI.renderConn();
      global.UI.toast('آماده — منبع داده: ' + C.stats.source);
    } catch (e) {
      console.error(e);
      const box = document.createElement('pre');
      box.style.cssText = 'color:#ff5f6d;padding:20px;font-size:12px;white-space:pre-wrap';
      box.textContent = 'خطا در راه‌اندازی تستر:\n' + (e && e.stack ? e.stack : e);
      document.body.appendChild(box);
    }
  });
})(window);

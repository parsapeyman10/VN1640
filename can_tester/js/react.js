/* ==========================================================================
   react.js -- the reaction rules, in the browser
   --------------------------------------------------------------------------
   tools/behaviour.py is the reference implementation (it is what the CAPL is
   generated from and what the tests exercise).  This file is its browser twin,
   so the standalone tester and the bridge produce the same consequences when a
   node is cut.  Without it the offline switch in the browser only stops values
   from changing while every fault flag stays 0 -- the exact "bag of numbers"
   the behaviour model exists to replace.

   Loaded after data.js, before core.js.  No DOM access, no timers: a pure
   function of (state, now), same contract as the Python side.
   ========================================================================== */
(function (global) {
  'use strict';

  const ABSENT_AFTER_MS = 500;      // must match tools/behaviour.py
  const LIVE_CYCLE_MAX_MS = 1000;   // a 5 s ambient frame is not a liveness source

  const canon = (s) => String(s).toLowerCase().replace(/[^a-z0-9]/g, '');
  const isSup = (msg) => /_SUP$/i.test(msg) || /_SUPERVISION_/i.test(msg);

  // who needs whose data; the reason is shown to the user
  const DEPENDENCIES = [
    ['ABS', 'ABS', 'Hs_Abs_VehicleSpeed_Invalid',
      'سرعت خودرو از سنسورهای چرخ می‌آید؛ با رفتن ABS این مقدار معتبر نیست'],
    ['ICU', 'ABS', 'Hs_Icu_Ems_Status', 'کیلومترشمار و مصرف روی سرعت خودرو حساب می‌شوند'],
    ['TCU', 'EMS', 'Hs_Tcu_Current_Gear', 'گیربکس به دور و گشتاور موتور نیاز دارد'],
    ['ICU', 'EMS', 'Hs_Icu_Ems_Status', 'آمپر دور و وضعیت موتور را از EMS می‌گیرد'],
    ['ICN', 'EMS', 'Ls_Icn_Speed_Display', 'نمایشگر سرعت و دور را از فریم‌های موتور می‌گیرد'],
    ['ICN', 'ABS', 'Ls_Icn_Speed_Display', 'نمایشگر سرعت را از ABS می‌گیرد'],
  ];

  function build(data) {
    const signals = data.signals || [];
    const nodes = data.nodes || [];
    const byName = new Map();
    signals.forEach((s) => { if (!byName.has(s.sig)) byName.set(s.sig, s); });

    const live = new Map();       // node -> [{net,msg}]
    const sup = new Map();        // node -> {comloss, counter, dynamic, ...}
    const substitutes = new Map(); // signal -> {mode, value, why}

    signals.forEach((s) => {
      if (isSup(s.msg)) {
        const c = canon(s.sig);
        const slot = sup.get(s.node) || {};
        if (/comlosscounter$/.test(c)) slot.counter = s.sig;
        else if (/comloss$/.test(c)) slot.comloss = s.sig;
        else if (/txtimeoutcounter$/.test(c)) slot.timeout = s.sig;
        else if (/ecudynamicstates$/.test(c)) slot.dynamic = s.sig;
        else if (/ecustaticstates$/.test(c)) slot.static = s.sig;
        sup.set(s.node, slot);
        return;
      }
      const cyc = Number(s.cycle) || 0;
      if (cyc && cyc <= LIVE_CYCLE_MAX_MS) {
        const list = live.get(s.node) || [];
        if (!list.some((f) => f.msg === s.msg)) list.push({ net: s.net, msg: s.msg });
        live.set(s.node, list);
      }

      const n = s.sig.toLowerCase();
      const faultish = /(comloss|absent|nerr|error|fault|warn|lamp)/.test(n.replace(/_/g, ''));
      if (s.kind === 'num' && !faultish) {
        if (/(speed|spd)/.test(n)) substitutes.set(s.sig, { mode: 'zero', value: 0,
          why: 'سرعت با نبودِ فرستنده صفر می‌شود (مقدار یخ‌زده خطرناک است)' });
        else if (/(torque|torq)/.test(n)) substitutes.set(s.sig, { mode: 'zero', value: 0,
          why: 'گشتاور صفر اعلام می‌شود؛ گاز داده نشده' });
        else if (/rpm/.test(n)) substitutes.set(s.sig, { mode: 'zero', value: 0,
          why: 'دور موتور صفر؛ موتور خاموش دیده می‌شود' });
      }
    });

    const nodeOf = new Map();
    signals.forEach((s) => { if (!nodeOf.has(s.sig)) nodeOf.set(s.sig, s.node); });
    const indexOf = new Map(nodes.map((n, i) => [n.node, i]));

    /* one tick; same shape as behaviour.Model.compute */
    function compute(state) {
      const values = state.values || {};
      const offline = state.offline || {};
      const lastSeen = state.lastSeen || {};
      const now = state.now || 0;
      const out = {};
      const reasons = [];
      const note = (rule, node, signal, text) => reasons.push({ rule, node, signal, text });

      const absent = {};
      nodes.forEach((n) => {
        if (offline[n.node]) { absent[n.node] = true; return; }
        const frames = live.get(n.node) || [];
        if (!frames.length) { absent[n.node] = false; return; }
        let gone = 0;
        frames.forEach((f) => {
          const t = lastSeen[f.net + ':' + f.msg];
          if (t && (now - t) > ABSENT_AFTER_MS) gone += 1;
        });
        absent[n.node] = frames.length > 0 && gone === frames.length;
      });

      /* report */
      nodes.forEach((n) => {
        const s = sup.get(n.node);
        if (!s) return;
        if (s.comloss) out[s.comloss] = absent[n.node] ? 1 : 0;
        if (s.counter) {
          const rec = byName.get(s.counter);
          const top = (rec && rec.max) || 255;
          if (absent[n.node]) out[s.counter] = Math.min(top, (values[s.counter] || 0) + 1);
          else out[s.counter] = 0;
        }
      });

      /* substitute */
      substitutes.forEach((sub, name) => {
        const node = nodeOf.get(name);
        if (!node || !absent[node] || sub.mode !== 'zero') return;
        out[name] = sub.value;
        note('substitute', node, name, sub.why);
      });

      /* cascade + recovery */
      DEPENDENCIES.forEach(([dep, needs, carrier, why]) => {
        if (absent[needs]) {
          const s = sup.get(dep);
          if (s && s.comloss) { out[s.comloss] = 1; note('cascade', dep, s.comloss, why); }
          const rec = byName.get(carrier);
          if (rec) {
            out[carrier] = rec.kind === 'bool' ? 1 : (rec.max || 1);
            note('cascade', dep, carrier,
              dep + ' داده‌ی ' + needs + ' را ندارد، پس این مقدار را نامعتبر اعلام می‌کند');
          }
        } else if (values[carrier]) {
          out[carrier] = 0;
          note('recover', dep, carrier, needs + ' برگشته، پس این مقدار دوباره معتبر می‌شود');
        }
      });

      /* inhibit */
      DEPENDENCIES.forEach(([dep, needs]) => {
        if (!absent[needs]) return;
        const s = sup.get(dep);
        if (s && s.dynamic) {
          out[s.dynamic] = 1;
          note('inhibit', dep, s.dynamic,
            dep + ' به ' + needs + ' نیاز دارد و آن غایب است؛ عملکرد وابسته غیرفعال می‌شود');
        }
      });

      return { values: out, absent, reasons };
    }

    return {
      compute, sup, live, substitutes, indexOf,
      stats: { nodes: nodes.length, sup: sup.size, substitutes: substitutes.size,
               dependencies: DEPENDENCIES.length },
    };
  }

  let BEHAVIOUR = null;
  global.React = {
    build,
    get model() { return BEHAVIOUR; },
    init(data) { BEHAVIOUR = build(data || global.NBCM_DATA); return BEHAVIOUR; },
    ABSENT_AFTER_MS,
  };
}(window));

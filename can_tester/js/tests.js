/* ==========================================================================
   tests.js — test-case engine (declarative JSON), runner, verdicts, reports

   Supported step types
   --------------------
     { "wait": 500 }                                     milliseconds
     { "set":  { "Hs_Abs_VehicleSpeed": 60 } }           write signal(s)
     { "set":  { "$offline": ["ABS"] } }                 node offline on/off (true/false)
     { "expect": { "signal": "Hs_Abs_VehicleSpeed", "op": ">=", "value": 0 } }
     { "expect": { "offline": "ABS" } }                  node is offline
     { "expect": { "online": "ABS" } }                   node is online
     { "expect": { "fresh": "HS_ID_ABS", "within": 200 } } message seen recently
     { "expect": { "absent": "HS_ID_ABS" } }             message not seen recently
     { "require": { "signal": "Hs_Abs_Active", "op": "==", "value": 1 } }
                                                          wait for condition (with timeout)
   Keys accepted as aliases: value/expected, op/operator.
   ========================================================================== */
(function (global) {
  'use strict';
  const C = global.Core;
  const $ = (id) => document.getElementById(id);
  const LSKEY = 'nbcm.suite.v1';
  // localStorage raises in some contexts (file:// in Chromium, private mode).
  // Saving is a convenience, never a requirement -- the editor must keep working.
  const store = {
    ok: true,
    get(k) { try { return localStorage.getItem(k); } catch (e) { store.ok = false; return null; } },
    set(k, v) { try { localStorage.setItem(k, v); return true; } catch (e) { store.ok = false; return false; } },
  };

  /* ------------------------------------------------------- default suite */
  // Built from the generated data model so it never drifts from the workbook.
  function firstMsgOf(nodeName) {
    const n = C.DATA.nodes.find((x) => x.node === nodeName);
    return n && n.msgs.length ? n.msgs[0] : null;
  }
  function firstBoolOf(nodeName) {
    const list = C.byNode.get(nodeName) || [];
    return (list.find((s) => s.kind === 'bool') || list[0] || null);
  }

  function makeDefaultSuite() {
    const absMsg = firstMsgOf('ABS');
    const emsMsg = firstMsgOf('EMS');
    const icnMsg = firstMsgOf('ICN');
    const absBool = firstBoolOf('ABS');
    const speedSig = C.ALIAS.speed ? C.ALIAS.speed.sig : (absMsg ? absMsg.sigs[0] : null);
    const tests = [];

    if (speedSig && absMsg) {
      tests.push({
        id: 'TC-001', title: 'سرعت خودرو روی باس منتشر می‌شود', suite: 'Signal',
        steps: [
          { set: { $offline: { ABS: false } } },
          { set: { [speedSig]: 60 } },
          { settle: 400 },
          { expect: { signal: speedSig, op: '>=', value: 1 } },
        ],
      });
      tests.push({
        id: 'TC-002', title: 'محدوده فیزیکی سیگنال سرعت رعایت می‌شود', suite: 'Signal',
        steps: [
          { set: { [speedSig]: 99999 } },
          { settle: 300 },
          { expect: { signal: speedSig, op: '<=', value: 8189 } },
        ],
      });
    }

    if (absMsg) {
      tests.push({
        id: 'TC-010', title: 'قطع ABS باعث Timeout پیام ' + absMsg.msg + ' می‌شود', suite: 'Timeout',
        steps: [
          { set: { $offline: { ABS: false } } },
          { settle: 1400 },
          { expect: { fresh: absMsg.msg, within: 2500 } },
          { set: { $offline: { ABS: true } } },
          { settle: 3000 },
          { expect: { absent: absMsg.msg } },
        ],
      });
      tests.push({
        id: 'TC-011', title: 'بازگشت ABS پیام را دوباره زنده می‌کند', suite: 'Timeout',
        steps: [
          { set: { $offline: { ABS: true } } },
          { settle: 2600 },
          { expect: { absent: absMsg.msg } },
          { set: { $offline: { ABS: false } } },
          { set: { [speedSig || absMsg.sigs[0]]: 45 } },
          { require: { signal: speedSig || absMsg.sigs[0], op: 'exists', timeout: 4000 } },
          { settle: 1200 },
          { expect: { fresh: absMsg.msg, within: 3000 } },
        ],
      });
    }

    const smoke = [];
    if (absMsg) smoke.push({ expect: { fresh: absMsg.msg, within: 3000 } });
    if (emsMsg) smoke.push({ expect: { fresh: emsMsg.msg, within: 3000 } });
    if (icnMsg) smoke.push({ expect: { fresh: icnMsg.msg, within: 3000 } });
    if (smoke.length) {
      tests.push({
        id: 'TC-020', title: 'خروجی گره‌های کلیدی HS و LS سالم است', suite: 'Smoke',
        steps: [{ set: { $offline: { ABS: false, EMS: false, ICN: false } } }, { settle: 1500 }].concat(smoke),
      });
    }

    if (absBool) {
      tests.push({
        id: 'TC-030', title: 'نوشتن و بازخوانی سیگنال بولی ' + absBool.sig, suite: 'Signal',
        steps: [
          { set: { $offline: { ABS: false } } },
          { set: { [absBool.sig]: 1 } },
          { settle: 250 },
          { expect: { signal: absBool.sig, op: '==', value: 1 } },
          { set: { [absBool.sig]: 0 } },
          { settle: 250 },
          { expect: { signal: absBool.sig, op: '==', value: 0 } },
        ],
      });
    }

    tests.push({
      id: 'TC-040', title: 'گره آنلاین/آفلاین درست علامت‌گذاری می‌شود', suite: 'Smoke',
      steps: [
        { set: { $offline: { MMS: false } } },
        { expect: { online: 'MMS' } },
        { set: { $offline: { MMS: true } } },
        { expect: { offline: 'MMS' } },
        { set: { $offline: { MMS: false } } },
      ],
    });

    return {
      version: 1,
      name: 'NBCM Restbus / CANoe 12',
      defaults: { settle: 350, poll: 100, timeout: 4000 },
      tests,
    };
  }

  const OPS = {
    '==': (a, b) => a === b,
    '!=': (a, b) => a !== b,
    '>': (a, b) => a > b,
    '>=': (a, b) => a >= b,
    '<': (a, b) => a < b,
    '<=': (a, b) => a <= b,
    '~=': (a, b) => Math.abs(a - b) <= Math.abs(b) * 0.02 + 1e-9,
    'exists': (a) => a !== undefined && a !== null,
    'notexists': (a) => a === undefined || a === null,
  };

  /* ------------------------------------------------------------ suite IO */
  function getSuite() { return suite; }
  function setSuite(obj) { suite = obj; validateAndStore(obj); }

  let suite = normalize(loadSuite());

  /* The generated suite is the fallback when nothing is stored yet. */
  function defaultSuite() { return makeDefaultSuite(); }

  function loadSuite() {
    try {
      const raw = store.get(LSKEY);
      if (raw) return JSON.parse(raw);
    } catch (e) { /* corrupt entry -> fall back to the generated suite */ }
    return makeDefaultSuite();
  }

  function normalize(s) {
    const d = Object.assign({ settle: 350, poll: 100, timeout: 4000 }, (s && s.defaults) || {});
    return Object.assign({ version: 1, name: (s && s.name) || 'Suite', defaults: d }, s || {}, { defaults: d });
  }

  function validate(s) {
    const errs = [];
    if (!s || typeof s !== 'object') errs.push('ریشه باید یک آبجکت JSON باشد');
    if (!Array.isArray(s.tests) || !s.tests.length) errs.push('tests باید آرایه‌ای غیرخالی باشد');
    (s.tests || []).forEach((t, i) => {
      const tag = '#' + (i + 1) + (t.id ? ' (' + t.id + ')' : '');
      if (!t.id) errs.push(tag + ': شناسه (id) لازم است');
      if (!Array.isArray(t.steps) || !t.steps.length) errs.push(tag + ': steps لازم است');
      (t.steps || []).forEach((st, j) => {
        const keys = Object.keys(st);
        const known = keys.filter((k) => ['wait', 'settle', 'set', 'expect', 'require', 'log'].includes(k));
        if (!known.length) errs.push(tag + ' step ' + (j + 1) + ': کلید ناشناخته ' + keys.join(','));
        if (st.expect && st.expect.signal && !C.byName.has(st.expect.signal)) {
          errs.push(tag + ' step ' + (j + 1) + ': سیگنال ناشناخته "' + st.expect.signal + '"');
        }
        if (st.require && st.require.signal && !C.byName.has(st.require.signal)) {
          errs.push(tag + ' step ' + (j + 1) + ': سیگنال ناشناخته "' + st.require.signal + '"');
        }
      });
    });
    return errs;
  }

  function validateAndStore(obj) {
    const errs = validate(obj);
    if (!errs.length) store.set(LSKEY, JSON.stringify(obj));
    return errs;
  }

  /* ------------------------------------------------------------- runner */
  const results = new Map();       // id -> result
  const selection = new Set();
  let running = false, abort = false;

  function log(lvl, text) {
    const box = $('console');
    const line = document.createElement('div');
    const t = new Date().toLocaleTimeString('fa-IR', { hour12: false });
    line.innerHTML = '<span class="t">' + t + '</span> ';
    const b = document.createElement('b'); b.className = lvl; b.textContent = lvl;
    line.appendChild(b);
    line.appendChild(document.createTextNode(' ' + text));
    box.appendChild(line);
    box.scrollTop = box.scrollHeight;
    if (box.childElementCount > 500) box.removeChild(box.firstChild);
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  function elapsedMsg(msgName) {
    if (global.UI && global.UI.echoAge) return global.UI.echoAge(msgName);
    return null;
  }

  async function runTest(t, opts) {
    const o = Object.assign({ settle: suite.defaults.settle, poll: suite.defaults.poll, timeout: suite.defaults.timeout }, opts || {});
    const res = { id: t.id, title: t.title || t.id, suite: t.suite || '—', verdict: 'RUNNING', reason: '', started: Date.now(), ended: 0, steps: [] };
    results.set(t.id, res);
    render();
    log('INFO', '→ ' + t.id + '  ' + (t.title || ''));

    try {
      for (let i = 0; i < t.steps.length; i++) {
        if (abort) { res.verdict = 'INCONC'; res.reason = 'توسط کاربر متوقف شد'; break; }
        const st = t.steps[i];
        if (st.log) { log('INFO', '  ' + st.log); continue; }
        if (st.wait || st.settle !== undefined) { await sleep(Number(st.wait || st.settle)); continue; }

        if (st.set) {
          Object.keys(st.set).forEach((k) => {
            if (k === '$offline') {
              const map = st.set.$offline;
              Object.keys(map).forEach((n) => C.writeOffline(n, !!map[n]));
            } else {
              C.writeSignal(k, st.set[k], 'test');
            }
          });
          await sleep(o.settle);
          continue;
        }

        if (st.expect) {
          const r = evalExpect(st.expect, o);
          res.steps.push({ step: i + 1, ok: r.ok, text: r.text });
          if (!r.ok) { res.verdict = 'FAIL'; res.reason = r.text; break; }
          log('PASS', '  ✓ ' + r.text);
          continue;
        }

        if (st.require) {
          const rq = st.require;
          const deadline = Date.now() + (rq.timeout || o.timeout);
          const op = OPS[rq.op || 'exists'] || OPS['exists'];
          let lastVal;
          while (Date.now() < deadline) {
            lastVal = C.getValue(rq.signal);
            if (op(lastVal, rq.value !== undefined ? rq.value : rq.expected)) break;
            await sleep(o.poll);
          }
          const ok = op(lastVal, rq.value !== undefined ? rq.value : rq.expected);
          const text = 'انتظار ' + rq.signal + ' ' + (rq.op || 'exists') + ' ' + (rq.value !== undefined ? rq.value : '') + ' (مقدار: ' + lastVal + ')';
          res.steps.push({ step: i + 1, ok, text });
          if (!ok) { res.verdict = 'FAIL'; res.reason = 'Timeout: ' + text; break; }
          log('PASS', '  ✓ ' + text);
        }
      }
    } catch (e) {
      res.verdict = 'INCONC'; res.reason = 'خطای اجرا: ' + e.message;
      log('ERR', '  ! ' + e.message);
    }

    if (res.verdict === 'RUNNING') res.verdict = 'PASS';
    res.ended = Date.now();
    res.duration = res.ended - res.started;
    log(res.verdict, '← ' + t.id + '  ' + res.verdict + (res.reason ? '  (' + res.reason + ')' : ''));
    render();
    return res;
  }

  function evalExpect(ex, o) {
    if (ex.offline) {
      const ok = !!C.offline[ex.offline];
      return { ok, text: 'گره ' + ex.offline + ' آفلاین است' + (ok ? '' : ' (نبود)') };
    }
    if (ex.online) {
      const ok = !C.offline[ex.online];
      return { ok, text: 'گره ' + ex.online + ' آنلاین است' + (ok ? '' : ' (نبود)') };
    }
    if (ex.fresh) {
      const limit = ex.within || 2500;
      const age = elapsedMsg(ex.fresh);
      const ok = age != null && age <= limit;
      return { ok, text: 'پیام ' + ex.fresh + ' تازه است (<' + limit + 'ms) — سن: ' + (age == null ? 'نامعلوم' : age + 'ms') };
    }
    if (ex.absent) {
      const limit = ex.within || 2500;
      const age = elapsedMsg(ex.absent);
      const ok = age == null || age > limit;
      return { ok, text: 'پیام ' + ex.absent + ' در ' + limit + 'ms گذشته دیده نشد — سن: ' + (age == null ? 'نامعلوم' : age + 'ms') };
    }
    if (ex.signal) {
      const sig = C.byName.get(ex.signal);
      if (!sig) return { ok: false, text: 'سیگنال ناشناخته: ' + ex.signal };
      const actual = C.getValue(ex.signal);
      const opName = ex.op || ex.operator || '==';
      const op = OPS[opName];
      if (!op) return { ok: false, text: 'اپراتور ناشناخته: ' + opName };
      const expected = ex.value !== undefined ? ex.value : ex.expected;
      const ok = op(actual, expected);
      let text = ex.signal + ' ' + opName + ' ' + (expected !== undefined ? expected : '');
      text += ' — مقدار واقعی: ' + actual;
      return { ok, text };
    }
    return { ok: false, text: 'نوع expect پشتیبانی نمی‌شود' };
  }

  async function runMany(tests) {
    if (running) return;
    running = true; abort = false;
    const t0 = Date.now();
    log('INFO', 'شروع اجرای ' + tests.length + ' تست');
    for (const t of tests) {
      if (abort) break;
      await runTest(t);
    }
    const passed = tests.filter((t) => (results.get(t.id) || {}).verdict === 'PASS').length;
    log('INFO', 'پایان: ' + passed + '/' + tests.length + ' در ' + ((Date.now() - t0) / 1000).toFixed(1) + ' ثانیه');
    running = false;
    render();
  }

  /* ------------------------------------------------------------- render */
  function allTests() { return suite.tests || []; }

  function render() {
    const tb = $('testTable').querySelector('tbody');
    const q = ($('testSearch').value || '').trim().toLowerCase();
    const sf = $('testSuiteFilter').value || '';
    const list = allTests().filter((t) => {
      if (sf && (t.suite || '—') !== sf) return false;
      if (!q) return true;
      return (t.id + ' ' + (t.title || '') + ' ' + (t.suite || '')).toLowerCase().includes(q);
    });
    tb.innerHTML = '';
    list.forEach((t) => {
      const r = results.get(t.id);
      const tr = document.createElement('tr');
      tr.className = 'clickable' + (selection.has(t.id) ? ' sel' : '');
      const c1 = document.createElement('td');
      const cb = document.createElement('input'); cb.type = 'checkbox'; cb.checked = selection.has(t.id);
      cb.onclick = (e) => { e.stopPropagation(); if (cb.checked) selection.add(t.id); else selection.delete(t.id); render(); };
      c1.appendChild(cb); tr.appendChild(c1);

      const c2 = document.createElement('td');
      const sp = document.createElement('span'); sp.className = 'vd ' + (r ? r.verdict : 'NONE');
      sp.textContent = r ? r.verdict : 'NONE'; c2.appendChild(sp); tr.appendChild(c2);

      const c3 = document.createElement('td');
      c3.innerHTML = '<b class="mono" style="font-size:11px">' + t.id + '</b> &nbsp;' + (t.title || '');
      tr.appendChild(c3);

      const c4 = document.createElement('td'); c4.textContent = t.suite || '—'; tr.appendChild(c4);
      const c5 = document.createElement('td'); c5.className = 'mono';
      c5.textContent = r && r.duration ? (r.duration / 1000).toFixed(2) + 's' : '—'; tr.appendChild(c5);
      const c6 = document.createElement('td'); c6.className = 'hint';
      c6.style.maxWidth = '160px'; c6.style.overflow = 'hidden'; c6.style.textOverflow = 'ellipsis';
      c6.title = r ? r.reason : ''; c6.textContent = r ? (r.reason || '—') : '—'; tr.appendChild(c6);

      tr.onclick = async () => {
        if (running) return;
        selection.clear(); selection.add(t.id); render();
        await runMany([t]);
      };
      tb.appendChild(tr);
    });

    // KPI
    const vals = allTests().map((t) => (results.get(t.id) || {}).verdict || 'NONE');
    const count = (v) => vals.filter((x) => x === v).length;
    const k = $('testKpis');
    k.innerHTML = '';
    [['PASS', 'pass'], ['FAIL', 'fail'], ['INCONC', 'inc'], ['RUNNING', 'run'], ['NONE', '']].forEach(([v, cls]) => {
      const d = document.createElement('div'); d.className = 'kpi ' + cls;
      d.innerHTML = '<div class="n">' + count(v) + '</div><div class="l">' + v + '</div>';
      k.appendChild(d);
    });
    const n = document.createElement('div'); n.className = 'kpi';
    n.innerHTML = '<div class="n">' + vals.length + '</div><div class="l">TOTAL</div>';
    k.appendChild(n);

    $('tabTestsN').textContent = vals.length;
    $('tabNodesN').textContent = C.DATA.nodes.length;

    // suite filter
    const sfEl = $('testSuiteFilter');
    const suites = [...new Set(allTests().map((t) => t.suite || '—'))];
    const cur = sfEl.value;
    if (sfEl.dataset.suites !== suites.join('|')) {
      sfEl.dataset.suites = suites.join('|');
      sfEl.innerHTML = '<option value="">همه Suiteها</option>';
      suites.forEach((s) => { const o = document.createElement('option'); o.value = s; o.textContent = s; sfEl.appendChild(o); });
      sfEl.value = cur || '';
    }
  }

  /* ------------------------------------------------------------- reports */
  let lastReport = null;
  function buildReport() {
    const t = allTests().map((tc) => {
      const r = results.get(tc.id);
      return {
        id: tc.id, title: tc.title || tc.id, suite: tc.suite || '—',
        verdict: r ? r.verdict : 'NONE',
        reason: r ? r.reason : '', duration_ms: r ? r.duration : null,
        steps: r ? r.steps : [],
      };
    });
    const count = (v) => t.filter((x) => x.verdict === v).length;
    const env = {
      generated: new Date().toISOString(),
      source: C.stats.source,
      connected: C.stats.connected,
      rx: C.stats.rx, tx: C.stats.tx, latency_ms: C.stats.latency,
      chanHs: C.settings.chanHs, chanLs: C.settings.chanLs,
      dataMeta: C.DATA.meta,
      offline: Object.keys(C.offline).filter((n) => C.offline[n]),
      scenario: { phase: C.scenarioPhaseLabel(), speed: Math.round(C.scenario.speed) },
    };
    lastReport = {
      schema: 'nbcm-test-report/1.0',
      run: {
        id: $('repId').value.trim() || ('RUN-' + new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14)),
        operator: $('repOp').value.trim() || '—',
        dut: $('repDut').value.trim() || 'NBCM',
        tool: 'NBCM CAN Tester (HTML)',
        canoe: 'CANoe 12',
      },
      summary: { total: t.length, pass: count('PASS'), fail: count('FAIL'), inconclusive: count('INCONC'), not_run: count('NONE') },
      tests: t,
      environment: env,
      verdict: count('FAIL') ? 'FAIL' : count('NONE') || count('INCONC') ? 'INCONC' : 'PASS',
    };
    return lastReport;
  }

  function renderReportPanel() {
    if (!lastReport) return;
    const s = lastReport.summary;
    $('repSummary').innerHTML =
      '<div class="kpi pass" style="margin-bottom:6px"><div class="n">' + s.pass + '</div><div class="l">PASS</div></div>' +
      '<div class="kpi fail" style="margin-bottom:6px"><div class="n">' + s.fail + '</div><div class="l">FAIL</div></div>' +
      '<div class="kpi inc" style="margin-bottom:6px"><div class="n">' + s.inconclusive + '</div><div class="l">INCONCLUSIVE</div></div>' +
      '<div class="hint">ورдикт کلی: <b>' + lastReport.verdict + '</b> · اجرا: ' + lastReport.run.id + '</div>';
    const table = $('repTable');
    table.innerHTML = '<tr><th>Verdict</th><th>شناسه</th><th>عنوان</th><th>مدت</th></tr>' +
      lastReport.tests.map((t) =>
        '<tr><td><span class="vd ' + t.verdict + '">' + t.verdict + '</span></td>' +
        '<td class="mono">' + t.id + '</td><td>' + (t.title || '') + (t.reason ? '<div class="hint">' + t.reason + '</div>' : '') + '</td>' +
        '<td class="mono">' + (t.duration_ms != null ? (t.duration_ms / 1000).toFixed(2) + 's' : '—') + '</td></tr>').join('');
    const env = $('repEnv');
    env.innerHTML = '';
    const add = (k, v) => { env.innerHTML += '<dt>' + k + '</dt><dd>' + v + '</dd>'; };
    add('منبع', lastReport.environment.source);
    add('اتصال', String(lastReport.environment.connected));
    add('RX / TX', lastReport.environment.rx + ' / ' + lastReport.environment.tx);
    add('کانال HS / LS', lastReport.environment.chanHs + ' / ' + lastReport.environment.chanLs);
    add('گره‌های آفلاین', lastReport.environment.offline.join(', ') || '—');
    add('تولید', lastReport.environment.generated);
  }

  function toJUnit(rep) {
    const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' }[c]));
    const suites = {};
    rep.tests.forEach((t) => { (suites[t.suite] = suites[t.suite] || []).push(t); });
    let out = '<?xml version="1.0" encoding="UTF-8"?>\n';
    out += '<testsuites name="' + esc(rep.run.dut) + '" tests="' + rep.summary.total + '" failures="' + rep.summary.fail +
      '" skipped="' + rep.summary.not_run + '">\n';
    Object.keys(suites).forEach((sn) => {
      const list = suites[sn];
      const fails = list.filter((t) => t.verdict === 'FAIL').length;
      out += '  <testsuite name="' + esc(sn) + '" tests="' + list.length + '" failures="' + fails + '">\n';
      list.forEach((t) => {
        out += '    <testcase classname="' + esc(sn) + '" name="' + esc(t.id + ' ' + (t.title || '')) +
          '" time="' + ((t.duration_ms || 0) / 1000).toFixed(3) + '"';
        if (t.verdict === 'FAIL') out += '>\n      <failure message="' + esc(t.reason || 'failed') + '"/>\n    </testcase>\n';
        else if (t.verdict === 'NONE' || t.verdict === 'INCONC') out += '>\n      <skipped message="' + esc(t.verdict + ' ' + (t.reason || '')) + '"/>\n    </testcase>\n';
        else out += '/>\n';
      });
      out += '  </testsuite>\n';
    });
    out += '</testsuites>\n';
    return out;
  }

  /* --------------------------------------------------------------- help */
  function showHelp() {
    global.UI.switchView('link');
    log('INFO', 'راهنما: تب «اتصال» را ببینید. مستندات کامل در docs/README.md');
    global.UI.toast('راهنمای اتصال در فایل docs/README.md');
  }

  /* ---------------------------------------------------------------- init */
  function init() {
    // fill editor
    const ta = $('suiteText');
    ta.value = JSON.stringify(suite, null, 2);

    $('runAll').onclick = () => runMany(allTests());
    $('runSel').onclick = () => {
      const list = allTests().filter((t) => selection.has(t.id));
      if (!list.length) { global.UI.toast('هیچ تستی انتخاب نشده'); return; }
      runMany(list);
    };
    $('runFail').onclick = () => {
      const list = allTests().filter((t) => (results.get(t.id) || {}).verdict === 'FAIL');
      if (!list.length) { global.UI.toast('تست FAIL وجود ندارد'); return; }
      runMany(list);
    };
    $('stopRun').onclick = () => { abort = true; log('INCONC', 'درخواست توقف اجرا'); };
    $('selAll').onchange = (e) => {
      selection.clear();
      if (e.target.checked) allTests().forEach((t) => selection.add(t.id));
      render();
    };
    $('testSearch').oninput = () => render();
    $('testSuiteFilter').onchange = () => render();
    $('clearLog').onclick = () => { $('console').innerHTML = ''; };
    $('copyLog').onclick = () => {
      const txt = $('console').innerText;
      if (navigator.clipboard) navigator.clipboard.writeText(txt).then(() => global.UI.toast('لاگ کپی شد'));
    };

    // editor
    $('suiteApply').onclick = () => {
      const msg = $('suiteMsg');
      let obj;
      try { obj = JSON.parse(ta.value); } catch (e) {
        ta.classList.add('err'); msg.className = 'msg show bad'; msg.textContent = 'JSON نامعتبر: ' + e.message; return;
      }
      const errs = validate(obj);
      if (errs.length) {
        ta.classList.add('err'); msg.className = 'msg show bad';
        msg.textContent = 'خطا (' + errs.length + '):\n' + errs.slice(0, 12).join('\n');
        return;
      }
      ta.classList.remove('err');
      suite = normalize(obj);
      validateAndStore(suite);
      results.clear();
      msg.className = 'msg show ok';
      msg.textContent = 'اعمال شد: ' + suite.tests.length + ' تست';
      render();
    };
    $('suiteSave').onclick = () => {
      let obj;
      try { obj = JSON.parse(ta.value); } catch (e) { global.UI.toast('JSON نامعتبر'); return; }
      const errs = validate(obj);
      if (errs.length) { global.UI.toast('ابتدا خطاها را رفع کنید'); return; }
      if (store.set(LSKEY, JSON.stringify(obj))) global.UI.toast('ذخیره شد');
      else global.UI.toast('مرورگر اجازه ذخیره نداد — «خروجی فایل» را بزنید');
    };
    $('suiteLoad').onclick = () => { ta.value = JSON.stringify(loadSuite(), null, 2); global.UI.toast('بارگذاری شد'); };
    $('suiteDefault').onclick = () => { ta.value = JSON.stringify(makeDefaultSuite(), null, 2); global.UI.toast('سوئیت پیش‌فرض بازسازی شد'); };
    $('fmtJson').onclick = () => {
      try { ta.value = JSON.stringify(JSON.parse(ta.value), null, 2); } catch (e) { global.UI.toast('JSON نامعتبر'); }
    };
    $('suiteImport').onclick = () => $('suiteFile').click();
    $('suiteFile').onchange = (e) => {
      const f = e.target.files[0]; if (!f) return;
      const fr = new FileReader();
      fr.onload = () => { ta.value = String(fr.result); global.UI.toast('فایل خوانده شد؛ «اعمال» را بزنید'); };
      fr.readAsText(f);
    };
    $('suiteExport').onclick = () => {
      const blob = new Blob([ta.value], { type: 'application/json' });
      const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'test_suite.json'; a.click();
    };

    // reference
    $('refBox').innerHTML = [
      '<b>wait / settle</b> — انتظار به میلی‌ثانیه',
      '<b>set</b> — نوشتن سیگنال: <code>{"set":{"Hs_Abs_VehicleSpeed":60}}</code>',
      '<b>set $offline</b> — قطع/وصل گره: <code>{"set":{"$offline":{"ABS":true}}}</code>',
      '<b>expect signal</b> — <code>{"expect":{"signal":"…","op":">=","value":1}}</code>',
      '<b>expect offline/online</b> — وضعیت گره',
      '<b>expect fresh/absent</b> — تازگی پیام (Timeout): <code>{"expect":{"fresh":"HS_ID_ABS","within":2000}}</code>',
      '<b>require</b> — انتظار تا برقراری شرط: <code>{"require":{"signal":"…","op":"==","value":1,"timeout":3000}}</code>',
      '<br>اپراتورها: <code>== != &gt; &gt;= &lt; &lt;= ~= exists notexists</code>',
      '<br>این فایل در مسیر <code>tests/test_suite.json</code> هم نگه‌داری می‌شود تا در CI قابل استفاده باشد.',
    ].join('<br>');

    // report
    $('repBuild').onclick = () => {
      const rep = buildReport();
      renderReportPanel();
      log('INFO', 'گزارش ساخته شد: ' + rep.verdict);
      global.UI.toast('گزارش ساخته شد (' + rep.verdict + ')');
    };
    $('repJson').onclick = () => {
      const rep = buildReport(); renderReportPanel();
      const blob = new Blob([JSON.stringify(rep, null, 2)], { type: 'application/json' });
      const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
      a.download = 'report_' + rep.run.id + '.json'; a.click();
    };
    $('repJunit').onclick = () => {
      const rep = buildReport(); renderReportPanel();
      const blob = new Blob([toJUnit(rep)], { type: 'application/xml' });
      const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
      a.download = 'junit_' + rep.run.id + '.xml'; a.click();
    };
    $('repPrint').onclick = () => {
      buildReport(); renderReportPanel(); window.print();
    };

    render();
    if (!store.ok) {
      log('INFO', 'حالت file:// — ذخیره محلی در دسترس نیست؛ برای ماندگاری از «خروجی فایل» استفاده کنید.');
    }
    if (!store.ok) {
      const m = $('suiteMsg');
      m.className = 'msg show';
      m.style.background = 'rgba(255,204,77,.12)';
      m.style.color = 'var(--warn)';
      m.textContent = 'این صفحه با file:// باز شده است؛ ذخیره محلی ممکن نیست. '
        + 'برای ماندگاری از «خروجی فایل» استفاده کنید یا تستر را از پل (http://127.0.0.1:8771) باز کنید.';
    }
  }

  global.Tests = {
    init, render, runMany, runTest, getSuite, setSuite, buildReport,
    getLastReport: () => lastReport, defaultSuite, showHelp, toJUnit, suite: () => suite,
  };
})(window);

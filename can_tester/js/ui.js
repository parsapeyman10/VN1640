/* ==========================================================================
   ui.js — rendering, panels, live gauges, echo / timeout monitoring
   ========================================================================== */
(function (global) {
  'use strict';
  const C = global.Core;
  const $ = (id) => document.getElementById(id);
  const el = (tag, attrs, kids) => {
    const n = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach((k) => {
      if (k === 'class') n.className = attrs[k];
      else if (k === 'html') n.innerHTML = attrs[k];
      else if (k === 'text') n.textContent = attrs[k];
      else if (k.slice(0, 2) === 'on' && typeof attrs[k] === 'function') n.addEventListener(k.slice(2), attrs[k]);
      else n.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach((c) => { if (c) n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  };
  const fmt = (v) => (typeof v === 'number' ? (Number.isInteger(v) ? String(v) : v.toFixed(2)) : String(v == null ? '—' : v));

  const UI = { view: 'control', ctrlNode: (C.DATA.nodes[0] || {}).node || 'ABS', ctrlQuery: '', onlyOverridden: false, onlyBool: false };

  /* ------------------------------------------------------------- toast */
  let toastT = null;
  function toast(msg) {
    const t = $('toast'); t.textContent = msg; t.classList.add('show');
    clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove('show'), 1900);
  }

  /* ------------------------------------------------------------- tabs */
  function switchView(name) {
    UI.view = name;
    document.querySelectorAll('nav.tabs button').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.view === name)));
    document.querySelectorAll('.view').forEach((v) => v.classList.toggle('active', v.id === 'view-' + name));
    if (name === 'nodes') renderNodes();
    if (name === 'tests') global.Tests.render();
    if (name === 'report') global.Tests.renderReportPanel && global.Tests.renderReportPanel();
    if (name === 'link') renderLink();
    if (name === 'help') global.Info && global.Info.renderHelp();
  }

  /* ------------------------------------------------------------- header */
  function renderHeader() {
    const m = C.DATA.meta || {};
    $('metaInfo').textContent = (m.nodes || 0) + ' nodes · ' + (m.messages || 0) + ' msgs · ' + (m.signals || 0) + ' sigs';
    renderConn();
    renderDrive();
    const hs = $('chanHs'), ls = $('chanLs');
    [hs, ls].forEach((sel) => { if (!sel.options.length) { for (let i = 1; i <= 8; i++) sel.appendChild(el('option', { value: String(i) }, ['CH ' + i])); } });
    hs.value = String(C.settings.chanHs); ls.value = String(C.settings.chanLs);
    hs.onchange = () => C.saveSettings({ chanHs: hs.value });
    ls.onchange = () => C.saveSettings({ chanLs: ls.value });
  }

  function renderConn() {
    const s = C.stats;
    const dot = $('connDot');
    dot.className = 'dot ' + (s.connected ? 'ok' : 'bad');
    const label = { sim: 'Simulator', ws: 'WebSocket', http: 'HTTP' }[s.source] || s.source;
    $('connText').textContent = s.connected ? label : (label + ' · قطع');
    $('connPill').title = s.lastError || (s.connected ? 'اتصال برقرار است' : 'اتصال قطع است');
  }

  // Surfaces bridge-side degradations that would otherwise look like "no data":
  // CANoe not reachable, or the NBCM_Test system variables missing in the config.
  function renderHealth(h) {
    const pill = $('connPill');
    if (!h) return;
    if (h.mode === 'sim') {
      pill.title = 'پل در حالت شبیه‌سازی است (CANoe وصل نیست).';
      return;
    }
    if (h.canoe && !h.sysvars) {
      pill.title = 'CANoe وصل است اما متغیرهای NBCM_Test پیدا نشد. '
        + 'فایل canoe/NBCM_Test.vsysvar را به کانفیگ اضافه کنید.';
      $('connText').textContent = 'CANoe · بدون System Variable';
      return;
    }
    if (!h.canoe) {
      pill.title = 'پل به CANoe وصل نشد: ' + (h.error || 'خطای نامشخص');
      $('connText').textContent = 'CANoe · قطع';
    } else {
      pill.title = 'CANoe متصل و System Variableها آماده‌اند.';
    }
  }

  function renderMeas(m) {
    const dot = $('measDot'), txt = $('measText');
    if (!m || typeof m.running !== 'boolean') { dot.className = 'dot'; txt.textContent = 'نامعلوم'; return; }
    dot.className = 'dot ' + (m.running ? 'ok' : 'warn');
    txt.textContent = m.running ? 'Measurement در حال اجرا' : 'Measurement متوقف';
  }

  function renderDrive() {
    const on = C.stats.driveMode === 1;
    $('driveDot').className = 'dot ' + (on ? 'ok' : 'warn');
    $('driveText').textContent = on ? 'کنترل: تستر' : 'کنترل: CANoe';
    $('driveBtn').title = on
      ? 'تستر مقادیر را روی باس می‌نویسد (DRIVE_MODE=1)'
      : 'سناریوی داخلی CANoe مالک سیگنال‌هاست — برای نوشتن روی باس کلیک کنید';
  }

  /* ------------------------------------------------------ control panel */
  function renderNodeSelect() {
    const sel = $('ctrlNode');
    sel.innerHTML = '';
    C.DATA.nodes.forEach((n) => {
      sel.appendChild(el('option', { value: n.node }, [
        n.node + '  ·  ' + n.nMsg + ' msg / ' + n.nSig + ' sig  (' + n.net + ')',
      ]));
    });
    sel.value = UI.ctrlNode;
    sel.onchange = () => { UI.ctrlNode = sel.value; renderControlTable(); };
  }

  function filteredSignals() {
    const q = UI.ctrlQuery.trim().toLowerCase();
    return (C.byNode.get(UI.ctrlNode) || []).filter((s) => {
      if (UI.onlyBool && s.kind !== 'bool') return false;
      if (UI.onlyOverridden && !C.meta[s.sig].overridden) return false;
      if (!q) return true;
      return s.sig.toLowerCase().includes(q) || s.msg.toLowerCase().includes(q);
    });
  }

  const ROWS_PER_CHUNK = 120;
  let ctrlChunk = 1;

  function renderControlTable() {
    const tbody = $('ctrlTable').querySelector('tbody');
    const list = filteredSignals();
    const shown = list.slice(0, ctrlChunk * ROWS_PER_CHUNK);
    tbody.innerHTML = '';
    const frag = document.createDocumentFragment();
    shown.forEach((s) => frag.appendChild(controlRow(s)));
    tbody.appendChild(frag);
    if (list.length > shown.length) {
      const tr = el('tr', {}, [el('td', { colspan: '6' }, [])]);
      const td = tr.firstChild;
      td.appendChild(el('button', {
        class: 'btn sm', text: 'نمایش ' + Math.min(ROWS_PER_CHUNK, list.length - shown.length) + ' مورد بیشتر',
        onclick: () => { ctrlChunk += 1; renderControlTable(); },
      }));
      tbody.appendChild(tr);
    }
    $('ctrlCount').textContent = shown.length + ' / ' + list.length + ' سیگنال';
  }

  function controlRow(s) {
    const tr = el('tr', { 'data-sig': s.sig, 'data-id': s.id });
    const nametd = el('td', { class: 'sigcol mono', title: s.sig + '\n' + s.id });
    nametd.appendChild(el('span', { text: s.sig }));
    // the circled "!" that explains the signal on hover and on click
    if (global.Info) nametd.appendChild(global.Info.button(global.Info.record(s.id, s.sig), s.sig));
    tr.appendChild(nametd);

    const vtd = el('td', { class: 'valcol' });
    const m = C.meta[s.sig];

    if (s.kind === 'bool') {
      const lab = el('label', { class: 'switch' });
      const cb = el('input', { type: 'checkbox' });
      cb.checked = !!C.values[s.sig];
      cb.onchange = () => { C.writeSignal(s.sig, cb.checked ? 1 : 0); m.overridden = true; refreshRow(tr, s); };
      lab.appendChild(cb); lab.appendChild(el('span', { class: 'sl' }));
      vtd.appendChild(lab);
    } else if (s.kind === 'enum' && s.max <= 8) {
      const sel = el('select', { style: 'width:70px;padding:2px 4px' });
      for (let i = 0; i <= s.max; i++) sel.appendChild(el('option', { value: String(i), text: String(i) }));
      sel.value = String(C.values[s.sig] || 0);
      sel.onchange = () => { C.writeSignal(s.sig, Number(sel.value)); m.overridden = true; refreshRow(tr, s); };
      vtd.appendChild(sel);
    } else {
      const inp = el('input', { type: 'number', min: s.min, max: s.max, step: s.kind === 'enum' ? 1 : 'any' });
      inp.value = fmt(C.values[s.sig]);
      inp.onchange = () => { C.writeSignal(s.sig, Number(inp.value)); m.overridden = true; refreshRow(tr, s); };
      vtd.appendChild(inp);
    }
    tr.appendChild(vtd);

    tr.appendChild(el('td', { class: 'unitcol', text: s.unit || '—' }));

    const rtd = el('td', { class: 'rngcol' });
    if (s.kind !== 'bool') {
      const range = el('input', { type: 'range', min: s.min, max: s.max, step: s.kind === 'enum' ? 1 : 'any' });
      range.value = C.values[s.sig];
      range.oninput = () => {
        C.writeSignal(s.sig, Number(range.value)); m.overridden = true;
        const num = vtd.querySelector('input[type=number]');
        if (num) num.value = fmt(Number(range.value));
        refreshRow(tr, s, true);
      };
      rtd.appendChild(range);
    } else rtd.appendChild(el('span', { class: 'hint', text: '—' }));
    tr.appendChild(rtd);

    tr.appendChild(el('td', { class: 'unitcol mono', title: s.msg,
      text: s.msg.replace(/^(HS|LS)_ID_/, '') + ' · ' + s.cycle + 'ms' }));

    const act = el('td');
    const tag = el('span', { class: 'out-tag' + (m.overridden ? ' on' : ''), text: m.overridden ? 'دستی' : 'باس' });
    if (m.overridden) {
      tag.title = 'کلیک برای بازگرداندن به مقدار باس';
      tag.style.cursor = 'pointer';
      tag.onclick = () => { C.releaseOverride(s.sig); refreshRow(tr, s); };
    }
    act.appendChild(tag);
    tr.appendChild(act);
    if (C.offline[s.node]) tr.classList.add('off');
    return tr;
  }

  function refreshRow(tr, s, onlyRange) {
    const m = C.meta[s.sig];
    if (!onlyRange) {
      const num = tr.querySelector('.valcol input[type=number]');
      const cb = tr.querySelector('.valcol input[type=checkbox]');
      const sel = tr.querySelector('.valcol select');
      const v = C.values[s.sig];
      if (num && document.activeElement !== num) num.value = fmt(v);
      if (cb) cb.checked = !!v;
      if (sel && document.activeElement !== sel) sel.value = String(v);
    }
    const rng = tr.querySelector('input[type=range]');
    if (rng && document.activeElement !== rng) rng.value = C.values[s.sig];
    const tag = tr.querySelector('.out-tag');
    if (tag) { tag.classList.toggle('on', m.overridden); tag.textContent = m.overridden ? 'دستی' : 'باس'; }
  }

  function refreshVisibleRows(names) {
    const set = names ? new Set(names) : null;
    document.querySelectorAll('#ctrlTable tbody tr[data-sig]').forEach((tr) => {
      if (set && !set.has(tr.dataset.sig)) return;
      const s = C.byId.get(tr.dataset.id);
      if (s) refreshRow(tr, s);
    });
  }

  /* -------------------------------------------------------------- nodes */
  function renderNodes() {
    const grid = $('nodeGrid');
    grid.innerHTML = '';
    let online = 0;
    C.DATA.nodes.forEach((n) => {
      const off = C.offline[n.node];
      if (!off) online += 1;
      const card = el('div', { class: 'node' + (off ? ' off' : ''), 'data-node': n.node });
      const top = el('div', { class: 'top' });
      const nm = el('span', { class: 'nm', text: n.node });
      if (global.Info) nm.appendChild(global.Info.button(global.Info.record(null, null, n.node), n.node));
      top.appendChild(nm);
      top.appendChild(el('span', { class: 'badge ' + n.net.toLowerCase(), text: n.net + '-CAN' }));
      card.appendChild(top);
      card.appendChild(el('div', { class: 'meta', text: n.nMsg + ' پیام · ' + n.nSig + ' سیگنال' }));

      const bar = el('div', { class: 'bar' });
      const sent = n.msgs.filter((mm) => !off).length;
      for (let i = 0; i < n.msgs.length; i++) {
        bar.appendChild(el('i', { style: 'width:' + (100 / n.msgs.length) + '%;opacity:' + (i < sent ? 1 : 0.15) }));
      }
      card.appendChild(bar);

      const actions = el('div', { class: 'actions' });
      const sw = el('label', { class: 'switch', title: 'قطع/وصل گره' });
      const cb = el('input', { type: 'checkbox' });
      cb.checked = off;
      cb.onchange = () => { C.writeOffline(n.node, cb.checked); renderNodes(); };
      sw.appendChild(cb); sw.appendChild(el('span', { class: 'sl' }));
      actions.appendChild(sw);
      actions.appendChild(el('button', {
        class: 'btn sm', text: 'کنترل', onclick: () => { UI.ctrlNode = n.node; $('ctrlNode').value = n.node; switchView('control'); renderControlTable(); },
      }));
      card.appendChild(actions);
      grid.appendChild(card);
    });
    $('nodesSummary').textContent = online + ' از ' + C.DATA.nodes.length + ' گره آنلاین';
    renderEcho();
  }

  /* --------------------------------------------------- echo / monitoring */
  // last-seen timestamp per message key, driven by real frames from the adapter
  const echo = new Map();   // key -> { msg, net, node, cycle, last, count, miss }
  C.DATA.nodes.forEach((n) => n.msgs.forEach((m) => {
    echo.set(n.net + ':' + m.msg, { msg: m.msg, net: n.net, node: n.node, cycle: m.cycle, last: 0, count: 0, miss: 0 });
  }));

  C.on('busframe', (key) => {
    const e = echo.get(key);
    if (!e) return;
    e.last = Date.now(); e.count += 1;
  });

  // In live mode the bridge is the authority on liveness: it knows which
  // messages CANoe actually received, including ones the panel never watched.
  C.on('msgage', (ages) => {
    const now = Date.now();
    Object.keys(ages || {}).forEach((key) => {
      const e = echo.get(key);
      if (!e) return;
      e.age = ages[key];
      e.last = now - ages[key];
    });
  });

  function echoAge(msgName) {
    const e = echo.get('HS:' + msgName) || echo.get('LS:' + msgName);
    if (!e) return null;
    if (typeof e.age === 'number' && C.stats.source !== 'sim') return e.age;
    if (!e.last) return null;
    return Date.now() - e.last;
  }
  function echoFor(key) { return echo.get(key); }

  function renderEcho() {
    const list = $('echoList');
    if (!list) return;
    const q = ($('echoSearch') && $('echoSearch').value.trim().toLowerCase()) || '';
    const rows = [...echo.values()]
      .filter((e) => !q || e.msg.toLowerCase().includes(q))
      .sort((a, b) => a.msg.localeCompare(b.msg));
    list.innerHTML = '';
    const now = Date.now();
    rows.slice(0, 400).forEach((e) => {
      const age = e.last ? now - e.last : null;
      const off = C.offline[e.node];
      const limit = Math.max(2500, e.cycle * 2.5);
      // stale is reported even for a node we switched off: the point of the
      // table is to show *when* traffic stopped, not only why.
      const stale = age != null && age > limit;
      const r = el('div', { class: 'statrow' + (stale ? ' stale' : '') });
      r.appendChild(el('i', { class: 'dot ' + (off ? 'bad' : stale ? 'warn' : age == null ? '' : 'ok') }));
      r.appendChild(el('span', { class: 'nm mono', text: e.msg }));
      r.appendChild(el('span', { class: 'cyc mono', text: '⏱' + e.cycle + 'ms' }));
      r.appendChild(el('span', { class: 'cyc', text: C.offline[e.node] ? e.node : '' }));
      r.appendChild(el('span', { class: 'age mono', title: 'سن آخرین دریافت', text: age == null ? '—' : (age / 1000).toFixed(1) + 's' }));
      r.appendChild(el('span', { class: 'miss mono', text: stale ? (off ? 'OFFLINE' : 'TIMEOUT') : '' }));
      list.appendChild(r);
    });
  }

  function resetEcho() { echo.forEach((e) => { e.miss = 0; e.last = 0; e.count = 0; }); renderEcho(); }

  /* ------------------------------------------------------------- gauges */
  let tickCount = 0, lastRateT = performance.now();
  function gaugesTick() {
    const now = performance.now();
    tickCount += 1;
    if (now - lastRateT >= 500) {
      C.stats.rate = Math.round((tickCount * 1000) / (now - lastRateT));
      tickCount = 0; lastRateT = now;
    }
    const A = C.ALIAS;
    if (A.speed) $('gSpeed').textContent = Math.round(C.values[A.speed.sig] || 0);
    if (A.rpm) $('gRpm').textContent = Math.round(C.values[A.rpm.sig] || 0);
    if (A.fuel) $('gFuel').textContent = (C.values[A.fuel.sig] || 0).toFixed(0);
    if (A.odo) $('gOdo').textContent = ((C.values[A.odo.sig] || 0) / 1000).toFixed(1);
    $('gSpeedSig').textContent = A.speed ? A.speed.sig : 'یافت نشد';
    $('rateV').textContent = C.stats.rate;
    $('rxV').textContent = C.stats.rx;
    $('txV').textContent = C.stats.tx;
    $('latV').textContent = C.stats.latency == null ? '—' : C.stats.latency + 'ms';
    $('drvPhase').textContent = C.scenarioPhaseLabel();
    if (!C.scenario.manual) {
      $('drvSpeed').value = Math.round(C.scenario.speed);
      $('drvSpeedV').textContent = Math.round(C.scenario.speed) + ' km/h';
    }
  }

  /* ----------------------------------------------------------- link view */
  function renderLink() {
    $('srcMode').value = C.settings.mode;
    $('srcUrl').value = C.settings.wsUrl;
    $('mapHs').value = C.settings.chanHs;
    $('mapLs').value = C.settings.chanLs;
    $('mapPort').value = C.settings.port;
    $('mapDut').value = C.settings.dut;
    const dl = $('linkStatus');
    const s = C.stats;
    dl.innerHTML = '';
    const add = (k, v) => { dl.appendChild(el('dt', { text: k })); dl.appendChild(el('dd', { text: v })); };
    add('حالت', s.source);
    add('وضعیت', s.connected ? 'متصل' : 'قطع');
    add('RX frames', String(s.rx));
    add('TX frames', String(s.tx));
    add('Latency', s.latency == null ? '—' : s.latency + ' ms');
    add('آخرین خطا', s.lastError || '—');
    add('HS کانال', C.settings.chanHs);
    add('LS کانال', C.settings.chanLs);
  }

  /* ------------------------------------------------------------- theme */
  function applyTheme(t) {
    document.documentElement.setAttribute('data-theme', t === 'light' ? 'light' : 'dark');
    C.saveSettings({ theme: t });
  }

  /* -------------------------------------------------------------- boot */
  function init() {
    applyTheme(C.settings.theme);
    renderHeader();
    renderNodeSelect();
    renderControlTable();
    renderNodes();

    document.querySelectorAll('nav.tabs button').forEach((b) => {
      b.addEventListener('click', () => switchView(b.dataset.view));
    });

    // control toolbar
    $('ctrlSearch').addEventListener('input', (e) => { UI.ctrlQuery = e.target.value; ctrlChunk = 1; renderControlTable(); });
    $('ctrlRelease').onclick = () => {
      const n = C.releaseAll();
      C.scenario.fuel = 70;
      ctrlChunk = 1; renderControlTable();
      toast(n.length ? n.length + ' سیگنال آزاد شد' : 'مقدار دستی فعال نیست');
    };
    $('ctrlOverridden').addEventListener('click', (e) => {
      UI.onlyOverridden = !UI.onlyOverridden;
      e.currentTarget.setAttribute('aria-pressed', String(UI.onlyOverridden));
      ctrlChunk = 1; renderControlTable();
    });
    $('ctrlBoolOnly').addEventListener('click', (e) => {
      UI.onlyBool = !UI.onlyBool;
      e.currentTarget.setAttribute('aria-pressed', String(UI.onlyBool));
      ctrlChunk = 1; renderControlTable();
    });

    $('drvSpeed').disabled = !C.scenario.manual;
    // scenario controls
    $('drvPlay').onclick = () => {
      C.scenario.running = !C.scenario.running;
      $('drvPlay').textContent = C.scenario.running ? '⏸ توقف' : '▶ ادامه';
    };
    $('drvReset').onclick = () => { C.scenarioReset(); toast('سناریو ریست شد'); };
    $('drvManual').onchange = (e) => {
      C.scenario.manual = e.target.checked;
      $('drvSpeed').disabled = !e.target.checked;
      if (e.target.checked) {
        // start from the current speed so flipping the switch does not jump to 0
        C.scenario.manualSpeed = Math.round(C.scenario.speed);
        $('drvSpeed').value = C.scenario.manualSpeed;
        $('drvSpeedV').textContent = C.scenario.manualSpeed + ' km/h';
      }
    };
    $('drvEngage').onchange = (e) => { C.scenario.engaged = e.target.checked; };
    $('drvSpeed').oninput = (e) => {
      C.scenario.manualSpeed = Number(e.target.value);
      $('drvSpeedV').textContent = e.target.value + ' km/h';
    };

    // nodes bulk
    $('allOnline').onclick = () => { C.DATA.nodes.forEach((n) => C.writeOffline(n.node, false)); renderNodes(); };
    $('allOffline').onclick = () => { C.DATA.nodes.forEach((n) => C.writeOffline(n.node, true)); renderNodes(); };
    $('echoReset').onclick = resetEcho;
    $('echoSearch').addEventListener('input', renderEcho);

    // theme + help
    $('themeBtn').onclick = () => applyTheme(C.settings.theme === 'dark' ? 'light' : 'dark');
    $('helpBtn').onclick = () => global.Tests.showHelp && global.Tests.showHelp();
    $('driveBtn').onclick = () => {
      const next = C.stats.driveMode !== 1;
      C.setDriveMode(next);
      renderDrive();
      toast(next ? 'کنترل به تستر منتقل شد (DRIVE_MODE=1)' : 'کنترل به سناریوی CANoe برگشت (DRIVE_MODE=0)');
    };

    // link view
    $('srcConnect').onclick = async () => {
      const mode = $('srcMode').value;
      C.saveSettings({ mode, wsUrl: $('srcUrl').value.trim() || C.settings.wsUrl });
      const msg = $('srcMsg');
      msg.className = 'msg show'; msg.textContent = 'در حال اتصال…';
      try {
        await C.connect(mode);
        msg.className = 'msg show ok'; msg.textContent = 'متصل شد: ' + C.stats.source;
        renderLink(); renderConn();
      } catch (e) {
        msg.className = 'msg show bad';
        msg.textContent = 'اتصال ناموفق: ' + e.message + ' — به حالت Simulator برگشتیم.';
        await C.connect('sim');
        renderLink(); renderConn();
      }
    };
    $('srcDisconnect').onclick = () => { const a = C.currentAdapter(); if (a) a.disconnect(); renderConn(); renderLink(); };
    $('mapSave').onclick = () => {
      C.saveSettings({
        chanHs: $('mapHs').value.trim() || '1', chanLs: $('mapLs').value.trim() || '2',
        port: $('mapPort').value.trim() || '8770', dut: $('mapDut').value.trim() || 'NBCM',
      });
      renderHeader(); toast('تنظیمات کانال ذخیره شد');
    };
    $('mapCopy').onclick = () => {
      const cfg = { chanHs: Number(C.settings.chanHs), chanLs: Number(C.settings.chanLs), port: Number(C.settings.port), dut: C.settings.dut };
      const txt = JSON.stringify(cfg, null, 2);
      if (navigator.clipboard) navigator.clipboard.writeText(txt).then(() => toast('کپی شد'), () => toast(txt));
      else toast(txt);
    };

    // exports
    const dl = (name, text, type) => {
      const blob = new Blob([text], { type: type || 'application/json' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob); a.download = name; a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 4000);
    };
    UI.download = dl;
    $('dlSignals').onclick = () => dl('signal_map.json', JSON.stringify({
      meta: C.DATA.meta, nodes: C.DATA.nodes, signals: C.DATA.signals,
    }, null, 1));
    $('dlSuite').onclick = () => dl('test_suite.json', JSON.stringify(global.Tests.getSuite(), null, 2));
    $('dlReport').onclick = () => dl('report.json', JSON.stringify(global.Tests.getLastReport() || {}, null, 2));

    // live updates
    C.on('connection', () => { renderConn(); if (UI.view === 'link') renderLink(); });
    UI._echoFor = echoFor;
    C.on('meas', renderMeas);
    C.on('health', renderHealth);
    C.on('drive', renderDrive);
    C.on('signals', (names) => { if (UI.view === 'control') refreshVisibleRows(names); });

    C.on('offline', () => { if (UI.view === 'nodes') renderNodes(); if (UI.view === 'control') refreshVisibleRows(); });
    C.on('tick', renderConn);

    setInterval(gaugesTick, 250);
    setInterval(() => { if (UI.view === 'nodes') renderEcho(); }, 700);
    requestAnimationFrame(scenarioLoop);

    let scLast = performance.now();
    function scenarioLoop(now) {
      const dt = Math.min(now - scLast, 250);
      scLast = now;
      // x4 time-lapse so a full urban->highway->brake cycle is visible quickly
      C.scenarioTick(dt * 4);
      requestAnimationFrame(scenarioLoop);
    }
  }

  global.UI = Object.assign(UI, { toast, switchView, renderNodes, renderControlTable, renderEcho, renderConn, renderMeas, renderLink, applyTheme, init, echoAge, echoFor, renderDrive, renderHealth });
})(window);

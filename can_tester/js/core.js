/* ==========================================================================
   core.js — data model, transport adapters, signal I/O, driving scenario
   No build step, no dependencies. Loaded after assets/data.js
   ========================================================================== */
(function (global) {
  'use strict';

  const DATA = global.NBCM_DATA || { nodes: [], signals: [], meta: {} };
  const LS = {
    get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private mode */ } },
  };

  /* ------------------------------------------------------------- settings */
  const DEFAULT_SETTINGS = {
    mode: 'sim',                    // sim | auto | ws | http
    wsUrl: 'ws://127.0.0.1:8770/',
    httpUrl: 'http://127.0.0.1:8770',
    chanHs: '1',
    chanLs: '2',
    port: '8770',
    dut: 'NBCM',
    theme: 'dark',
  };
  const settings = Object.assign({}, DEFAULT_SETTINGS, LS.get('nbcm.settings', {}));
  function saveSettings(patch) {
    Object.assign(settings, patch || {});
    LS.set('nbcm.settings', settings);
    emit('settings', settings);
  }

  /* ------------------------------------------------------------- event bus */
  const handlers = {};
  function on(evt, fn) { (handlers[evt] = handlers[evt] || []).push(fn); return () => off(evt, fn); }
  function off(evt, fn) { handlers[evt] = (handlers[evt] || []).filter((f) => f !== fn); }
  function emit(evt, payload) { (handlers[evt] || []).forEach((f) => { try { f(payload); } catch (e) { console.error(e); } }); }

  /* ---------------------------------------------------------- signal index */
  const byId = new Map();
  const byNode = new Map();
  const byMsg = new Map();          // key "NET:MSG"
  DATA.signals.forEach((s) => {
    byId.set(s.id, s);
    if (!byNode.has(s.node)) byNode.set(s.node, []);
    byNode.get(s.node).push(s);
    const mk = s.net + ':' + s.msg;
    if (!byMsg.has(mk)) byMsg.set(mk, { key: mk, net: s.net, msg: s.msg, sigs: [] });
    byMsg.get(mk).sigs.push(s);
  });
  const byName = new Map();         // CAPL variable name -> signal (first wins, stable)
  DATA.signals.forEach((s) => { if (!byName.has(s.sig)) byName.set(s.sig, s); });

  /* --------------------------------------------------------- value store */
  // A single logical value per physical signal name keeps duplicates in sync
  // (same CAPL variable may appear in more than one message definition).
  const values = Object.create(null);
  const meta = Object.create(null);   // name -> { overridden, ts, src }
  DATA.signals.forEach((s) => {
    if (!(s.sig in values)) { values[s.sig] = s.def; }
    if (!meta[s.sig]) meta[s.sig] = { overridden: false, ts: 0, src: 'init' };
  });

  const offline = Object.create(null);
  DATA.nodes.forEach((n) => { offline[n.node] = false; });

  const stats = {
    rx: 0, tx: 0,     // frames counted from the adapter
    rate: 0,
    latency: null,
    connected: false,
    source: 'sim',
    lastError: '',
    health: null,
    driveMode: 0,          // 0 = CANoe scenario owns signals, 1 = tester owns
    sysvars: false,
  };

  function clampNum(sig, v) {
    const n = typeof v === 'number' ? v : parseFloat(v);
    if (!isFinite(n)) return sig.def;
    if (sig.kind === 'bool') return n ? 1 : 0;
    return Math.min(sig.max, Math.max(sig.min, Math.round(n * 1000) / 1000));
  }

  /* Writes a value into the value store.
     Ownership rules (this is what keeps panel, scenario and bus from fighting):
       src='panel'  | 'test'      -> operator intent, marks the signal overridden
       src='scenario'             -> ignored while the signal is overridden
       src='bus'    | 'restbus'   -> measurement echo, never clears an override
  */
  function setValue(sigNameOrId, value, opts) {
    const sig = byId.get(sigNameOrId) || byName.get(sigNameOrId);
    if (!sig) return false;
    const o = opts || {};
    const src = o.src || 'local';
    const m = meta[sig.sig];
    if (src === 'scenario' && m.overridden) return false;
    const v = clampNum(sig, value);
    values[sig.sig] = v;
    if (src === 'panel' || src === 'test' || o.override) m.overridden = true;
    m.ts = Date.now();
    m.src = src;
    emit('signal:' + sig.sig, v);
    emit('signals', [sig.sig]);
    return true;
  }

  function getValue(sigNameOrId) {
    const sig = byId.get(sigNameOrId) || byName.get(sigNameOrId);
    if (!sig) return undefined;
    return values[sig.sig];
  }

  function releaseOverride(sigName) {
    const m = meta[sigName];
    if (m) { m.overridden = false; m.src = 'release'; }
    emit('signals', [sigName]);
  }

  /* Clears every manual override (used by "release all" and by test teardown). */
  function releaseAll() {
    const names = [];
    Object.keys(meta).forEach((n) => {
      if (meta[n].overridden) { meta[n].overridden = false; meta[n].src = 'release'; names.push(n); }
    });
    if (names.length) emit('signals', names);
    return names;
  }

  function setOffline(node, flag) {
    if (!(node in offline)) return;
    offline[node] = !!flag;
    emit('offline', { node, flag: !!flag });
  }

  /* --------------------------------------------------------- signal alias */
  // Shared "vehicle" signals used by the scenario engine. The workbook is the
  // source of truth, but names are resolved leniently so a DBC rename does not
  // break the dashboard.
  function findSig(candidates) {
    for (const c of candidates) { if (byName.has(c)) return byName.get(c); }
    for (const c of candidates) {
      const lower = c.toLowerCase();
      for (const s of DATA.signals) if (s.sig.toLowerCase() === lower) return s;
    }
    return null;
  }
  const ALIAS = {
    speed: findSig(['Hs_Abs_VehicleSpeed', 'Hs_Ems_VehicleSpeed', 'LS_ICN_SPD_GWY']),
    speedValid: findSig(['Hs_Abs_VehicleSpeed_Invalid', 'Hs_Abs_VehicleSpeedValid']),
    rpm: findSig(['Hs_Ems_Rpm', 'Hs_Ems_EngineSpeed', 'Hs_Ems_N']),
    fuel: findSig(['Hs_Ems_Fuel_Tank_Level_Out', 'Hs_Ems_FuelLevel']),
    odo: findSig(['LS_ICN_ODO', 'Ls_Icn_Mileage', 'Hs_Ems_Distance']),
  };

  /* ------------------------------------------------------- driving scenario */
  const PHASES = [
    { id: 'idle', fa: 'درجا', target: 0, hold: 3000 },
    { id: 'urbanAccel', fa: 'شتاب شهری', target: 50, hold: 0 },
    { id: 'urban', fa: 'ثابت شهری', target: 50, hold: 10000 },
    { id: 'hwAccel', fa: 'شتاب جاده‌ای', target: 110, hold: 0 },
    { id: 'highway', fa: 'ثابت جاده‌ای', target: 110, hold: 15000 },
    { id: 'brake', fa: 'ترمزگیری', target: 0, hold: 0 },
  ];
  const scenario = {
    running: true,
    manual: false,
    engaged: true,
    manualSpeed: 0,
    phase: 0,
    phaseT: 0,
    speed: 0,
    odoKm: 12345.0,
    fuel: 70,
  };

  function scenarioReset() {
    scenario.phase = 0; scenario.phaseT = 0; scenario.speed = 0;
    scenario.odoKm = 12345.0; scenario.fuel = 70;
    if (ALIAS.fuel) setValue(ALIAS.fuel.sig, 70);
    if (ALIAS.odo) setValue(ALIAS.odo.sig, scenario.odoKm * 1000);
    emit('scenario', scenario);
  }

  function scenarioTick(dtMs) {
    if (!scenario.engaged) { emit('scenario', scenario); return; }
    const dtH = dtMs / 3600000;
    let speed = scenario.speed;

    if (scenario.manual) {
      speed = Number(scenario.manualSpeed) || 0;
      scenario.phase = -1;
    } else if (scenario.running) {
      scenario.phaseT += dtMs;
      const ph = PHASES[scenario.phase];
      if (scenario.phase === 0 || scenario.phase === 2 || scenario.phase === 4) {
        speed = ph.target;
        if (scenario.phaseT >= ph.hold) {
          scenario.phase = (scenario.phase + 1) % PHASES.length;
          scenario.phaseT = 0;
        }
      } else if (scenario.phase === 1 || scenario.phase === 3) {
        // accelerate 1.25 km/h per 10 ms tick of simulated time
        speed = Math.min(ph.target, speed + 1.25 * (dtMs / 10));
        if (speed >= ph.target - 0.01) { scenario.phase += 1; scenario.phaseT = 0; }
      } else {                                    // brake
        speed = Math.max(0, speed - 1.75 * (dtMs / 10));
        if (speed <= 0) { scenario.phase = 0; scenario.phaseT = 0; }
      }
    }
    scenario.speed = speed;

    if (ALIAS.speed) setValue(ALIAS.speed.sig, speed, { src: 'scenario' });
    if (ALIAS.rpm) {
      const rpm = speed <= 0 ? 800 : 800 + (2600 - 800) * (speed / 110);
      setValue(ALIAS.rpm.sig, rpm, { src: 'scenario' });
    }
    if (ALIAS.speedValid) setValue(ALIAS.speedValid.sig, 0, { src: 'scenario' });

    if (!offline['EMS']) {
      if (ALIAS.fuel) {
        scenario.fuel = Math.min(100, Math.max(0, scenario.fuel - speed * dtH * 0.02));
        setValue(ALIAS.fuel.sig, scenario.fuel, { src: 'scenario' });
      }
      if (ALIAS.odo && !offline['ICN']) {
        scenario.odoKm += speed * dtH;
        setValue(ALIAS.odo.sig, scenario.odoKm * 1000, { src: 'scenario' });
      }
    }
    emit('scenario', scenario);
  }

  function scenarioPhaseLabel() {
    if (!scenario.engaged) return 'غیرفعال';
    if (scenario.manual) return 'کنترل دستی';
    if (!scenario.running) return 'متوقف';
    return PHASES[scenario.phase].fa;
  }

  /* ======================================================================
     Transport adapters
     Every adapter implements:
        connect(), disconnect(), write(sigName, value), writeOffline(node, flag)
     and pushes `onFrame({ sig: [name, value], offline: {...}, stats: {...} })`
     ====================================================================== */

  /* ------------------------------------------------------- 1) simulator */
  function SimulatorAdapter() {
    let timer = null;
    this.name = 'sim';
    this.connect = () => {
      stats.connected = true; stats.source = 'sim'; stats.lastError = '';
      // Publish every restbus frame once per tick so echo / timeout monitoring
      // behaves exactly like the real bridge does.
      timer = setInterval(() => {
        byMsg.forEach((m) => {
          const node = m.sigs[0].node;
          if (offline[node]) return;
          stats.rx += 1;
          emit('busframe', m.key);
        });
        emit('tick', stats);
      }, 1000);
      emit('connection', stats);
    };
    this.disconnect = () => { if (timer) clearInterval(timer); timer = null; stats.connected = false; emit('connection', stats); };
    this.write = (sigName, value, src) => { stats.tx += 1; setValue(sigName, value, { src: src || 'panel' }); };
    this.writeOffline = (node, flag) => setOffline(node, flag);
  }

  /* ------------------------------------------------------- 2) HTTP poll */
  function HttpAdapter(base) {
    let polling = null;
    this.name = 'http';
    this.connect = async () => {
      const r = await fetch(base + '/api/state', { cache: 'no-store' });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const s = await r.json();
      stats.connected = true; stats.source = 'http'; stats.lastError = '';
      adoptState(s);
      stats.health = await (await fetch(base + '/api/health', { cache: 'no-store' })).json();
      emit('health', stats.health);
      polling = setInterval(poll, 250);
      emit('connection', stats);
    };
    async function poll() {
      try {
        const r = await fetch(base + '/api/state', { cache: 'no-store' });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        const s = await r.json();
        adoptState(s);
      } catch (e) {
        stats.lastError = e.message;
        stats.connected = false;
        emit('connection', stats);
        if (polling) clearInterval(polling);
        polling = null;
      }
    }
    this.disconnect = () => { if (polling) clearInterval(polling); polling = null; stats.connected = false; emit('connection', stats); };
    this.write = (sigName, value, src) => {
      stats.tx += 1;
      setValue(sigName, value, { src: src || 'panel' });
      fetch(base + '/api/signal', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ signal: sigName, value }),
      }).catch((e) => { stats.lastError = e.message; });
    };
    this.writeOffline = (node, flag) => {
      setOffline(node, flag);
      fetch(base + '/api/offline', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ node, offline: !!flag }),
      }).catch((e) => { stats.lastError = e.message; });
    };
  }

  /* ----------------------------------------------------------- 3) WS */
  function WsAdapter(url) {
    let ws = null, pingTimer = null, latencySent = 0;
    this.name = 'ws';
    this.connect = () => new Promise((resolve, reject) => {
      let settled = false;
      try { ws = new WebSocket(url); } catch (e) { reject(e); return; }
      const to = setTimeout(() => { if (!settled) { reject(new Error('timeout')); try { ws.close(); } catch (e) {} } }, 4000);
      ws.onopen = () => {
        clearTimeout(to); settled = true;
        stats.connected = true; stats.source = 'ws'; stats.lastError = '';
        emit('connection', stats);
        send({ cmd: 'hello', client: 'nbcm-tester', ver: 1, chanHs: settings.chanHs, chanLs: settings.chanLs });
        // ask the bridge why it is in a degraded state (no CANoe / no sysvars)
        fetch(settings.httpUrl + '/api/health', { cache: 'no-store' })
          .then((r) => (r.ok ? r.json() : null))
          .then((h) => { if (h) { stats.health = h; emit('health', h); } })
          .catch(() => {});
        pingTimer = setInterval(() => { latencySent = performance.now(); send({ cmd: 'ping', t: Date.now() }); }, 3000);
        resolve();
      };
      ws.onerror = () => { stats.lastError = 'websocket error'; if (!settled) { clearTimeout(to); reject(new Error('websocket error')); } };
      ws.onclose = () => {
        stats.connected = false; emit('connection', stats);
        if (pingTimer) { clearInterval(pingTimer); pingTimer = null; }
      };
      ws.onmessage = (ev) => {
        let m; try { m = JSON.parse(ev.data); } catch (e) { return; }
        if (m.pong) { stats.latency = Date.now() - m.pong; emit('tick', stats); return; }
        if (m.type === 'offline') {
          Object.keys(m.offline || {}).forEach((n) => setOffline(n, m.offline[n]));
          return;
        }
        if (m.type === 'state') { adoptState(m); return; }
        if (m.type === 'frames' && Array.isArray(m.frames)) {
          m.frames.forEach((f) => {
            if (!f) return;
            stats.rx += 1;
            setValue(f[0], f[1], { src: 'bus' });
            const sg = byName.get(f[0]);
            if (sg) emit('busframe', sg.net + ':' + sg.msg);
            emit('frame', f);
          });
          return;
        }
        if (m.type === 'meas') { emit('meas', m); return; }
      };
    });
    function send(o) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(o)); }
    this.disconnect = () => {
      if (pingTimer) { clearInterval(pingTimer); pingTimer = null; }
      if (ws) { try { ws.close(); } catch (e) {} ws = null; }
      stats.connected = false; emit('connection', stats);
    };
    this.write = (sigName, value, src) => {
      stats.tx += 1;
      setValue(sigName, value, { src: src || 'panel' });
      send({ cmd: 'set', signal: sigName, value });
    };
    this.writeOffline = (node, flag) => { setOffline(node, flag); send({ cmd: 'offline', node, flag: !!flag }); };
    this.sendCmd = (obj) => send(obj);
  }

  /* ------------------------------------------------------ state adoption */
  function adoptState(s) {
    if (!s) return;
    (s.frames || []).forEach((f) => {
      if (!f) return;
      stats.rx += 1;
      setValue(f[0], f[1], { src: 'bus' });
      const sg = byName.get(f[0]);
      if (sg) emit('busframe', sg.net + ':' + sg.msg);
      emit('frame', f);
    });
    if (s.signals) Object.keys(s.signals).forEach((k) => setValue(k, s.signals[k], { src: 'bus' }));
    if (s.offline) Object.keys(s.offline).forEach((n) => setOffline(n, s.offline[n]));
    if (typeof s.measRunning === 'boolean') emit('meas', { running: s.measRunning });
    if (typeof s.driveMode === 'number' && s.driveMode !== stats.driveMode) {
      stats.driveMode = s.driveMode; emit('drive', s.driveMode);
    }
    if (s.sysvars !== undefined) stats.sysvars = !!s.sysvars;
    if (s.msgAge) emit('msgage', s.msgAge);
    emit('tick', stats);
  }

  /* ------------------------------------------------------------- factory */
  let adapter = null;
  async function connect(mode) {
    if (adapter) { try { adapter.disconnect(); } catch (e) {} adapter = null; }
    const m = mode || settings.mode;
    if (m === 'sim' || m === 'auto') {
      adapter = new SimulatorAdapter();
      adapter.connect();
      if (m === 'auto') probeForBridge();
      return adapter;
    }
    if (m === 'ws') {
      adapter = new WsAdapter(settings.wsUrl);
      await adapter.connect();
      saveSettings({ mode: 'ws' });
      return adapter;
    }
    if (m === 'http') {
      adapter = new HttpAdapter(settings.httpUrl);
      await adapter.connect();
      saveSettings({ mode: 'http' });
      return adapter;
    }
    adapter = new SimulatorAdapter(); adapter.connect(); return adapter;
  }
  async function probeForBridge() {
    try {
      const r = await fetch(settings.httpUrl + '/api/state', { cache: 'no-store' });
      if (!r.ok) return;
      const s = await r.json();
      // bridge found -> switch transparently, keeping the simulator as fallback
      if (adapter) adapter.disconnect();
      adapter = new WsAdapter(settings.wsUrl);
      try { await adapter.connect(); saveSettings({ mode: 'ws' }); }
      catch (e) { adapter = new HttpAdapter(settings.httpUrl); await adapter.connect(); saveSettings({ mode: 'http' }); }
      void s;
    } catch (e) { /* stay on simulator */ }
  }
  function currentAdapter() { return adapter; }

  function setDriveMode(tester) {
    stats.driveMode = tester ? 1 : 0;
    const a = adapter;
    if (a && a.name === 'ws' && a.sendCmd) a.sendCmd({ cmd: 'drive', tester: !!tester });
    else if (a && a.name === 'http') {
      fetch(settings.httpUrl + '/api/drive', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ tester: !!tester }),
      }).catch(() => {});
    }
    emit('drive', stats.driveMode);
  }

  function writeSignal(sigName, value, src) {
    const s = src || 'panel';
    if (adapter) adapter.write(sigName, value, s);
    else setValue(sigName, value, { src: s });
  }
  function writeOffline(node, flag) { if (adapter) adapter.writeOffline(node, flag); else setOffline(node, flag); }

  /* --------------------------------------------------------------- export */
  global.Core = {
    DATA, settings, saveSettings, on, off, emit,
    byId, byNode, byMsg, byName, values, meta, offline, stats, ALIAS, clampNum,
    getValue, setValue, releaseOverride, releaseAll, setOffline,
    writeSignal, writeOffline, setDriveMode, connect, currentAdapter, adoptState,
    scenario, scenarioTick, scenarioReset, scenarioPhaseLabel, PHASES,
  };
})(window);

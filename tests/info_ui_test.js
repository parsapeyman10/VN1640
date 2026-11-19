/* ==========================================================================
   info_ui_test.js -- does the (i) button actually work in the tester?
   Run:  npm install jsdom --no-save && node tests/info_ui_test.js
   ========================================================================== */
const { JSDOM } = require('jsdom');
const fs = require('fs');
const html = fs.readFileSync(require('path').join(__dirname, '..', 'can_tester', 'index.html'), 'utf8');
const dom = new JSDOM(html, { runScripts: 'outside-only', url: 'http://localhost/' });
const w = dom.window;
// load the scripts in order, like the browser would
for (const f of ['assets/data.js','assets/descriptions.js','js/core.js','js/info.js','js/ui.js','js/tests.js']) {
  w.eval(fs.readFileSync(require('path').join(__dirname, '..', 'can_tester', f), 'utf8'));
}
const fails = [];
const ok = (c, msg) => { if (!c) fails.push(msg); };

w.requestAnimationFrame = (cb) => 0;   // the scenario loop is a browser thing
w.cancelAnimationFrame = () => {};
w.Info.init();
w.UI.init();

// 1) descriptions loaded for every signal
const D = w.NBCM_DESCRIPTIONS;
ok(D && Object.keys(D.signals).length === 481, 'descriptions: expected 481, got ' + (D && Object.keys(D.signals).length));
ok(Object.keys(D.nodes).length === 13, 'nodes: expected 13, got ' + Object.keys(D.nodes).length);

// 2) every signal row has a (i) button, and the table is rendered
const rows = w.document.querySelectorAll('#ctrlTable tbody tr[data-sig]');
ok(rows.length > 0, 'no control rows rendered');
const btns = w.document.querySelectorAll('#ctrlTable tbody tr[data-sig] .infobtn');
ok(btns.length === rows.length, `info buttons ${btns.length} != rows ${rows.length}`);

// 3) the hover title is populated and mentions the message
const b0 = btns[0];
ok(b0.getAttribute('title') && b0.getAttribute('title').length > 20, 'no hover text');
ok(/پیام:/.test(b0.getAttribute('title')), 'hover text has no message line');

// 4) clicking opens the popup with real content
b0.dispatchEvent(new w.Event('click', { bubbles: true }));
const box = w.document.getElementById('infoBox');
ok(box.classList.contains('show'), 'popup did not open');
const body = w.document.getElementById('infoBody');
ok(body.textContent.length > 120, 'popup content too short: ' + body.textContent.length);
ok(/این چیست و چه کاری می‌کند/.test(body.textContent), 'missing "what is it" section');
ok(/مشخصات فنی/.test(body.textContent), 'missing facts section');

// 5) Escape closes it
w.document.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Escape' }));
ok(!box.classList.contains('show'), 'Escape did not close');

// 6) node card buttons exist too
w.UI.switchView('nodes');
const nodeBtns = w.document.querySelectorAll('#nodeGrid .infobtn');
ok(nodeBtns.length === 13, `node info buttons ${nodeBtns.length} != 13`);

console.log(fails.length ? 'FAIL\n  ' + fails.join('\n  ') : 'PASS  info buttons + popup work on all ' + rows.length + ' rows and 13 nodes');
// UI.init starts polling and a scenario loop; leave explicitly or the test hangs
w.close();
process.exit(fails.length ? 1 : 0);

/* ==========================================================================
   why_ui_test.js -- does the tester show *why* a value changed?
   Run:  node tests/why_ui_test.js
   ========================================================================== */
const { JSDOM }=require('jsdom'); const fs=require('fs'),path=require('path');
const root=require('path').join(__dirname,'..','can_tester');
const dom=new JSDOM(fs.readFileSync(path.join(root,'index.html'),'utf8'),{runScripts:'outside-only',url:'http://localhost/'});
const w=dom.window; w.requestAnimationFrame=()=>0;
for(const f of ['assets/data.js','assets/descriptions.js','js/react.js','js/core.js','js/info.js','js/ui.js'])
  w.eval(fs.readFileSync(path.join(root,f),'utf8'));
w.Info.init(); w.UI.init();
const R=[]; const ck=(n,v,e)=>R.push([n,v,e||'']);
// no reaction yet -> friendly empty state
w.UI.switchView('control');
let t=w.document.getElementById('reactList').textContent;
ck('empty state explains what to do', t.includes('قطع کنید'), t.slice(0,60));
// now cut a node and feed reasons through the same path the sim uses
w.Core.setOffline('ABS', true);
w.Core.emit('reasons', [
  {rule:'substitute',node:'ABS',signal:'Hs_Abs_Wheel_Speed_Fl',text:'سرعت صفر می‌شود'},
  {rule:'cascade',node:'ICU',signal:'Hs_Icu_Com_Loss',text:'ICU به ABS نیاز دارد'},
]);
t=w.document.getElementById('reactList').textContent;
ck('rules are named in Persian', t.includes('جانشین') && t.includes('زنجیره'), t.slice(0,80));
ck('signal and reason shown', t.includes('Hs_Abs_Wheel_Speed_Fl') && t.includes('ICU به ABS'), '');
ck('count badge', w.document.getElementById('reactCount').textContent==='(2)', w.document.getElementById('reactCount').textContent);
ck('rows are a table', w.document.querySelectorAll('#reactList .reacttbl tr').length===3, '');
R.forEach(([n,v,e])=>console.log((v?'PASS ':'FAIL ')+n+(e&&!v?' ['+e+']':'')));
w.close(); process.exit(R.every(r=>r[1])?0:1);

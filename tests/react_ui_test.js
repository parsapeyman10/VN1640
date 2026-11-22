/* ==========================================================================
   react_ui_test.js -- does the browser react like the bridge does?
   The reference rules are in tools/behaviour.py (tested by
   tests/test_behaviour.py); this checks the browser twin in js/react.js.
   Run:  node tests/react_ui_test.js
   ========================================================================== */
const { JSDOM }=require('jsdom'); const fs=require('fs'), path=require('path');
const root=require('path').join(__dirname,'..','can_tester');
const dom=new JSDOM(fs.readFileSync(path.join(root,'index.html'),'utf8'),{runScripts:'outside-only',url:'http://localhost/'});
const w=dom.window; w.requestAnimationFrame=()=>0;
for(const f of ['assets/data.js','js/react.js','js/core.js'])
  w.eval(fs.readFileSync(path.join(root,f),'utf8'));
const R=[];
const ck=(n,v,e)=>R.push([n,v,e||'']);
const m=w.React.init(w.NBCM_DATA);
ck('model built', !!m, '');
ck('supervision frames', m.stats.sup === 9, 'got '+m.stats.sup);
ck('substitutes', m.stats.substitutes > 20, 'got '+m.stats.substitutes);
const now=Date.now();
const seen={};
w.NBCM_DATA.nodes.forEach(n=>n.msgs.forEach(x=>{seen[n.net+':'+x.msg]=now;}));
const alive=m.compute({values:{},offline:{},lastSeen:seen,now});
ck('nothing absent when all frames seen', !Object.values(alive.absent).some(Boolean), '');
const cut=m.compute({values:{},offline:{ABS:true},lastSeen:seen,now});
ck('ABS absent when switched off', cut.absent.ABS===true,'');
ck('Com_Loss set', cut.values['Hs_Abs_Com_Loss']===1,'got '+cut.values['Hs_Abs_Com_Loss']);
ck('speed substituted', cut.values['Hs_Abs_Wheel_Speed_Fl']===0,'');
ck('ICU cascades', cut.values['Hs_Icu_Com_Loss']===1,'');
ck('reasons explain why', cut.reasons.length>=5 && cut.reasons.every(r=>r.text), '');
const back=m.compute({values:{'Hs_Abs_VehicleSpeed_Invalid':1},offline:{},lastSeen:seen,now});
ck('recovery clears the flag', back.values['Hs_Abs_VehicleSpeed_Invalid']===0,'');
const stale={}; Object.keys(seen).forEach(k=>{stale[k]=now-900;});
const to=m.compute({values:{},offline:{},lastSeen:stale,now});
ck('timeout works without the switch', Object.values(to.absent).filter(Boolean).length>10,'');
R.forEach(([n,v,e])=>console.log((v?'PASS ':'FAIL ')+n+(e&&!v?' ['+e+']':'')));
w.close(); process.exit(R.every(r=>r[1])?0:1);

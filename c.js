const { JSDOM }=require('jsdom'); const fs=require('fs'),path=require('path');
const root='/home/user/VN1640/can_tester';
const dom=new JSDOM(fs.readFileSync(path.join(root,'index.html'),'utf8'),{runScripts:'outside-only',url:'http://localhost/'});
const w=dom.window; w.requestAnimationFrame=()=>0;
for(const f of ['assets/data.js','assets/descriptions.js','js/react.js','js/core.js','js/info.js','js/ui.js'])
  w.eval(fs.readFileSync(path.join(root,f),'utf8'));
w.Info.init(); w.UI.init();
w.UI.switchView('control');
const host=w.document.getElementById('reactList');
console.log('host exists:', !!host);
console.log('html:', JSON.stringify((host.innerHTML||'').slice(0,160)));

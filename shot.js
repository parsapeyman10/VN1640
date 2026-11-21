const { JSDOM } = require('jsdom');
const fs = require('fs'); const path = require('path');
const root = '/home/user/VN1640/can_tester';
const dom = new JSDOM(fs.readFileSync(path.join(root,'index.html'),'utf8'), {runScripts:'outside-only', url:'http://localhost/'});
const w = dom.window;
w.requestAnimationFrame = () => 0; w.cancelAnimationFrame = () => {};
for (const f of ['assets/data.js','assets/descriptions.js','js/core.js','js/info.js','js/ui.js','js/tests.js'])
  w.eval(fs.readFileSync(path.join(root,f),'utf8'));
w.Info.init(); w.UI.init();
// open the popup for a bool signal that has notes
const rec = w.Info.record('EMS:HS_ID_EMS1:Hs_Ems_EngineActualTorque','Hs_Ems_EngineActualTorque');
w.Info.open(rec);
console.log('TITLE:', rec.title);
console.log('---');
console.log(w.document.getElementById('infoBody').textContent.replace(/\n+/g,'\n').trim());

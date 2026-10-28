const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const {mkdtempSync, mkdirSync, writeFileSync, rmSync} = require('node:fs');
const {tmpdir} = require('node:os');
const {join} = require('node:path');

const config = JSON.parse(process.env.BC_BROWSER_CONFIG);
const profile = mkdtempSync(join(tmpdir(), 'boundary-browser-'));
const report = [];
const errors = [];
let browser;
let socket;

async function main() {
  const assets = new Map();
  const urls = [
    'https://cdn.jsdelivr.net/npm/three@0.167.1/build/three.module.js',
    'https://cdn.jsdelivr.net/npm/three@0.167.1/examples/jsm/controls/OrbitControls.js',
  ];
  for (const url of urls) {
    const response = await fetch(url, {signal: AbortSignal.timeout(30000)});
    assert.ok(response.ok, `Unable to load the application's Three.js dependency: ${url}`);
    assets.set(url, await response.text());
  }
  browser = spawn(process.env.CHROMIUM_BIN || '/usr/bin/chromium', [
    '--headless', '--no-sandbox', '--disable-dev-shm-usage', '--use-gl=angle',
    '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--remote-debugging-port=0',
    `--user-data-dir=${profile}`, 'about:blank',
  ], {stdio:['ignore','ignore','pipe']});
  const address = await new Promise((resolve, reject) => {
    let output = '';
    browser.once('error', reject);
    browser.once('exit', code => reject(new Error(`Chromium exited: ${code}`)));
    browser.stderr.on('data', chunk => {
      output += chunk;
      const match = output.match(/DevTools listening on (ws:\/\/\S+)/);
      if (match) resolve(match[1]);
    });
  });
  socket = new WebSocket(address);
  await once(socket, 'open');
  let nextId = 0;
  const pending = new Map();
  const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
    const id = ++nextId;
    pending.set(id, {resolve, reject});
    socket.send(JSON.stringify({id, method, params, sessionId}));
  });
  socket.addEventListener('message', event => {
    const message = JSON.parse(event.data);
    if (message.method === 'Runtime.exceptionThrown') errors.push(message.params.exceptionDetails);
    if (message.method === 'Fetch.requestPaused') {
      fulfill(message).catch(error => errors.push(String(error)));
    }
    const request = pending.get(message.id);
    if (!request) return;
    pending.delete(message.id);
    if (message.error) request.reject(new Error(message.error.message));
    else request.resolve(message.result);
  });
  async function fulfill(message) {
    const {requestId, request} = message.params;
    let body = assets.get(request.url);
    if (body === undefined) {
      const response = await send('Fetch.getResponseBody', {requestId}, message.sessionId);
      body = response.base64Encoded ? Buffer.from(response.body, 'base64').toString() : response.body;
      const marker = '  state.resetCameraView();\n\n  const resetButton';
      assert.ok(body.includes(marker), 'Viewer test instrumentation point is missing');
      body = body.replace(marker, '  window.__bcTest = {state, items, tensorGroup};\n' + marker);
      body += '\nwindow.__bcThree = THREE;\n';
    }
    await send('Fetch.fulfillRequest', {requestId, responseCode:200,
      responseHeaders:[{name:'Content-Type',value:'text/javascript'},{name:'Access-Control-Allow-Origin',value:'*'}],
      body:Buffer.from(body).toString('base64')}, message.sessionId);
  }
  const {targetId} = await send('Target.createTarget', {url:'about:blank'});
  const {sessionId} = await send('Target.attachToTarget', {targetId,flatten:true});
  const command = (method, params = {}) => send(method,params,sessionId);
  await command('Runtime.enable');
  await command('Network.enable');
  await command('Network.setCookie', {name:config.cookieName,value:config.session,url:config.baseUrl});
  await command('Fetch.enable', {patterns:[
    ...urls.map(urlPattern => ({urlPattern,requestStage:'Request'})),
    {urlPattern:'*mechanical-bc-viewer.js*',requestStage:'Response'},
  ]});
  const evaluate = async expression => {
    const result = await command('Runtime.evaluate', {expression,returnByValue:true,awaitPromise:true});
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
    return result.result.value;
  };
  async function waitFor(expression, message) {
    const end = Date.now() + 20000;
    while (Date.now() < end) {
      try {
        if (await evaluate(expression)) return;
      } catch (error) {
        if (!/context.*destroyed|Cannot find.*context/i.test(error.message)) throw error;
      }
      await new Promise(resolve => setTimeout(resolve,40));
    }
    throw new Error(message);
  }
  async function open(key, width = 1440) {
    await command('Emulation.setDeviceMetricsOverride',{width,height:1080,deviceScaleFactor:1,mobile:false});
    await command('Page.navigate',{url:config.baseUrl+config.pages[key]});
    await waitFor(`location.href===${JSON.stringify(config.baseUrl+config.pages[key])} && !!window.__bcTest && !!document.querySelector('[data-bc-tensor-panel]') && document.readyState==='complete'`, 'Boundary page did not render');
    await evaluate(`Promise.all(document.getAnimations().filter(a=>a.effect.getComputedTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>{})))`);
    await evaluate('document.fonts.ready');
    await evaluate(`document.querySelector('.bc-panel').scrollIntoView({block:'start',behavior:'instant'});window.scrollBy({top:-100,behavior:'instant'});new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))`);
    assert.equal(await evaluate('__bcTest.state.renderer.getContext().isContextLost()'),false);
  }
  async function screenshot(name) {
    if (!process.env.BC_BROWSER_REPORT_DIR) return;
    mkdirSync(process.env.BC_BROWSER_REPORT_DIR,{recursive:true});
    const viewport = await evaluate('({width:innerWidth,height:innerHeight})');
    const height = await evaluate('Math.ceil(document.querySelector(".bc-panel").getBoundingClientRect().height+200)');
    await command('Emulation.setDeviceMetricsOverride',{width:viewport.width,height,deviceScaleFactor:1,mobile:false});
    await evaluate(`new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))`);
    await waitFor(`document.getAnimations().every(animation=>animation.playState!=='running'||animation.effect.getComputedTiming().iterations===Infinity)`, 'Screenshot transitions did not settle');
    await evaluate(`document.querySelector('.bc-panel').scrollIntoView({block:'start',behavior:'instant'});window.scrollBy({top:-100,behavior:'instant'})`);
    const result = await command('Page.captureScreenshot',{format:'png'});
    writeFileSync(join(process.env.BC_BROWSER_REPORT_DIR,name+'.png'),Buffer.from(result.data,'base64'));
    await command('Emulation.setDeviceMetricsOverride',{...viewport,deviceScaleFactor:1,mobile:false});
    await evaluate(`new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))`);
  }
  const tensorComponents = () => evaluate('[...new Map(__bcTest.state.tensorMeshes.map(mesh=>[mesh.userData.tooltip,mesh.userData.component])).values()]');
  const tensorCount = async () => (await tensorComponents()).length;
  const visibleTooltip = `Array.from(document.querySelector('#mechanical-bc-cube').children).find(el=>el.style.pointerEvents==='none'&&el.style.opacity==='1')`;
  async function checkTensorGeometry() {
    const arrows = await evaluate(`(() => {
      __bcTest.state.root.updateMatrixWorld(true);
      const groups = new Map();
      for (const mesh of __bcTest.state.tensorMeshes) {
        if (!groups.has(mesh.userData.tooltip)) groups.set(mesh.userData.tooltip, {
          component: mesh.userData.component, value: mesh.userData.value,
          color: mesh.material.color.getHexString(), box: new __bcThree.Box3(),
          direction: new __bcThree.Vector3(0, 1, 0).transformDirection(mesh.matrixWorld),
        });
        groups.get(mesh.userData.tooltip).box.expandByObject(mesh);
      }
      return [...groups.values()].map(arrow => {
        const center = arrow.box.getCenter(new __bcThree.Vector3());
        const size = arrow.box.getSize(new __bcThree.Vector3());
        const halfLength = (Math.abs(arrow.direction.x)*size.x + Math.abs(arrow.direction.y)*size.y + Math.abs(arrow.direction.z)*size.z)/2;
        return {component: arrow.component, value: arrow.value, color: arrow.color,
          start: center.clone().addScaledVector(arrow.direction, -halfLength).toArray(),
          tip: center.clone().addScaledVector(arrow.direction, halfLength).toArray(),
          min: arrow.box.min.toArray(), max: arrow.box.max.toArray()};
      });
    })()`);
    for (const arrow of arrows) {
      assert.ok(Math.abs(Math.hypot(...arrow.tip.map((value, axis)=>value-arrow.start[axis]))-0.44)<1e-6,
        'Tensor arrows keep a fixed length independent of the component value');
      const direction = 'xyz'.indexOf(arrow.component[0]);
      const normal = 'xyz'.indexOf(arrow.component[1]);
      const faceSign = Math.sign(arrow.start[normal]);
      assert.ok((arrow.tip[direction] - arrow.start[direction]) * faceSign * Math.sign(arrow.value) > 0,
        `${arrow.component}: arrow follows the supplied component sign on its opposing face`);
      if (direction === normal) {
        const nearest = Math.min(Math.abs(arrow.start[normal]), Math.abs(arrow.tip[normal]));
        assert.ok(nearest >= 0.5 && nearest <= 0.58, 'Pull tails and push tips must meet the corresponding face');
        assert.equal(arrow.color, arrow.value > 0 ? '2563eb' : 'c2410c');
      } else {
        assert.ok(Math.abs(arrow.start[normal] - arrow.tip[normal]) < 1e-8, 'Shear must stay parallel to the face');
        assert.ok(Math.abs(arrow.start[normal]) >= 0.5 && Math.abs(arrow.start[normal]) <= 0.61);
        const nearestSurface = faceSign > 0 ? arrow.min[normal] : -arrow.max[normal];
        assert.ok(nearestSurface >= 0.5 - 1e-8, 'The complete shear arrow must stay outside the cube face');
        assert.equal(arrow.color, '0f766e');
      }
    }
  }
  async function checkLocalArrowOrigins(key) {
    const geometry = await evaluate(`(() => {
      const shafts = [], heads = [], markers = [];
      __bcTest.state.root.updateMatrixWorld(true);
      __bcTest.state.root.traverse(mesh => {
        if (mesh.geometry?.type === 'SphereGeometry' || mesh.geometry?.type === 'OctahedronGeometry') {
          markers.push(mesh.getWorldPosition(new __bcThree.Vector3()).toArray());
        }
        if (mesh.material?.color?.getHexString() !== 'dc2626') return;
        if (mesh.geometry?.type === 'ConeGeometry') heads.push(mesh.userData.tooltip);
        if (mesh.geometry?.type !== 'CylinderGeometry') return;
        const halfHeight = mesh.geometry.parameters.height / 2;
        const start = new __bcThree.Vector3(0, -halfHeight, 0).applyMatrix4(mesh.matrixWorld);
        const end = new __bcThree.Vector3(0, halfHeight, 0).applyMatrix4(mesh.matrixWorld);
        shafts.push({start: start.toArray(), direction: end.sub(start).normalize().toArray()});
      });
      return {shafts, heads, markers};
    })()`);
    const center = key === 'edge' ? [0, 0.5, -0.5] : [0, 0, 0.5];
    const sign = key === 'edge' ? -1 : 1;
    assert.equal(geometry.shafts.length, 3, `${key}: one shaft per loaded direction`);
    assert.equal(geometry.heads.length, 3, `${key}: one head per loaded direction`);
    const directions = geometry.shafts.map(shaft => {
      assert.ok(shaft.start.every((value, axis) => Math.abs(value - center[axis]) < 1e-8),
        `${key}: all arrow shafts must start at the region center; got ${shaft.start}`);
      return shaft.direction.map(value => Math.abs(value) < 1e-8 ? 0 : Math.round(value));
    });
    assert.deepEqual(directions, [[sign, 0, 0], [0, sign, 0], [0, 0, sign]], `${key}: retain the supplied load signs`);
    assert.equal(geometry.markers.some(point => point.every((value, axis) => Math.abs(value - center[axis]) < 1e-8)),
      false, `${key}: do not draw a center marker`);
  }
  await open('tensor');
  assert.equal(await tensorCount(),8,'Copper needs four independent components, two faces each');
  assert.equal(await evaluate('document.querySelector("[data-tensor-load]").closest("label").hidden'),true);
  assert.equal(await evaluate('document.querySelector("[data-tensor-status]").checkVisibility()'),false);
  assert.match(await evaluate('document.querySelector("[data-tensor-heading]").textContent'),/Stress \(MPa\)/);
  await checkTensorGeometry();
  for (const width of [1280, 1440, 1920]) {
    await command('Emulation.setDeviceMetricsOverride', {width, height: 1080, deviceScaleFactor: 1, mobile: false});
    await evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))');
    assert.equal(await evaluate(`(() => {const cube=document.querySelector('.bc-cube-wrap').getBoundingClientRect();
      const matrix=document.querySelector('[data-tensor-matrix]').getBoundingClientRect();
      return matrix.left>cube.right && matrix.top<cube.bottom && matrix.right<=innerWidth;})()`), true,
      `Tensor matrix must sit beside the cube at ${width}`);
    await screenshot('tensor-'+width);
    const matrixValues = await evaluate('Array.from(document.querySelectorAll("[data-component] strong")).map(value=>value.textContent)');
    await evaluate('document.querySelector("[data-tensor-options]").open=true');
    for (const [filter, components] of [['pull', ['xx', 'xx', 'yy', 'yy']], ['push', []], ['slide', ['xy', 'xy', 'yx', 'yx']]]) {
      await evaluate(`document.querySelector('[data-tensor-filter=${filter}]').click();document.activeElement.blur()`);
      assert.deepEqual(await tensorComponents(), components);
      assert.deepEqual(await evaluate('Array.from(document.querySelectorAll("[data-component] strong")).map(value=>value.textContent)'), matrixValues);
      assert.match(await evaluate('document.querySelector("[data-tensor-description]").textContent'), /^Cube arrows:/);
      assert.equal(await evaluate('document.querySelector("[data-tensor-filter-note]").checkVisibility()'), true);
      assert.equal(await evaluate('document.querySelector("[data-tensor-note]").checkVisibility()'), false);
      assert.doesNotMatch(await evaluate('document.querySelector("[data-tensor-options]").textContent'), /step:|Stress component schematic/);
      assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'),false);
      if (width === 1280 || filter === 'slide') await screenshot('tensor-'+filter+'-'+width);
    }
    await evaluate('document.querySelector("[data-tensor-filter=all]").click();document.activeElement.blur();document.querySelector("[data-tensor-options]").open=false');
  }
  await screenshot('tensor-final');
  const matrixTop = await evaluate('document.querySelector("[data-tensor-matrix]").getBoundingClientRect().top');
  await evaluate('document.querySelector("[data-component=xy]").click()');
  assert.equal(await evaluate('document.querySelector("[data-tensor-matrix]").getBoundingClientRect().top'), matrixTop,
    'Selecting a component must not move the matrix buttons');
  assert.equal(await tensorCount(),2);
  assert.equal(await evaluate('__bcTest.tensorGroup.children.filter(m=>m.userData.tensorFace&&m.material.opacity>0.1).length'),2);
  await evaluate('document.activeElement.blur()');
  assert.equal(await evaluate('__bcTest.tensorGroup.children.filter(m=>m.userData.tensorFace&&m.material.opacity>0.1).length'),2,
    'Selected faces stay emphasized when focus moves away');
  await screenshot('tensor-shear-selected');
  await evaluate('document.querySelector("[data-component=xy]").click();document.activeElement.blur()');
  assert.equal(await tensorCount(),8);
  await evaluate('document.querySelector("[data-component=xx]").click();document.activeElement.blur()');
  assert.match(await evaluate('document.querySelector("[data-tensor-description]").textContent'), /Pull apart \(tension\)/);
  await screenshot('tensor-pull-selected');
  const tensorHover = await evaluate(`(() => {
    const mesh=__bcTest.state.tensorMeshes.find(m=>m.userData.component==='xx'&&m.position.x>0);
    const p=new __bcThree.Box3().setFromObject(mesh).getCenter(new __bcThree.Vector3()).project(__bcTest.state.camera);
    const r=document.querySelector('#mechanical-bc-cube').getBoundingClientRect();
    return {x:r.x+(p.x+1)*r.width/2,y:r.y+(1-p.y)*r.height/2};})()`);
  await command('Input.dispatchMouseEvent', {type:'mouseMoved',...tensorHover});
  assert.match(await evaluate(`${visibleTooltip}?.textContent||''`), /Stress component xx: 15\.00 MPa[\s\S]*Pull · Tension/);
  assert.equal(await evaluate('document.querySelector("[data-component=xx]").classList.contains("is-hovered")'),true);
  await command('Input.dispatchMouseEvent', {type:'mouseMoved',x:0,y:0});
  assert.equal(await evaluate(`!!(${visibleTooltip})`),false);
  assert.equal(await evaluate('document.querySelector("[data-component=xx]").classList.contains("is-hovered")'),false);
  await evaluate('document.querySelector("[data-component=xx]").click();document.activeElement.blur()');
  report.push('copper: Pull/Push/Slide filter actual arrows while preserving the full matrix at 1280/1440/1920; no repeated step or stress paragraph; selection and hover stay linked');

  await open('records');
  assert.equal(await tensorCount(),18);
  await checkTensorGeometry();
  await evaluate('document.querySelector("[data-tensor-filter=push]").click()');
  assert.deepEqual(await tensorComponents(), ['xx', 'xx', 'zz', 'zz']);
  await evaluate('document.querySelector("[data-tensor-filter=all]").click();document.activeElement.blur()');
  assert.equal(await evaluate(`(()=>{const groups={};for(const mesh of __bcTest.state.tensorMeshes){
    const face=mesh.userData.tooltip.split('\\n')[1].split(' face')[0];const key=face+mesh.userData.component;
    (groups[key]??={face,box:new __bcThree.Box3()}).box.expandByObject(mesh)}
    const boxes=Object.values(groups);return boxes.some((a,i)=>boxes.slice(i+1).some(b=>a.face===b.face&&a.box.intersectsBox(b.box)))})()`),false,
    'Normal and both shear arrows must not physically cross on one face');
  await evaluate('document.querySelector("[data-component=xx]").click();document.activeElement.blur()');
  assert.match(await evaluate('document.querySelector("[data-tensor-description]").textContent'), /Push together \(compression\)/);
  await screenshot('tensor-push-selected');
  await evaluate('document.querySelector("[data-component=xx]").click();document.activeElement.blur()');
  await evaluate('document.querySelector("[data-component=yx]").click()');
  assert.equal(await tensorCount(),2);
  await evaluate('document.querySelector("[data-tensor-load]").value="1";document.querySelector("[data-tensor-load]").dispatchEvent(new Event("change"))');
  assert.equal(await tensorCount(),0);
  assert.match(await evaluate('document.querySelector("[data-tensor-status]").textContent'),/Not supplied/);
  assert.match(await evaluate('document.querySelector("[data-tensor-load]").selectedOptions[0].textContent'),/step 3$/);
  await evaluate('document.querySelector("[data-tensor-load]").value="2";document.querySelector("[data-tensor-load]").dispatchEvent(new Event("change"))');
  assert.equal(await tensorCount(),2);
  assert.match(await evaluate('document.querySelector("[data-tensor-load]").selectedOptions[0].textContent'),/123456789012345$/);
  await evaluate('document.querySelector("[data-tensor-load]").value="3";document.querySelector("[data-tensor-load]").dispatchEvent(new Event("change"))');
  assert.doesNotMatch(await evaluate('document.querySelector("[data-tensor-load]").selectedOptions[0].textContent'),/step/);
  await evaluate('document.querySelector("[data-component=yx]").click();document.activeElement.blur()');
  await screenshot('tensor-all-components');
  report.push('18 arrows: negative normal and independent shear separated; exact supplied record order and absent steps');

  for (const key of ['point','edge','face','whole','zero','empty','mixed']) {
    await open(key);
    const counts = await evaluate(`({whole:__bcTest.state.wholeMeshes.filter(m=>m.geometry.type==='ConeGeometry').length,
      local:(()=>{let count=0;__bcTest.state.root.traverse(m=>{if(m.geometry?.type==='ConeGeometry'&&m.material.color.getHexString()==='dc2626')count++});return count})()})`);
    if(key==='whole') assert.equal(counts.whole,2);
    if(key==='zero') assert.equal(counts.whole,0);
    if(key==='empty') assert.deepEqual(counts,{whole:0,local:0});
    if(key==='point') assert.equal(counts.local,1);
    if(key==='edge'||key==='face') {
      assert.equal(counts.local,3);
      await checkLocalArrowOrigins(key);
    }
    if(key==='mixed') assert.equal(counts.local,7);
    await screenshot(key+'-final');
    report.push(`${key}: local ${counts.local}, whole scalar ${counts.whole}`);
  }
  await open('whole');
  assert.match(await evaluate('document.querySelector(".bc-whole-heading").textContent'),/Force \(N\)/);
  assert.match(await evaluate('document.querySelector("[data-bc-scalar-legend]").textContent'), /Force \(N\)/);
  assert.match(await evaluate('document.querySelector(".bc-diagram-caption").textContent'), /sign shows direction/);
  const hover = await evaluate(`(()=>{const m=__bcTest.state.wholeMeshes.find(m=>m.geometry.type==='ConeGeometry');
    const p=m.getWorldPosition(new __bcThree.Vector3()).project(__bcTest.state.camera);
    const r=document.querySelector('#mechanical-bc-cube').getBoundingClientRect();return {x:r.x+(p.x+1)*r.width/2,y:r.y+(1-p.y)*r.height/2}})()`);
  await command('Input.dispatchMouseEvent',{type:'mouseMoved',...hover});
  assert.match(await evaluate(`${visibleTooltip}?.textContent||''`),/Force \(N\)[\s\S]*12\.50/);
  assert.equal(await evaluate(`(()=>{const t=${visibleTooltip};const r=t.getBoundingClientRect();const c=t.parentElement.getBoundingClientRect();return r.left>=c.left&&r.right<=c.right&&r.top>=c.top&&r.bottom<=c.bottom})()`),true);
  await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape'});
  assert.equal(await evaluate(`!!(${visibleTooltip})`),false);
  await command('Input.dispatchMouseEvent',{type:'mouseMoved',x:hover.x+1,y:hover.y});
  assert.ok(await evaluate(`!!(${visibleTooltip})`));
  await command('Input.dispatchMouseEvent',{type:'mouseMoved',x:0,y:0});
  assert.equal(await evaluate(`!!(${visibleTooltip})`),false);
  const initial = await evaluate('__bcTest.state.camera.position.toArray()');
  await command('Input.dispatchMouseEvent',{type:'mousePressed',x:hover.x-50,y:hover.y,button:'left',clickCount:1});
  await command('Input.dispatchMouseEvent',{type:'mouseMoved',x:hover.x+50,y:hover.y+40,button:'left',buttons:1});
  await command('Input.dispatchMouseEvent',{type:'mouseReleased',x:hover.x+50,y:hover.y+40,button:'left',clickCount:1});
  assert.notDeepEqual(await evaluate('__bcTest.state.camera.position.toArray()'),initial);
  await evaluate('document.querySelector("[data-bc-reset]").click()');
  assert.deepEqual(await evaluate('__bcTest.state.camera.position.toArray()'),initial);
  report.push('real pointer hover includes force and value; rotate and reset restore camera');

  for (const width of [1280,1440,1920]) {
    for (const key of ['edge', 'face']) {
      await open(key, width);
      await checkLocalArrowOrigins(key);
      assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'), false);
      if (width !== 1440) await screenshot(key+'-'+width);
    }
    await open('mixed',width);
    await evaluate('document.querySelectorAll(".bc-axis-list .bc-load-detail").forEach(el=>el.open=true)');
    assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'),false,`Page overflows at ${width}`);
    assert.equal(await evaluate(`(()=>{const r=document.querySelector('.bc-panel').getBoundingClientRect();return r.left>=0&&r.right<=innerWidth})()`),true,`Boundary panel is clipped at ${width}`);
    assert.equal(await evaluate(`Array.from(document.querySelectorAll('.bc-axis-list')).some(el=>{const nodes=Array.from(el.children);return nodes.slice(1).some(node=>Math.abs(node.getBoundingClientRect().top-nodes[0].getBoundingClientRect().top)>1)})`),false);
    await evaluate('document.querySelector("[data-tensor-condition]").value="1";document.querySelector("[data-tensor-condition]").dispatchEvent(new Event("change"))');
    assert.match(await evaluate('document.querySelector("[data-tensor-heading]").textContent'),/Strain \(-\)/);
    await evaluate('document.querySelector("[data-tensor-options]").open=true;document.querySelector("[data-tensor-shape]").click()');
    assert.equal(await tensorCount(),0);
    assert.match(await evaluate('document.querySelector("[data-tensor-kind]").textContent'),/Normalized small-strain/);
    await evaluate('document.querySelector("[data-component=xx]").click()');
    assert.equal(await tensorCount(),2);
    await evaluate('document.querySelector(".bc-whole-select").value="1";document.querySelector(".bc-whole-select").dispatchEvent(new Event("change"))');
    assert.match(await evaluate('document.querySelector("[data-bc-scalar-legend]").textContent'), /Displacement \(mm\)/);
    assert.match(await evaluate('document.querySelector(".bc-whole-heading").textContent'),/Displacement \(mm\)/);
    assert.equal(await evaluate(`['.bc-panel','#mechanical-bc-cube','[data-tensor-matrix]'].every(selector=>{const r=document.querySelector(selector).getBoundingClientRect();return r.left>=0&&r.right<=innerWidth})`),true,`Interaction clips the diagram at ${width}`);
    await screenshot('mixed-'+width);
    report.push(`${width}px: long metadata, independent panels, stress/strain and force/displacement selection`);
  }
  await command('Emulation.setScriptExecutionDisabled',{value:true});
  await command('Page.navigate',{url:config.baseUrl+config.pages.tensor});
  await waitFor(`location.href===${JSON.stringify(config.baseUrl+config.pages.tensor)}&&document.readyState==='complete'`, 'No-JavaScript page did not load');
  assert.equal(await evaluate('document.querySelector("[data-bc-tensor-panel]").checkVisibility()'),false);
  assert.match(await evaluate('document.querySelector(".bc-table-wrap").textContent'),/15\.00[\s\S]*step[\s\S]*1/);
  const details = await evaluate(`(()=>{const s=document.querySelector('.bc-tensor-loads summary');s.scrollIntoView({block:'center',behavior:'instant'});const r=s.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`);
  await command('Input.dispatchMouseEvent',{type:'mousePressed',...details,button:'left',clickCount:1});
  await command('Input.dispatchMouseEvent',{type:'mouseReleased',...details,button:'left',clickCount:1});
  assert.equal(await evaluate('document.querySelector(".bc-tensor-loads details").open'),true);
  assert.equal(await evaluate('document.querySelector(".bc-tensor-loads .bc-load-list").checkVisibility()'),true);
  report.push('without JavaScript: supplied tensor values and step remain available in native expandable details');
  assert.deepEqual(errors,[],'Browser errors');
  console.log(JSON.stringify({checks:report,errors},null,2));
}

main().catch(error=>{console.error(error);process.exitCode=1}).finally(async()=>{
  socket?.close();
  if(browser&&browser.exitCode===null){const done=once(browser,'exit');browser.kill('SIGTERM');await done}
  rmSync(profile,{recursive:true,force:true});
});

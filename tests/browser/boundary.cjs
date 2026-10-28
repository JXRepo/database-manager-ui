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
  await command('Emulation.setEmulatedMedia', {features:[{name:'prefers-reduced-motion',value:'reduce'}]});
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
  const tensorComponents = () => evaluate('__bcTest.state.tensorMeshes.flatMap(mesh=>mesh.userData.entries.map(entry=>entry.component)).sort()');
  const tensorCount = async () => (await tensorComponents()).length;
  const concept = '__bcTest.tensorGroup.children.find(object=>object.userData.tensorConcept)';
  const reference = '__bcTest.tensorGroup.children.find(object=>object.userData.tensorReference)';
  async function checkConcept(component, signedValue) {
    const data = await evaluate(`({component:(${concept})?.userData.tensorConcept.component,
      matrix:(${concept})?.matrix.toArray(), reference:(${reference})?.matrix.toArray(),
      referenceMaterial:(${reference})?.material.type})`);
    assert.equal(data.component,component);
    const identity=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
    const expected=[...identity];
    const direction='xyz'.indexOf(component[0]),normal='xyz'.indexOf(component[1]);
    expected[normal*4+direction]=direction===normal?(signedValue>0?1.55:0.58):Math.sign(signedValue)*0.7;
    data.matrix.forEach((value,index)=>assert.ok(Math.abs(value-expected[index])<1e-8));
    assert.deepEqual(data.reference,identity,'The dashed original cube stays fixed');
    assert.equal(data.referenceMaterial,'LineDashedMaterial');
    assert.equal(await evaluate('document.querySelector(".bc-cube-wrap").contains(document.querySelector("[data-bc-motion]"))'),true);
    assert.equal(await evaluate('document.querySelector("[data-bc-tensor-panel]").querySelectorAll("svg, canvas, [data-tensor-example-host]").length'),0,
      'The action is drawn on the left main cube, with no right-side example graphics');
  }
  const visibleTooltip = `Array.from(document.querySelector('#mechanical-bc-cube').children).find(el=>el.style.pointerEvents==='none'&&el.style.opacity==='1')`;
  async function checkTensorGeometry() {
    const faces = await evaluate(`__bcTest.state.tensorMeshes.map(mesh=>({
      type:mesh.geometry.type, position:mesh.position.toArray(), normal:mesh.userData.normal,
      faceSign:mesh.userData.faceSign, entries:mesh.userData.entries, color:mesh.material.color.getHexString()
    }))`);
    assert.equal(await evaluate('__bcTest.tensorGroup.children.some(mesh=>mesh.isMesh&&mesh.geometry.type!=="PlaneGeometry")'),false,
      'Tensor diagrams use face surfaces, with no arrow meshes');
    for (const face of faces) {
      assert.equal(face.type,'PlaneGeometry');
      const axis = 'xyz'.indexOf(face.normal);
      face.position.forEach((value, index) => assert.ok(Math.abs(value-(index===axis?face.faceSign*0.506:0))<1e-8));
      assert.ok(face.entries.every(entry=>entry.component[1]===face.normal&&entry.faceSign===face.faceSign));
      const opposite = faces.find(other=>other.normal===face.normal&&other.faceSign===-face.faceSign);
      assert.ok(opposite,'Every affected face must have its opposite');
      assert.deepEqual(opposite.entries.map(entry=>[entry.component,entry.value]),face.entries.map(entry=>[entry.component,entry.value]));
      const normal = face.entries.find(entry=>entry.direction===entry.normal);
      const shear = face.entries.some(entry=>entry.direction!==entry.normal);
      assert.equal(face.color,normal&&shear?'7c3aed':normal?(normal.value>0?'2563eb':'c2410c'):'0f766e');
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
  await checkConcept('xx',15);
  await screenshot('tensor-main-initial');
  assert.deepEqual(await evaluate('Array.from(document.querySelectorAll("[data-tensor-action-count]")).map(node=>node.textContent)'),['(2)','(0)','(2)']);
  assert.equal(await evaluate('document.querySelector("[data-bc-motion]").disabled'),false,
    'Reduced motion must allow an explicit manual replay');
  assert.equal(await evaluate('document.querySelector("[data-bc-motion]").getAttribute("aria-pressed")'),'false');
  const reducedRest = await evaluate('__bcTest.state.tensorMeshes.map(mesh=>mesh.position.toArray())');
  const finalExample = await evaluate(`(${concept}).matrix.toArray()`);
  const replayButton = await evaluate(`(() => {const r=document.querySelector('[data-bc-motion]').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()`);
  await command('Input.dispatchMouseEvent', {type:'mousePressed',...replayButton,button:'left',clickCount:1});
  await command('Input.dispatchMouseEvent', {type:'mouseReleased',...replayButton,button:'left',clickCount:1});
  await waitFor(`JSON.stringify((${concept}).matrix.toArray())!==${JSON.stringify(JSON.stringify(finalExample))}`,
    'A real click must animate the conceptual example with reduced motion enabled');
  await waitFor('document.querySelector("[data-bc-motion]").getAttribute("aria-pressed")==="false"','Manual replay must finish once');
  assert.deepEqual(await evaluate(`(${concept}).matrix.toArray()`),finalExample,
    'The conceptual changed shape remains visible at rest');
  assert.deepEqual(await evaluate('__bcTest.state.tensorMeshes.map(mesh=>mesh.position.toArray())'),reducedRest);
  assert.equal(await evaluate('matchMedia("(prefers-reduced-motion: reduce)").matches'),true);
  await evaluate('document.querySelector("[data-component=xy]").click();new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');
  assert.equal(await evaluate('document.querySelector("[data-bc-motion]").getAttribute("aria-pressed")'),'false');
  await evaluate('document.querySelector("[data-tensor-filter=all]").click();document.activeElement.blur()');
  assert.equal(await tensorCount(),8,'Copper keeps four independent components on their opposing faces');
  assert.equal(await evaluate('document.querySelector("[data-tensor-load]").closest("label").hidden'),true);
  assert.equal(await evaluate('document.querySelector("[data-tensor-status]").checkVisibility()'),false);
  assert.match(await evaluate('document.querySelector("[data-tensor-heading]").textContent'),/Stress \(MPa\)/);
  await checkTensorGeometry();
  for (const width of [1280, 1440, 1920]) {
    await command('Emulation.setDeviceMetricsOverride', {width, height: 1080, deviceScaleFactor: 1, mobile: false});
    await evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))');
    assert.equal(await evaluate(`(() => {const cube=document.querySelector('.bc-cube-wrap').getBoundingClientRect();
      const matrix=document.querySelector('[data-tensor-matrix]').getBoundingClientRect();
      return matrix.left>cube.right && document.querySelector('[data-bc-tensor-panel]').getBoundingClientRect().top<cube.bottom && matrix.right<=innerWidth;})()`), true,
      `Tensor matrix must sit beside the cube at ${width}`);
    await screenshot('tensor-'+width);
    const matrixValues = await evaluate('Array.from(document.querySelectorAll("[data-component] strong")).map(value=>value.textContent)');
    await evaluate('document.querySelector("[data-tensor-options]").open=true');
    for (const [filter, components] of [['pull', ['xx', 'xx']], ['push', []], ['slide', ['xy', 'xy']]]) {
      await evaluate(`document.querySelector('[data-tensor-filter=${filter}]').click();document.activeElement.blur()`);
      assert.deepEqual(await tensorComponents(), components);
      assert.deepEqual(await evaluate('Array.from(document.querySelectorAll("[data-component] strong")).map(value=>value.textContent)'), matrixValues);
      if (components.length) await checkConcept(components[0],1);
      else assert.match(await evaluate('document.querySelector("[data-tensor-description]").textContent'), /^Cube faces:/);
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
  assert.equal(await evaluate('__bcTest.state.tensorMeshes.filter(m=>m.material.opacity>0.1).length'),2);
  await evaluate('document.activeElement.blur()');
  assert.equal(await evaluate('__bcTest.state.tensorMeshes.filter(m=>m.material.opacity>0.1).length'),2,
    'Selected faces stay emphasized when focus moves away');
  await screenshot('tensor-shear-selected');
  await evaluate('document.querySelector("[data-component=xy]").click();document.activeElement.blur()');
  assert.equal(await tensorCount(),8);
  await evaluate('document.querySelector("[data-component=xx]").click();document.activeElement.blur()');
  assert.match(await evaluate('document.querySelector("[data-tensor-description]").textContent'), /Pull apart \(tension\)/);
  await screenshot('tensor-pull-selected');
  const tensorHover = await evaluate(`(() => {
    const mesh=__bcTest.state.tensorMeshes.find(m=>m.userData.components.includes('xx')&&m.position.x>0);
    const p=new __bcThree.Box3().setFromObject(mesh).getCenter(new __bcThree.Vector3()).project(__bcTest.state.camera);
    const r=document.querySelector('#mechanical-bc-cube').getBoundingClientRect();
    return {x:r.x+(p.x+1)*r.width/2,y:r.y+(1-p.y)*r.height/2};})()`);
  await command('Input.dispatchMouseEvent', {type:'mouseMoved',...tensorHover});
  assert.match(await evaluate(`${visibleTooltip}?.textContent||''`), /Stress on \+X face[\s\S]*xx: 15\.00 MPa[\s\S]*Pull/);
  assert.equal(await evaluate('document.querySelector("[data-component=xx]").classList.contains("is-hovered")'),true);
  await command('Input.dispatchMouseEvent', {type:'mouseMoved',x:0,y:0});
  assert.equal(await evaluate(`!!(${visibleTooltip})`),false);
  assert.equal(await evaluate('document.querySelector("[data-component=xx]").classList.contains("is-hovered")'),false);
  await evaluate('document.querySelector("[data-component=xx]").click();document.activeElement.blur()');
  report.push('copper: Pull/Push/Slide filter highlighted faces and examples while preserving the full matrix at 1280/1440/1920; no repeated step or stress paragraph; selection and hover stay linked');

  await open('records');
  await checkConcept('xx',-15);
  await evaluate('document.querySelector("[data-tensor-filter=all]").click()');
  assert.equal(await tensorCount(),18);
  await checkTensorGeometry();
  await evaluate('document.querySelector("[data-tensor-filter=push]").click()');
  assert.deepEqual(await tensorComponents(), ['xx', 'xx']);
  await evaluate('document.querySelector("[data-tensor-filter=all]").click();document.activeElement.blur()');
  assert.equal(await evaluate('__bcTest.state.tensorMeshes.length'),6);
  assert.equal(await evaluate('__bcTest.state.tensorMeshes.every(mesh=>mesh.userData.entries.length===3)'),true,
    'One surface per face retains all three independent components without overlapping surfaces');
  const sharedFaceHover = await evaluate(`(() => {
    const mesh=__bcTest.state.tensorMeshes.find(m=>m.userData.normal==='x'&&m.userData.faceSign===1);
    const p=mesh.position.clone().project(__bcTest.state.camera);
    const r=document.querySelector('#mechanical-bc-cube').getBoundingClientRect();
    return {x:r.x+(p.x+1)*r.width/2,y:r.y+(1-p.y)*r.height/2};})()`);
  await command('Input.dispatchMouseEvent', {type:'mouseMoved',...sharedFaceHover});
  const sharedTooltip = await evaluate(`${visibleTooltip}?.textContent||''`);
  assert.match(sharedTooltip, /xx: -15\.00 MPa · Push · -X direction/);
  assert.match(sharedTooltip, /yx: -7\.00 MPa · Slide · -Y direction/);
  assert.match(sharedTooltip, /zx: 6\.00 MPa · Slide · \+Z direction/);
  assert.deepEqual(await evaluate('Array.from(document.querySelectorAll("[data-component].is-hovered")).map(cell=>cell.dataset.component)'),
    ['xx','yx','zx'], 'A shared face highlights every associated component without guessing one');
  await command('Input.dispatchMouseEvent', {type:'mouseMoved',x:0,y:0});
  assert.equal(await evaluate('document.querySelectorAll("[data-component].is-hovered").length'),0);
  await checkTensorGeometry();
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
  report.push('nine independent components grouped on six opposing faces; exact supplied record order and absent steps');

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
  await command('Emulation.setEmulatedMedia', {features:[{name:'prefers-reduced-motion',value:'no-preference'}]});
  await open('tensor');
  async function checkMotion(trigger) {
    const motion = await evaluate(`new Promise((resolve,reject)=>{
      ${trigger};
      const drawing=()=>(${concept}).matrix.toArray();
      const original=()=>({matrix:(${reference}).matrix.toArray(),points:Array.from((${reference}).geometry.attributes.position.array)});
      const scene=()=>JSON.stringify({camera:__bcTest.state.camera.position.toArray(),
        objects:__bcTest.state.root.children.filter(object=>object!==__bcTest.tensorGroup&&!object.userData.tensorFaceAxis)
          .map(object=>({position:object.position.toArray(),scale:object.scale.toArray()}))});
      const before=drawing(), base=scene(), outlines=original(), frames=[];
      const data=JSON.stringify(__bcTest.items), values=document.querySelector('[data-tensor-matrix]').textContent;
      const started=performance.now();
      function sample(){
        frames.push(drawing());
        if(scene()!==base||JSON.stringify(original())!==JSON.stringify(outlines)) return reject(new Error('Animation changed the camera, local markers or dashed reference'));
        if(document.querySelector('[data-bc-motion]').getAttribute('aria-pressed')==='false') return resolve({before,frames,after:drawing(),
          unchanged:data===JSON.stringify(__bcTest.items)&&values===document.querySelector('[data-tensor-matrix]').textContent});
        if(performance.now()-started>3000) return reject(new Error('Main cube cue did not finish'));
        requestAnimationFrame(sample);
      }
      requestAnimationFrame(sample);
    })`);
    assert.ok(motion.frames.length>3,'A selected action animates over real browser frames');
    assert.ok(motion.frames.some(frame=>JSON.stringify(frame)!==JSON.stringify(motion.before)),'The conceptual shape must visibly change');
    assert.deepEqual(motion.after,motion.before,'Motion ends at the same readable changed-shape illustration');
    assert.equal(motion.unchanged,true,'Examples must not change supplied values or records');
  }
  await checkMotion('document.querySelector("[data-tensor-filter=pull]").click()');
  if(process.env.BC_BROWSER_REPORT_DIR){
    const clip=await evaluate(`(()=>{const r=document.querySelector('.bc-cube-wrap').getBoundingClientRect();return{x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1}})()`);
    const timings=[];
    await evaluate('document.querySelector("[data-bc-motion]").click()');
    for(let frame=0;frame<12;frame++){
      timings.push(Date.now());
      const result=await command('Page.captureScreenshot',{format:'png',clip});
      writeFileSync(join(process.env.BC_BROWSER_REPORT_DIR,`pull-motion-${String(frame).padStart(2,'0')}.png`),Buffer.from(result.data,'base64'));
      await new Promise(resolve=>setTimeout(resolve,80));
    }
    writeFileSync(join(process.env.BC_BROWSER_REPORT_DIR,'pull-motion-timings.json'),JSON.stringify(timings));
  }
  await checkMotion('document.querySelector("[data-component=xy]").click()');
  await checkConcept('xy',2);
  await open('records');
  await checkMotion('document.querySelector("[data-tensor-filter=push]").click()');
  await checkConcept('xx',-15);
  await checkMotion('document.querySelector("[data-component=yx]").click()');
  await checkConcept('yx',-7);
  const rest=await evaluate(`(${concept}).matrix.toArray()`);
  await evaluate('document.querySelector("[data-bc-motion]").click()');
  await waitFor(`JSON.stringify((${concept}).matrix.toArray())!==${JSON.stringify(JSON.stringify(rest))}`,'Replay did not animate the example');
  await evaluate('document.querySelector("[data-bc-motion]").click()');
  assert.deepEqual(await evaluate(`(${concept}).matrix.toArray()`),rest);
  await evaluate('document.querySelector("[data-bc-motion]").click();window.scrollTo({top:0,behavior:"instant"})');
  await waitFor('document.querySelector("[data-bc-motion]").getAttribute("aria-pressed")==="false"','Offscreen illustration did not stop');
  await evaluate(`document.querySelector('.bc-panel').scrollIntoView({block:'start',behavior:'instant'});window.scrollBy({top:-100,behavior:'instant'});new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))`);
  assert.equal(await evaluate('document.querySelector("[data-bc-motion]").getAttribute("aria-pressed")'),'false');
  await evaluate('document.querySelector("[data-bc-motion]").click()');
  await command('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'reduce'}]});
  await waitFor('document.querySelector("[data-bc-motion]").getAttribute("aria-pressed")==="false"','Reduced motion did not stop the example');
  assert.equal(await evaluate('document.querySelector("[data-bc-motion]").disabled'),false);
  await evaluate('document.querySelector("[data-tensor-load]").value="1";document.querySelector("[data-tensor-load]").dispatchEvent(new Event("change"))');
  assert.equal(await tensorCount(),0);
  assert.equal(await evaluate('document.querySelector("[data-bc-motion]").hidden'),true);
  await command('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'no-preference'}]});
  await open('mixed');
  await checkMotion('document.querySelector("[data-tensor-filter=push]").click()');
  assert.match(await evaluate('document.querySelector("[data-tensor-legend]").textContent'), /Local markers stay on the dashed reference/);
  await open('whole');
  assert.equal(await evaluate('!!document.querySelector("[data-bc-motion]")'),false);
  report.push('main 3D cube shows signed Pull/Push/Slide with a fixed dashed reference; right panel has no graphics; finite motion and manual reduced-motion replay preserve data, local markers and camera');
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

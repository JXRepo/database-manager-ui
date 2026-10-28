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
      body = body.replace(marker, '  window.__bcTest = {state, items, tensorGroup, baseCube};\n' + marker);
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
  const identity = [1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
  const cubeMatrix = () => evaluate('__bcTest.baseCube.matrix.toArray()');
  async function selectOnly(selector) {
    await evaluate(`document.querySelector('[data-tensor-clear]').click();document.querySelector(${JSON.stringify(selector)}).click();document.activeElement.blur()`);
    assert.deepEqual(await cubeMatrix(),identity,'Selection resets to the original cube without automatic motion');
  }
  async function actionAnimation(components, name) {
    await evaluate(`document.querySelector('[data-tensor-clear]').click();${components.map(key=>`document.querySelector('[data-component=${key}]').click();`).join('')}document.activeElement.blur()`);
    assert.match(await evaluate('document.querySelector("[data-bc-motion]").textContent'),/^Play action$/);
    const capture = `(()=>{const {state,baseCube,tensorGroup}=__bcTest;state.root.updateMatrixWorld(true);
      const mesh=baseCube.children[0], data=Array.from(mesh.geometry.attributes.position.array);
      const grips=state.root.children.find(o=>o.userData.tensorActionGrips);
      const r=document.querySelector('#mechanical-bc-cube').getBoundingClientRect();
      const world=new __bcThree.Vector3().fromBufferAttribute(mesh.geometry.attributes.position, window.actionVertex);
      const p=mesh.localToWorld(world).project(state.camera);
      return {matrix:baseCube.matrix.toArray(),data,gripsVisible:grips.visible,grips:grips.children.map(g=>({position:g.position.toArray(),anchor:g.userData.anchor})),
        point:[(p.x+1)*r.width/2,(1-p.y)*r.height/2],camera:state.camera.position.toArray(),
        originals:baseCube.children.map(o=>o.uuid),values:document.querySelector('[data-tensor-matrix]').textContent,
        source:JSON.stringify(__bcTest.items)}})()`;
    const normal=components[0][1];
    await evaluate(`window.actionVertex=(()=>{const p=__bcTest.baseCube.children[0].geometry.attributes.position;
      for(let i=0;i<p.count;i++){const v=[p.getX(i),p.getY(i),p.getZ(i)];if(v['xyz'.indexOf('${normal}')]==.5&&v.filter((_,axis)=>axis!=='xyz'.indexOf('${normal}')).every(n=>n===0))return i;}throw Error('No face center')})()`);
    const original=await evaluate(capture);
    assert.ok(original.grips.length>=2);
    assert.equal(original.gripsVisible,false,'Grip pads are hidden while the cube is at rest');
    const start=await evaluate(`(()=>{document.querySelector('[data-bc-motion]').click();return performance.now()})()`);
    await waitFor(`performance.now()-${start}>500`,'Action did not reach its tug');
    await evaluate('document.querySelector("[data-bc-motion]").click()');
    const tug=await evaluate(capture);
    assert.equal(tug.gripsVisible,true,'Grips appear only during the action');
    assert.deepEqual(tug.matrix,identity,'Action animates vertices, without scaling the whole cube matrix');
    assert.notDeepEqual(tug.data,original.data,'The original surface is locally deformed');
    assert.ok(Math.hypot(tug.point[0]-original.point[0],tug.point[1]-original.point[1])>15,'The local gripping action is visibly large at the default display');
    assert.deepEqual(tug.camera,original.camera);
    assert.deepEqual(tug.originals,original.originals,'Reuse all original meshes and white corners');
    assert.equal(tug.values,original.values);
    assert.equal(tug.source,original.source);
    assert.ok(tug.grips.some((g,i)=>g.position.some((v,j)=>Math.abs(v-original.grips[i].position[j])>.15)),'Opposing gripping pads actually move');
    assert.equal(await evaluate(`__bcTest.state.tensorMeshes.every(face=>{
      const border=__bcTest.tensorGroup.children.find(o=>o.userData.tensorOutline&&o.userData.normal===face.userData.normal&&o.userData.faceSign===face.userData.faceSign);
      const points=border.geometry.attributes.position, surface=face.geometry.attributes.position, uv=face.geometry.attributes.uv;
      for(let i=0;i<surface.count;i++){
        if(Math.min(uv.getX(i),uv.getY(i),1-uv.getX(i),1-uv.getY(i))!==0)continue;
        let attached=false;
        for(let j=0;j<points.count;j++)if(Math.hypot(surface.getX(i)-points.getX(j),surface.getY(i)-points.getY(j),surface.getZ(i)-points.getZ(j))<1e-5)attached=true;
        if(!attached)return false;
      }
      return true;
    })`),true,'Every curved highlight boundary point must remain attached to its outline');
    await screenshot(name+'-tug');
    await evaluate('document.querySelector("[data-bc-motion]").click()');
    await waitFor('document.querySelector("[data-bc-motion]").getAttribute("aria-pressed")==="false"','Action did not return');
    const returned=await evaluate(capture);
    assert.deepEqual(returned.data,original.data,'Tug and rebound return exactly to the original surface');
    assert.deepEqual(returned.grips,original.grips);
    assert.equal(returned.gripsVisible,false,'Grip pads disappear after the rebound');
    if(name==='pull'&&process.env.BC_BROWSER_REPORT_DIR){
      const clip=await evaluate(`(()=>{const r=document.querySelector('.bc-cube-wrap').getBoundingClientRect();return{x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1}})()`);
      const frames=[];
      await evaluate('document.querySelector("[data-bc-motion]").click()');
      for(let i=0;i<24;i++){
        frames.push({at:Date.now(),point:(await evaluate(capture)).point});
        const image=await command('Page.captureScreenshot',{format:'png',clip});
        writeFileSync(join(process.env.BC_BROWSER_REPORT_DIR,'pull-action-'+String(i).padStart(2,'0')+'.png'),Buffer.from(image.data,'base64'));
        await new Promise(resolve=>setTimeout(resolve,100));
      }
      writeFileSync(join(process.env.BC_BROWSER_REPORT_DIR,'pull-action-frames.json'),JSON.stringify(frames));
    }
  }
  await open('tensor',1440);
  assert.equal(await evaluate('document.querySelectorAll("[data-tensor-mode],[data-tensor-calculated],[data-tensor-scale]").length'),0);
  assert.match(await evaluate('document.querySelector("[data-tensor-action-note]").textContent'),/Illustrative motion/);
  assert.equal(await evaluate('document.querySelectorAll(".bc-table-frame").length'),0,'Pure tensors have no duplicate XYZ table');
  assert.equal(await evaluate('document.querySelector("[data-bc-tensor-fallback]").checkVisibility()'),false);
  assert.equal(await evaluate('document.querySelector("[data-tensor-details]").open'),false);
  await screenshot('action-original');
  await actionAnimation(['xx'],'pull');
  await actionAnimation(['xy'],'shear');
  await actionAnimation(['xx','xy'],'pull-shear');
  for(const width of [1280,1920]){
    await open('tensor',width);
    await actionAnimation(['xx'],'pull-'+width);
    assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'),false);
  }
  await evaluate('document.querySelector("[data-bc-motion]").click()');
  await waitFor('__bcTest.baseCube.children[0].geometry.boundingBox.max.x>.6','Action did not begin before resetting');
  await evaluate('document.querySelector("[data-bc-reset]").click()');
  assert.ok(Math.abs(await evaluate('__bcTest.baseCube.children[0].geometry.boundingBox.max.x')-.5)<1e-8,'Reset restores original vertex buffers');
  assert.equal(await evaluate('__bcTest.state.root.children.find(o=>o.userData.tensorActionGrips).visible'),false);
  assert.equal(await evaluate('document.querySelector("[data-bc-motion]").getAttribute("aria-pressed")'),'false');
  await open('elastic',1440);
  await actionAnimation(['xx'],'push');
  await actionAnimation(['xx','xy'],'push-shear');
  await open('records',1440);
  await actionAnimation(['yx'],'independent-shear');
  await open('mixed',1280);
  await actionAnimation(['xx'],'mixed-push');
  report.push('Action animation: original glass surfaces tug locally at the default display with moving opposing grip pads, then rebound exactly; Pull, Push, Shear, mixtures and independent asymmetric components; numeric matrix/data/camera unchanged');

  await open('tensor');
  assert.deepEqual(await cubeMatrix(),identity);
  assert.deepEqual(await evaluate('__bcTest.baseCube.children.map(o=>o.geometry.type)'),
    ['BoxGeometry','BoxGeometry','EdgesGeometry','EdgesGeometry',...Array(8).fill('SphereGeometry')]);
  assert.equal(await evaluate('__bcTest.baseCube.children[0].material.transparent'),true);
  assert.equal(await evaluate('__bcTest.baseCube.children.slice(4).every(o=>o.material.color.getHexString()==="ffffff")'),true);
  assert.equal(await evaluate('document.querySelector("[data-bc-tensor-panel]").querySelectorAll("svg,canvas,[data-tensor-example-host]").length'),0);
  assert.match(await evaluate('document.querySelector("[data-tensor-filter=pull]").title'),/2 of 2/);
  assert.equal(await tensorCount(),8);
  assert.equal(await evaluate('document.querySelector("[data-tensor-load]").closest("label").hidden'),true);
  await checkTensorGeometry();
  await screenshot('original-glass-cube');
  for (const width of [1280,1440,1920]) {
    await command('Emulation.setDeviceMetricsOverride',{width,height:1080,deviceScaleFactor:1,mobile:false});
    await evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');
    assert.equal(await evaluate(`(()=>{const cube=document.querySelector('.bc-cube-wrap').getBoundingClientRect(),matrix=document.querySelector('[data-tensor-matrix]').getBoundingClientRect();return matrix.left>cube.right&&matrix.right<=innerWidth})()`),true);
    assert.equal(await evaluate('document.querySelector("[data-bc-motion]").getBoundingClientRect().right < document.querySelector("[data-bc-reset]").getBoundingClientRect().left'),true,'Playback and Reset controls must not overlap');
    const values=await evaluate('document.querySelector("[data-tensor-matrix]").textContent');
    await selectOnly('[data-tensor-filter=pull]');
    assert.deepEqual(await tensorComponents(),['xx','xx','yy','yy']);
    await evaluate('document.querySelector("[data-tensor-filter=slide]").click();document.activeElement.blur()');
    assert.equal(await tensorCount(),8);
    await evaluate('document.querySelector("[data-tensor-filter=pull]").click();document.activeElement.blur()');
    assert.deepEqual(await tensorComponents(),['xy','xy','yx','yx']);
    assert.equal(await evaluate('document.querySelector("[data-tensor-matrix]").textContent'),values);
    assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'),false);
    await screenshot('tensor-controls-'+width);
  }
  await selectOnly('[data-component=xx]');
  const matrixTop=await evaluate('document.querySelector("[data-tensor-matrix]").getBoundingClientRect().top');
  await evaluate('document.querySelector("[data-component=xy]").click();document.activeElement.blur()');
  assert.equal(await evaluate('document.querySelector("[data-tensor-matrix]").getBoundingClientRect().top'),matrixTop);
  await selectOnly('[data-component=xx]');
  const tensorHover=await evaluate(`(()=>{const mesh=__bcTest.state.tensorMeshes.find(m=>m.userData.components.includes('xx')&&m.position.x>0);const p=new __bcThree.Box3().setFromObject(mesh).getCenter(new __bcThree.Vector3()).project(__bcTest.state.camera);const r=document.querySelector('#mechanical-bc-cube').getBoundingClientRect();return {x:r.x+(p.x+1)*r.width/2,y:r.y+(1-p.y)*r.height/2}})()`);
  await command('Input.dispatchMouseEvent',{type:'mouseMoved',...tensorHover});
  assert.match(await evaluate(`${visibleTooltip}?.textContent||''`),/Stress on \+X face[\s\S]*xx: 15\.00 MPa[\s\S]*Pull/);
  assert.equal(await evaluate('document.querySelector("[data-component=xx]").classList.contains("is-hovered")'),true);
  await command('Input.dispatchMouseEvent',{type:'mouseMoved',x:0,y:0});
  assert.equal(await evaluate(`!!(${visibleTooltip})`),false);
  report.push('original glass geometry, linked faces and arbitrary combinations at 1280/1440/1920; values unchanged');

  await open('records');
  assert.equal(await tensorCount(),18);
  assert.deepEqual(await cubeMatrix(),identity);
  assert.equal(await evaluate('document.querySelector("[data-bc-motion]").disabled'),false);
  await checkTensorGeometry();
  const sharedFaceHover=await evaluate(`(()=>{const mesh=__bcTest.state.tensorMeshes.find(m=>m.userData.normal==='x'&&m.userData.faceSign===1);const p=mesh.position.clone().project(__bcTest.state.camera);const r=document.querySelector('#mechanical-bc-cube').getBoundingClientRect();return{x:r.x+(p.x+1)*r.width/2,y:r.y+(1-p.y)*r.height/2}})()`);
  await command('Input.dispatchMouseEvent',{type:'mouseMoved',...sharedFaceHover});
  const sharedTooltip=await evaluate(`${visibleTooltip}?.textContent||''`);
  assert.match(sharedTooltip,/xx: -15\.00 MPa · Push · -X direction/);
  assert.match(sharedTooltip,/yx: -7\.00 MPa · Slide · -Y direction/);
  assert.match(sharedTooltip,/zx: 6\.00 MPa · Slide · \+Z direction/);
  assert.deepEqual(await evaluate('Array.from(document.querySelectorAll("[data-component].is-hovered")).map(c=>c.dataset.component)'),['xx','yx','zx']);
  await command('Input.dispatchMouseEvent',{type:'mouseMoved',x:0,y:0});
  await selectOnly('[data-component=yx]');
  assert.equal(await tensorCount(),2);
  await evaluate('document.querySelector("[data-tensor-load]").value="1";document.querySelector("[data-tensor-load]").dispatchEvent(new Event("change"))');
  assert.equal(await tensorCount(),0);
  assert.match(await evaluate('document.querySelector("[data-tensor-status]").textContent'),/missing or invalid.*yx/);
  assert.match(await evaluate('document.querySelector("[data-tensor-load]").selectedOptions[0].textContent'),/step 3$/);
  assert.equal(await evaluate('document.querySelector("[data-bc-motion]").disabled'),true);
  await evaluate('document.querySelector("[data-tensor-load]").value="2";document.querySelector("[data-tensor-load]").dispatchEvent(new Event("change"))');
  assert.equal(await tensorCount(),2);
  assert.match(await evaluate('document.querySelector("[data-tensor-load]").selectedOptions[0].textContent'),/123456789012345$/);
  await evaluate('document.querySelector("[data-tensor-load]").value="3";document.querySelector("[data-tensor-load]").dispatchEvent(new Event("change"))');
  assert.doesNotMatch(await evaluate('document.querySelector("[data-tensor-load]").selectedOptions[0].textContent'),/step/);
  await evaluate('document.querySelector("[data-tensor-filter=all]").click();document.activeElement.blur()');
  await screenshot('independent-asymmetric-tensor');
  report.push('distinct reciprocal components remain separate and can illustrate their own directions; exact record order, missing values and absent steps retained');

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
    assert.equal(await tensorCount(),10);
    assert.equal(await evaluate('document.querySelectorAll(".bc-table-frame").length'),1);
    assert.equal(await evaluate('document.querySelectorAll(".bc-table thead").length'),1);
    assert.deepEqual(await evaluate('Array.from(document.querySelectorAll(".bc-table tbody")).map(n=>n.dataset.bcTargetType)'), ['Point','Edge','Face','Whole cube']);
    assert.equal(await evaluate('document.querySelectorAll(".bc-table .bc-tensor-loads").length'),0);
    assert.match(await evaluate('document.querySelector(".bc-legend").textContent'),/Gray outline: XYZ reference/);
    await evaluate('document.querySelector(".bc-whole-select").value="1";document.querySelector(".bc-whole-select").dispatchEvent(new Event("change"))');
    assert.match(await evaluate('document.querySelector("[data-bc-scalar-legend]").textContent'), /Displacement \(mm\)/);
    assert.match(await evaluate('document.querySelector(".bc-whole-heading").textContent'),/Displacement \(mm\)/);
    assert.equal(await evaluate(`['.bc-panel','#mechanical-bc-cube','[data-tensor-matrix]'].every(selector=>{const r=document.querySelector(selector).getBoundingClientRect();return r.left>=0&&r.right<=innerWidth})`),true,`Interaction clips the diagram at ${width}`);
    await screenshot('mixed-'+width);
    report.push(`${width}px: long metadata, independent panels, stress/strain and force/displacement selection`);
  }
  await command('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'no-preference'}]});
  await open('tensor');
  await selectOnly('[data-component=xx]');
  assert.deepEqual(await cubeMatrix(),identity,'No automatic animation even without reduced-motion preference');
  const pointer=await evaluate(`(()=>{const r=document.querySelector('[data-bc-motion]').getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2}})()`);
  await command('Input.dispatchMouseEvent',{type:'mousePressed',...pointer,button:'left',clickCount:1});
  await command('Input.dispatchMouseEvent',{type:'mouseReleased',...pointer,button:'left',clickCount:1});
  await waitFor('__bcTest.baseCube.children[0].geometry.boundingBox.max.x>.6','Real pointer click did not animate the original cube');
  await evaluate('document.querySelector("[data-bc-motion]").click()');
  const paused=await evaluate('Array.from(__bcTest.baseCube.children[0].geometry.attributes.position.array)');
  assert.match(await evaluate('document.querySelector("[data-bc-motion]").textContent'),/Resume/);
  await evaluate('new Promise(resolve=>setTimeout(resolve,150))');
  assert.deepEqual(await evaluate('Array.from(__bcTest.baseCube.children[0].geometry.attributes.position.array)'),paused,'Pause holds the current geometry');
  await evaluate('document.querySelector("[data-bc-motion]").click()');
  await waitFor('document.querySelector("[data-bc-motion]").getAttribute("aria-pressed")==="false"','Resumed action did not finish');
  assert.equal(await evaluate('__bcTest.state.root.children.find(o=>o.userData.tensorActionGrips).visible'),false);
  if(process.env.BC_BROWSER_REPORT_DIR) {
    await evaluate('document.querySelector("[data-bc-reset]").click();document.querySelector("[data-bc-motion]").click()');
    const clip=await evaluate(`(()=>{const r=document.querySelector('.bc-cube-wrap').getBoundingClientRect();return{x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1}})()`);
    for(let frame=0;frame<8;frame++) {
      const result=await command('Page.captureScreenshot',{format:'png',clip});
      writeFileSync(join(process.env.BC_BROWSER_REPORT_DIR,`pull-motion-${String(frame).padStart(2,'0')}.png`),Buffer.from(result.data,'base64'));
      await new Promise(resolve=>setTimeout(resolve,100));
    }
    await waitFor('document.querySelector("[data-bc-motion]").getAttribute("aria-pressed")==="false"','Recorded animation did not finish');
  }
  await evaluate('document.querySelector("[data-bc-motion]").click();window.scrollTo({top:0,behavior:"instant"})');
  await waitFor('document.querySelector("[data-bc-motion]").getAttribute("aria-pressed")==="false"','Offscreen motion did not pause');
  await evaluate(`document.querySelector('.bc-panel').scrollIntoView({block:'start',behavior:'instant'});window.scrollBy({top:-100,behavior:'instant'});new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))`);
  assert.equal(await evaluate('document.querySelector("[data-bc-motion]").getAttribute("aria-pressed")'),'false');
  await evaluate('document.querySelector("[data-bc-motion]").click()');
  await command('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'reduce'}]});
  await waitFor('document.querySelector("[data-bc-motion]").getAttribute("aria-pressed")==="false"','Preference change did not pause');
  await evaluate('document.querySelector("[data-bc-reset]").click()');
  assert.deepEqual(await cubeMatrix(),identity);
  assert.equal(await evaluate('document.querySelector("[data-bc-motion]").disabled'),false,'Reduced motion permits explicit manual playback');
  await evaluate('document.querySelector("[data-bc-motion]").click();document.querySelector("[data-tensor-clear]").click()');
  await evaluate('new Promise(resolve=>setTimeout(resolve,150))');
  assert.deepEqual(await cubeMatrix(),identity,'A stale animation cannot modify a new selection');
  assert.equal(await evaluate('document.querySelector("[data-bc-motion]").disabled'),true);
  await open('whole');
  assert.equal(await evaluate('!!document.querySelector("[data-bc-motion]")'),false);
  report.push('real click plays; pause freezes and resumes; replay is finite; reset, offscreen and preference changes are reliable; selection changes cancel stale frames; no automatic motion');

  await command('Emulation.setScriptExecutionDisabled',{value:true});
  await command('Page.navigate',{url:config.baseUrl+config.pages.tensor});
  await waitFor(`location.href===${JSON.stringify(config.baseUrl+config.pages.tensor)}&&document.readyState==='complete'`, 'No-JavaScript page did not load');
  assert.equal(await evaluate('document.querySelector("[data-bc-tensor-panel]").checkVisibility()'),false);
  assert.equal(await evaluate('document.querySelector("[data-bc-tensor-fallback]").checkVisibility()'),true);
  assert.equal(await evaluate('document.querySelectorAll(".bc-table").length'),0);
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

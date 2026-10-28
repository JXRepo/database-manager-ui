const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {test,before} = require('node:test');
let action;
before(async()=>{
  const tensor=readFileSync(join(__dirname,'../../static/assets/js/mechanical-bc-tensor.js'),'utf8');
  const source=readFileSync(join(__dirname,'../../static/assets/js/mechanical-bc-action.js'),'utf8').replace(/^import .*;\n/gm,'');
  action=await import(`data:text/javascript;base64,${Buffer.from(tensor+'\n'+source).toString('base64')}`);
});
const shift=(point,values,amount=1)=>action.tensorActionPoint(point,values,new Set(Object.keys(values)),amount);
test('pull grips the middle of opposite faces more strongly than their corners',()=>{
  const center=shift([.5,0,0],{xx:15});
  const corner=shift([.5,.5,.5],{xx:15});
  assert.ok(center[0]>.7);
  assert.ok(center[0]-0.5>2*(corner[0]-.5),'Local tug, not uniform scaling');
  assert.ok(shift([-.5,0,0],{xx:15})[0]<-.7);
  assert.ok(shift([0,.5,0],{xx:15})[1]<.5,'The waist narrows slightly');
  assert.deepEqual(shift([.5,0,0],{xx:15}),shift([.5,0,0],{xx:15000}),'An explicitly illustrative cue does not encode physical magnitude');
});
test('push indents its face while shear slides the correct opposing faces',()=>{
  assert.ok(shift([.5,0,0],{xx:-15})[0]<.3);
  assert.ok(shift([0,.5,0],{xx:-15})[1]>.5);
  assert.ok(shift([0,.5,0],{xy:2})[0]>.2);
  assert.ok(shift([0,-.5,0],{xy:2})[0]<-.2);
  assert.ok(shift([.5,0,0],{yx:-7})[1]<-.2);
  const point=[.5,.4,0];
  const combined=shift(point,{xx:-15,xy:2});
  const push=shift(point,{xx:-15}),shear=shift(point,{xy:2});
  combined.forEach((v,i)=>assert.ok(Math.abs(v-(push[i]+shear[i]-point[i]))<1e-12));
});
test('tug has an obvious rebound, remains bounded and returns exactly to the original',()=>{
  assert.equal(action.tensorTug(0),0);
  assert.equal(action.tensorTug(1),0);
  assert.ok(action.tensorTug(.14)>action.tensorTug(.25));
  assert.ok(action.tensorTug(.36)>action.tensorTug(.25));
  for(let i=0;i<=100;i++)assert.ok(action.tensorTug(i/100)>=0&&action.tensorTug(i/100)<=1.1);
  const p=[.5,.5,.5];
  assert.deepEqual(shift(p,{xx:15},action.tensorTug(1)),p);
  assert.deepEqual(shift(p,{xx:0,yy:null,xy:NaN}),p);
  assert.deepEqual(action.tensorActionPoint(p,{xx:15},new Set(),1),p);
});

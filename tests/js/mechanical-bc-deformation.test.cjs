const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {test, before} = require('node:test');
let deformation;
const complete = {xx:15, yy:5, zz:0, xy:2, yx:2, xz:0, zx:0, yz:0, zy:0};
const context = {size:[2,2,2], lengthUnit:'mm', phaseCount:1, phaseFraction:1, solidFraction:1,
  model:{name:'Isotropic linear elasticity', youngsModulus:120000, poissonRatio:0.34, stiffnessUnit:'MPa'}};
before(async () => {
  let source = readFileSync(join(__dirname,'../../static/assets/js/mechanical-bc-deformation.js'),'utf8');
  const tensor = readFileSync(join(__dirname,'../../static/assets/js/mechanical-bc-tensor.js'),'utf8');
  source = source.replace(/^import .*;\n/gm,'');
  deformation = await import(`data:text/javascript;base64,${Buffer.from(tensor+'\n'+source).toString('base64')}`);
});
function calculate(values=complete, selected=Object.keys(values), type='stress', units={Stress:'MPa',Strain:1}, metadata=context) {
  return deformation.tensorDeformation(values,new Set(selected),type,units,metadata);
}
function close(actual, expected) { assert.ok(Math.abs(actual-expected)<1e-12,`${actual} != ${expected}`); }
test('copper response uses every selected value, Poisson coupling and real dimensions', () => {
  const original=JSON.stringify({complete,context});
  const result=calculate();
  assert.equal(result.error,'');
  close(result.matrix[0][0],13.3/120000);
  close(result.matrix[1][1],-0.1/120000);
  close(result.matrix[2][2],-6.8/120000);
  close(result.matrix[0][1],2.68/120000);
  close(result.extensions[0],2*13.3/120000);
  const doubled=calculate(Object.fromEntries(Object.entries(complete).map(([key,value])=>[key,2*value])));
  result.matrix.forEach((row,i)=>row.forEach((value,j)=>close(doubled.matrix[i][j],2*value)));
  assert.equal(JSON.stringify({complete,context}),original);
});
test('arbitrary normal and shear combinations add numerically without peak normalization', () => {
  const values={...complete,xx:-15,yy:5};
  const compression=calculate(values,['xx']);
  const shear=calculate(values,['xy','yx']);
  const combined=calculate(values,['xx','xy','yx']);
  combined.matrix.forEach((row,i)=>row.forEach((value,j)=>close(value,compression.matrix[i][j]+shear.matrix[i][j])));
  close(compression.matrix[0][0],-15/120000);
  close(compression.matrix[1][1],0.34*15/120000);
  assert.match(calculate(values,['xy']).error,/together/);
});
test('strain percent and stress/stiffness units are converted explicitly', () => {
  const values={...complete,xx:2,yy:-1,zz:0,xy:1,yx:1};
  const result=calculate(values,Object.keys(values),'strain',{Strain:'%'});
  close(result.matrix[0][0],0.02);
  close(result.matrix[0][1],0.01);
  const other=calculate(complete,Object.keys(complete),'stress',{Stress:'MPa'},
    {...context,model:{...context.model,youngsModulus:120,stiffnessUnit:'GPa'}});
  close(other.matrix[0][0],calculate().matrix[0][0]);
  assert.match(calculate(values,Object.keys(values),'strain',{Strain:'unknown'}).error,/unit/i);
});
test('unsupported or conflicting data never produces a guessed deformation', () => {
  for(const metadata of [{}, {...context,phaseCount:2}, {...context,model:{...context.model,name:'Plasticity'}},
    {...context,model:{...context.model,youngsModulus:0}}, {...context,model:{...context.model,poissonRatio:0.5}},
    {...context,model:{...context.model,stiffnessUnit:null}}]) assert.ok(calculate(complete,Object.keys(complete),'stress',{Stress:'MPa'},metadata).error);
  assert.match(calculate({...complete,yx:-7}).error,/symmetric/i);
  assert.match(calculate({...complete,zz:undefined}).error,/nine/i);
  assert.match(calculate({...complete,xx:Infinity}).error,/nine/i);
  assert.match(calculate({...complete,xx:0.2},Object.keys(complete),'strain',{Strain:1}).error,/small.strain/i);
  const empty=calculate(complete,[]);
  assert.equal(empty.matrix,null);
  assert.match(empty.error,/Select/);
});
test('reported material alias conflicts disable stress estimation but not supplied strain', () => {
  const metadata = {...context,error:'Conflicting material values for youngs_modulus.'};
  const result = calculate(complete,Object.keys(complete),'stress',{Stress:'MPa'},metadata);
  assert.equal(result.matrix,null);
  assert.match(result.error,/Conflicting.*youngs_modulus/);
  const strain = Object.fromEntries(Object.entries(complete).map(([key,value])=>[key,value/1000]));
  assert.equal(calculate(strain,Object.keys(strain),'strain',{Strain:1},metadata).error,'');
});

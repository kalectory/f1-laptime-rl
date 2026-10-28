import * as THREE from 'three';
import { buildScenery } from './scenery.js';
import { RoomEnvironment } from './vendor/RoomEnvironment.js';
import { OrbitControls } from './vendor/OrbitControls.js';
import { Sky } from './vendor/addons/objects/Sky.js';
import { EffectComposer } from './vendor/addons/postprocessing/EffectComposer.js';
import { RenderPass } from './vendor/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from './vendor/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from './vendor/addons/postprocessing/OutputPass.js';

await document.fonts.ready;

const $ = id => document.getElementById(id);
const clamp = THREE.MathUtils.clamp;
let renderer;
try {
  renderer = new THREE.WebGLRenderer({canvas:$('scene'),antialias:true,alpha:false,powerPreference:'high-performance'});
} catch (e) {
  $('loading').innerHTML='<h1>3D graphics unavailable</h1><p>This browser could not start WebGL.</p><a href="../media/replay.html">Open the 2D replay</a>';
  throw e;
}
renderer.setPixelRatio(Math.min(devicePixelRatio,2));
renderer.setSize(innerWidth,innerHeight);
renderer.outputColorSpace=THREE.SRGBColorSpace;
renderer.toneMapping=THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure=.85;
renderer.shadowMap.enabled=true;
renderer.shadowMap.type=THREE.PCFSoftShadowMap;
const scene=new THREE.Scene();
scene.fog=new THREE.Fog('#aec2d2',500,2600);
const sky=new Sky();sky.scale.setScalar(10000);scene.add(sky);
// Balance the atmospheric model against the studio-style reflection lighting.
sky.material.fragmentShader=sky.material.fragmentShader.replace('vec4( retColor, 1.0 )','vec4( retColor * vec3(0.28, 0.45, 0.70), 1.0 )');
const sunDirection=new THREE.Vector3().setFromSphericalCoords(1,THREE.MathUtils.degToRad(78),THREE.MathUtils.degToRad(225));
sky.material.uniforms.turbidity.value=2.4;
sky.material.uniforms.rayleigh.value=2.6;
sky.material.uniforms.mieCoefficient.value=.004;
sky.material.uniforms.mieDirectionalG.value=.8;
sky.material.uniforms.sunPosition.value.copy(sunDirection);
const camera=new THREE.PerspectiveCamera(innerWidth<600?68:43,innerWidth/innerHeight,.08,20000);
const controls=new OrbitControls(camera,renderer.domElement);
controls.enableDamping=true;controls.maxPolarAngle=Math.PI*.48;controls.minDistance=3;controls.maxDistance=2400;controls.enabled=false;
const pmrem=new THREE.PMREMGenerator(renderer);
const room=new RoomEnvironment();
scene.environment=pmrem.fromScene(room,.035).texture;room.dispose();pmrem.dispose();
scene.add(new THREE.HemisphereLight('#c7ddff','#65704c',1.25));
const sun=new THREE.DirectionalLight('#ffddb0',3.8);
const sunOffset=sunDirection.clone().multiplyScalar(120);
sun.position.copy(sunOffset);sun.castShadow=true;
sun.shadow.mapSize.set(2048,2048);
Object.assign(sun.shadow.camera,{left:-35,right:35,top:35,bottom:-35,near:.1,far:230});
sun.shadow.camera.updateProjectionMatrix();
sun.shadow.bias=-.00015;sun.shadow.normalBias=.025;
scene.add(sun,sun.target);

// Keep HDR highlights through bloom; tone mapping and sRGB conversion happen last.
const supportsCinema=renderer.capabilities.isWebGL2&&renderer.extensions.has('EXT_color_buffer_float');
let cinematic=supportsCinema&&innerWidth>=700,composer=null;
function renderScene(){
 renderer.info.autoReset=false;renderer.info.reset();
 if(!cinematic){renderer.render(scene,camera);return;}
 if(!composer){
  const target=new THREE.WebGLRenderTarget(innerWidth,innerHeight,{type:THREE.HalfFloatType,samples:4});
  composer=new EffectComposer(renderer,target);
  composer.addPass(new RenderPass(scene,camera));
  composer.addPass(new UnrealBloomPass(new THREE.Vector2(innerWidth,innerHeight),.28,.45,1.6));
  composer.addPass(new OutputPass());
  composer.setSize(innerWidth,innerHeight);
 }
 composer.render(0);
}
function updateCinemaButton(){
 $('cinematic').textContent=cinematic?'Cinema: on':'Cinema: off';
 $('cinematic').setAttribute('aria-pressed',String(cinematic));
 $('cinematic').disabled=!supportsCinema;
}
updateCinemaButton();
$('cinematic').onclick=()=>{cinematic=!cinematic;updateCinemaButton();if(captureMode)tick(performance.now());};

function material(color,roughness=.6,metalness=0){return new THREE.MeshStandardMaterial({color,roughness,metalness});}
function box(parent,w,h,d,mat,x=0,y=0,z=0){const m=new THREE.Mesh(new THREE.BoxGeometry(w,h,d),mat);m.position.set(x,y,z);m.castShadow=true;m.receiveShadow=true;parent.add(m);return m;}
function tube(parent,points,radius,mat){const curve=new THREE.CatmullRomCurve3(points.map(p=>new THREE.Vector3(...p)));const m=new THREE.Mesh(new THREE.TubeGeometry(curve,24,radius,8,false),mat);parent.add(m);m.castShadow=true;return m;}
function label(text,color='#ffffff',bg=null){const c=document.createElement('canvas');c.width=1024;c.height=192;const ctx=c.getContext('2d');if(bg){ctx.fillStyle=bg;ctx.fillRect(0,0,1024,192);}ctx.fillStyle=color;ctx.font='600 105px Arial';ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(text,512,100);const t=new THREE.CanvasTexture(c);t.colorSpace=THREE.SRGBColorSpace;return t;}
let seed=1907;function random(){seed=(seed*1664525+1013904223)>>>0;return seed/4294967296;}
function grain(base,amount,size=256){const c=document.createElement('canvas');c.width=c.height=size;const ctx=c.getContext('2d');const d=ctx.createImageData(size,size);for(let i=0;i<d.data.length;i+=4){const n=(random()-.5)*amount;for(let j=0;j<3;j++)d.data[i+j]=base[j]+n;d.data[i+3]=255;}ctx.putImageData(d,0,0);const t=new THREE.CanvasTexture(c);t.wrapS=t.wrapT=THREE.RepeatWrapping;t.colorSpace=THREE.SRGBColorSpace;t.anisotropy=Math.min(8,renderer.capabilities.getMaxAnisotropy());return t;}
const grassTex=grain([104,119,74],18);grassTex.repeat.set(160,160);
const ground=new THREE.Mesh(new THREE.PlaneGeometry(6500,6500),new THREE.MeshStandardMaterial({map:grassTex,roughness:1}));ground.rotation.x=-Math.PI/2;ground.position.set(650,-.04,100);ground.receiveShadow=true;scene.add(ground);
const asphaltTex=grain([62,66,70],15);
const asphalt=new THREE.MeshStandardMaterial({map:asphaltTex,bumpMap:asphaltTex,bumpScale:.025,roughness:.82});
const gravelTex=grain([168,155,128],43);
const gravel=new THREE.MeshStandardMaterial({map:gravelTex,roughness:1});
const white=material('#eef0e7',.75),red=material('#d54439',.7),barrier=material('#e8e8df',.83),carbon=material('#141b20',.5,.35),metal=material('#aeb7bb',.25,.85);
const data=await fetch('./data.json').then(r=>{if(!r.ok)throw new Error('Replay data unavailable');return r.json();}).catch(e=>{$('loading').innerHTML='<h1>Replay could not load</h1><p class="error">Refresh to try again.</p>';throw e;});
const comparison=new URLSearchParams(location.search).get('comparison');
if(data.comparisons?.[comparison]){
 data.runs=data.comparisons[comparison].runs;
 document.querySelector('.wordmark').innerHTML='TRAJECTORY <em>'+(data.comparisons[comparison].title||'TRAINED QWEN COMPARISON')+'</em>';
 const button=document.createElement('button');button.dataset.camera='duel';button.textContent='Both cars';document.querySelector('.views').prepend(button);
}
const wingWordmark=data.wordmark_svg?await new THREE.TextureLoader().loadAsync('data:image/svg+xml;charset=utf-8,'+encodeURIComponent(data.wordmark_svg.replace('<svg ', '<svg width="1187" height="256" '))):null;
if(wingWordmark){wingWordmark.colorSpace=THREE.SRGBColorSpace;wingWordmark.anisotropy=Math.min(8,renderer.capabilities.getMaxAnisotropy());}
const winner=data.runs.reduce((a,b)=>a.lap<b.lap?a:b),lapDifference=Math.abs(data.runs[1].lap-data.runs[0].lap);
document.querySelector('.badge').innerHTML='<i></i> '+data.runs.map(r=>r.short).join(' × ')+' · 5.350 KM';
$('scene').setAttribute('aria-label','Three dimensional replay of '+data.runs.map(r=>r.label).join(' versus '));
$('selected').textContent=data.runs[0].short+' / LIVE TELEMETRY';
$('finish').innerHTML=`<div class="eyebrow">${winner.short} takes the flag</div><strong>${winner.lap.toFixed(3)} <span style="font-size:12px">SECONDS</span></strong><div style="font-size:12px;margin-top:7px">${lapDifference.toFixed(3)}s faster lap</div>`;
const points=data.track.centerline;
const start=data.track.start,finishNormal=[Math.cos(start.heading),Math.sin(start.heading)];
// Saved traces stop at the last 50 ms control sample. Complete only that final
// display interval at the recorded finish time, preserving its lateral position.
for(const run of data.runs){
 const last=run.trace.at(-1),dt=run.lap-last[0];
 if(dt>0&&dt<=.051){
  const end=last.slice(),along=(last[1]-start.x)*finishNormal[0]+(last[2]-start.y)*finishNormal[1];
  const dx=Math.cos(last[3]),dy=Math.sin(last[3]),dot=dx*finishNormal[0]+dy*finishNormal[1];
  if(dot>.5){end[0]=run.lap;end[1]-=along*dx/dot;end[2]-=along*dy/dot;end[9]=data.track.length;run.trace.push(end);}
 }
}
function trackPoint(i,offset=0,height=0){const n=points.length;i=(i+n)%n;const a=points[(i+n-1)%n],b=points[(i+1)%n],p=points[i];const dx=b[0]-a[0],dy=b[1]-a[1],l=Math.hypot(dx,dy);return [p[0]-dy/l*offset,height,-p[1]-dx/l*offset];}
function ribbon(lo,hi,height,mat,filter=()=>true){const positions=[],uv=[];for(let i=0;i<points.length;i++){if(!filter(i))continue;const a=trackPoint(i,lo,height),b=trackPoint(i,hi,height),c=trackPoint(i+1,lo,height),d=trackPoint(i+1,hi,height);positions.push(...a,...c,...b,...b,...c,...d);const s=i*data.track.spacing/8,s2=(i+1)*data.track.spacing/8;uv.push(s,lo/8,s2,lo/8,s,hi/8,s,hi/8,s2,lo/8,s2,hi/8);}const geo=new THREE.BufferGeometry();geo.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));geo.setAttribute('uv',new THREE.Float32BufferAttribute(uv,2));geo.computeVertexNormals();const m=new THREE.Mesh(geo,mat);m.material.side=THREE.DoubleSide;m.receiveShadow=true;scene.add(m);return m;}
ribbon(-11,11,.005,gravel);ribbon(-6,6,.025,asphalt);
for(const side of [-1,1]){
 ribbon(side*5.85,side*5.99,.035,white);
 for(const [mat,parity] of [[white,0],[red,1]])ribbon(side*6,side*6.85,.065,mat,i=>Math.floor(i/2)%2===parity);
 const count=Math.ceil(points.length/3),inst=new THREE.InstancedMesh(new THREE.BoxGeometry(6.2,.85,.35),barrier,count);const dummy=new THREE.Object3D();
 for(let j=0;j<count;j++){const i=j*3,a=trackPoint(i,side*11.35,.43),b=trackPoint(i+3,side*11.35,.43);dummy.position.set(...a);dummy.rotation.set(0,-Math.atan2(b[2]-a[2],b[0]-a[0]),0);dummy.updateMatrix();inst.setMatrixAt(j,dummy.matrix);}inst.receiveShadow=true;scene.add(inst);
}
// The simulator times its car reference point crossing this same start plane.
const stripeGroup=new THREE.Group();stripeGroup.position.set(start.x,0,-start.y);stripeGroup.rotation.y=start.heading;scene.add(stripeGroup);
for(let x=0;x<4;x++)for(let z=0;z<12;z++){const tile=box(stripeGroup,.6,.015,1,(x+z)%2?carbon:white,(x-1.5)*.6,.05,z-5.5);tile.castShadow=false;}
const bannerMat=new THREE.MeshStandardMaterial({map:label('TRAJECTORY','#F7F9E8','#101214'),roughness:.5});
box(stripeGroup,.6,8,.6,metal,0,4,-8);box(stripeGroup,.6,8,.6,metal,0,4,8);box(stripeGroup,.8,1.9,17,carbon,0,7.3,0);
const banner=new THREE.Mesh(new THREE.PlaneGeometry(16,1.8),bannerMat);banner.position.set(-.42,7.3,0);banner.rotation.y=-Math.PI/2;stripeGroup.add(banner);
for(let i=0;i<5;i++){const m=new THREE.Mesh(new THREE.SphereGeometry(.11,10,8),new THREE.MeshStandardMaterial({color:'#53e899',emissive:'#26e891',emissiveIntensity:1.8}));m.position.set(-.5,6.0,(i-2)*.6);stripeGroup.add(m);}
// Pit buildings and grandstands give the long straight recognizable scale.
const glass=new THREE.MeshPhysicalMaterial({color:'#7092a4',metalness:.5,roughness:.12,clearcoat:1});
for(let i=0;i<10;i++){
 const x=55+i*35;box(scene,32,5,13,white,x,2.5,-24);box(scene,31,2,12,glass,x,6,-24);box(scene,34,.35,15,carbon,x,7.2,-24);
 for(let j=0;j<4;j++){box(scene,5,3.7,.15,material('#394950'),x-11+j*7,2,-17.4);}
 const sign=new THREE.Mesh(new THREE.PlaneGeometry(25,1.5),new THREE.MeshBasicMaterial({map:label(i%2?'GRAND PRIX':'TRAJECTORY')}));sign.position.set(x,5.1,-17.3);scene.add(sign);
}
const scenery=buildScenery(scene,{points,trackPoint,random,box,material,label});

function car(color,number,branded=false){
 const g=new THREE.Group();const paint=new THREE.MeshPhysicalMaterial({color,metalness:.62,roughness:.2,clearcoat:1,clearcoatRoughness:.12,envMapIntensity:1.7});
 const darkPaint=new THREE.MeshPhysicalMaterial({color:'#1a2730',metalness:.65,roughness:.23,clearcoat:1});
 function loft(stations,mat){const p=[],idx=[];for(const [x,w,lo,hi] of stations)p.push(x,lo,-w,x,lo,w,x,hi,w*.75,x,hi,-w*.75);for(let i=0;i<stations.length-1;i++)for(let j=0;j<4;j++){const a=i*4+j,b=i*4+(j+1)%4,c=(i+1)*4+j,d=(i+1)*4+(j+1)%4;idx.push(a,b,c,b,d,c);}idx.push(0,2,1,0,3,2);const n=(stations.length-1)*4;idx.push(n,n+1,n+2,n,n+2,n+3);const geo=new THREE.BufferGeometry();geo.setAttribute('position',new THREE.Float32BufferAttribute(p,3));for(let j=0;j<idx.length;j+=3)[idx[j+1],idx[j+2]]=[idx[j+2],idx[j+1]];geo.setIndex(idx);geo.computeVertexNormals();const m=new THREE.Mesh(geo,mat);m.castShadow=true;m.receiveShadow=true;g.add(m);}
 loft([[-2.7,.35,.22,.45],[-1.4,.5,.22,.7],[0,.48,.22,.83],[.8,.29,.25,.67],[2.5,.12,.23,.38]],paint);
 box(g,4.6,.09,1.55,carbon,-.25,.17,0);
 for(const side of [-1,1]){
  const pod=new THREE.Mesh(new THREE.SphereGeometry(1,24,16),paint);pod.scale.set(1.22,.34,.35);pod.position.set(-.62,.47,side*.56);pod.castShadow=true;g.add(pod);
  box(g,.09,.28,.42,carbon,.52,.5,side*.54);
  for(let j=0;j<4;j++)box(g,.06,.012,.26,carbon,-.6-j*.12,.795,side*.54);
  box(g,1.3,.06,.08,paint,-1.1,.23,side*.86);
  tube(g,[[.05,.8,side*.33],[.26,.79,side*.58]],.035,carbon);
  const mirror=box(g,.25,.1,.12,paint,.3,.82,side*.62);mirror.rotation.y=side*.13;
 }
 const cockpit=new THREE.Mesh(new THREE.SphereGeometry(1,24,16),carbon);cockpit.scale.set(.64,.17,.3);cockpit.position.set(-.1,.78,0);g.add(cockpit);
 loft([[-1.7,.09,.7,1.08],[-.85,.16,.7,1.37],[-.55,.18,.65,1.1]],paint);
 const helmet=new THREE.Mesh(new THREE.SphereGeometry(.19,24,16),material('#eaece8',.23,.3));helmet.position.set(-.2,.99,0);helmet.castShadow=true;g.add(helmet);
 const visor=new THREE.Mesh(new THREE.SphereGeometry(.195,24,16,0,Math.PI*2,Math.PI*.38,Math.PI*.2),glass);visor.position.copy(helmet.position);g.add(visor);
 tube(g,[[-.7,1.0,-.37],[.15,1.13,-.34],[.44,1.0,0],[.15,1.13,.34],[-.7,1.0,.37]],.035,darkPaint);
 tube(g,[[.44,1,0],[.58,.65,0]],.035,darkPaint);
 for(const x of [-2.1,1.65])for(const side of [-1,1]){
  tube(g,[[x*.65,.43,side*.25],[x,.36,side*.92]],.025,carbon);
  tube(g,[[x*.65-.3,.27,side*.3],[x,.34,side*.92]],.025,carbon);
 }
 const wheels=[];const tyre=material('#131617',.86);const stripe=material('#d8ca83',.55);
 for(const x of [-1.9,1.65])for(const side of [-1,1]){
  const pivot=new THREE.Group();pivot.position.set(x,.37,side*.94);g.add(pivot);
  const wheel=new THREE.Group();pivot.add(wheel);wheels.push({pivot,wheel,front:x>0});
  const rubber=new THREE.Mesh(new THREE.CylinderGeometry(.37,.37,.37,40),tyre);rubber.rotation.x=Math.PI/2;rubber.castShadow=true;wheel.add(rubber);
  for(const s of [-1,1]){
   const rim=new THREE.Mesh(new THREE.CylinderGeometry(.22,.22,.012,32),metal);rim.rotation.x=Math.PI/2;rim.position.z=s*.19;wheel.add(rim);
   const hub=new THREE.Mesh(new THREE.CylinderGeometry(.17,.17,.018,24),carbon);hub.rotation.x=Math.PI/2;hub.position.z=s*.2;wheel.add(hub);
   const ring=new THREE.Mesh(new THREE.TorusGeometry(.305,.008,6,40),stripe);ring.position.z=s*.19;wheel.add(ring);
   for(let j=0;j<6;j++){const spoke=box(wheel,.32,.025,.02,metal,0,0,s*.212);spoke.rotation.z=j*Math.PI/3;}
  }
 }
 for(let j=0;j<3;j++){const wing=box(g,.19,.035,1.92,j===2?paint:carbon,2.25+j*.17,.19+j*.06,0);wing.rotation.z=-.12;}
 for(const side of [-1,1]){box(g,.65,.25,.04,paint,2.4,.28,side*.95);box(g,.8,.56,.045,paint,-2.36,.87,side*.81);box(g,.08,.6,.08,carbon,-2.2,.66,side*.3);}
 box(g,.65,.06,1.65,darkPaint,-2.35,1.13,0);box(g,.5,.055,1.65,paint,-2.48,1.33,0);
 if(branded&&wingWordmark){
  const foilLogo=new THREE.Mesh(new THREE.PlaneGeometry(1.3,1.3*256/1187),new THREE.MeshBasicMaterial({map:wingWordmark,transparent:true,depthWrite:false,polygonOffset:true,polygonOffsetFactor:-1}));
  foilLogo.rotation.set(-Math.PI/2,0,-Math.PI/2);foilLogo.position.set(-2.48,1.362,0);g.add(foilLogo);
 }
 const decal=new THREE.Mesh(new THREE.PlaneGeometry(.65,.15),new THREE.MeshBasicMaterial({map:label(number),transparent:true,depthWrite:false}));decal.rotation.x=-Math.PI/2;decal.rotation.z=-Math.PI/2;decal.position.set(1.2,.61,0);g.add(decal);
 const tail=new THREE.Mesh(new THREE.BoxGeometry(.08,.08,.13),new THREE.MeshStandardMaterial({color:'#ff3c24',emissive:'#ff1e00',emissiveIntensity:3}));tail.position.set(-2.72,.35,0);g.add(tail);
 g.userData.wheels=wheels;scene.add(g);return g;
}
const cars=data.runs.map((r,i)=>car(r.color,i?'02':'01',r.wordmark));
const markers=data.runs.map(r=>{const m=new THREE.Mesh(new THREE.SphereGeometry(7,16,12),new THREE.MeshBasicMaterial({color:r.color}));scene.add(m);return m;});
let selected=0,mode='chase',t=0,rate=1,playing=true,last=performance.now(),snap=true;
const tmax=Math.max(...data.runs.map(r=>r.lap));$('scrub').max=tmax;
$('drivers').innerHTML=data.runs.map((r,i)=>`<button class="driver ${i?'':'active'}" data-driver="${i}"><span class="rank">0${i+1}</span><span><strong><i class="dot" style="background:${r.color}"></i>${r.short}</strong><small>${r.description||(i?'Original repository program':'Trained Qwen')}</small></span><span class="lap">${r.lap.toFixed(3)}<small>BEST LAP / S</small></span></button>`).join('');
function sample(run,time){const a=run.trace;let lo=0,hi=a.length-1;while(lo<hi){const m=Math.ceil((lo+hi)/2);if(a[m][0]<=time)lo=m;else hi=m-1;}const x=a[lo],y=a[Math.min(lo+1,a.length-1)],f=clamp((time-x[0])/(y[0]-x[0]||1),0,1);const v=x.map((n,i)=>n+(y[i]-n)*f);v[3]=x[3]+Math.atan2(Math.sin(y[3]-x[3]),Math.cos(y[3]-x[3]))*f;return v;}
function timeAtProgress(run,s){const a=run.trace;let i=0;while(i<a.length-1&&a[i+1][9]<s)i++;const b=a[Math.min(i+1,a.length-1)];return a[i][0]+clamp((s-a[i][9])/(b[9]-a[i][9]||1),0,1)*(b[0]-a[i][0]);}
const map=$('minimap'),ctx=map.getContext('2d');const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]);const minx=Math.min(...xs),maxx=Math.max(...xs),miny=Math.min(...ys),maxy=Math.max(...ys);
function mp(x,y){const scale=Math.min(404/(maxx-minx),184/(maxy-miny));return [18+(x-minx)*scale,18+(maxy-y)*scale];}
function drawMap(states){ctx.clearRect(0,0,440,220);ctx.strokeStyle='#697d88';ctx.lineWidth=4;ctx.beginPath();points.forEach((p,i)=>{const q=mp(...p);i?ctx.lineTo(...q):ctx.moveTo(...q);});ctx.closePath();ctx.stroke();states.forEach((s,i)=>{const p=mp(s[1],s[2]);ctx.beginPath();ctx.arc(...p,i===selected?7:5,0,Math.PI*2);ctx.fillStyle=data.runs[i].color;ctx.fill();ctx.strokeStyle='#fff';ctx.lineWidth=1.5;ctx.stroke();});}
// Compile cuts from replay time, so scrubbing and offline capture use the same director.
function makeBroadcastShots(runs){
 const end=Math.max(...runs.map(r=>r.lap)),firstFinish=Math.min(...runs.map(r=>r.lap));
 const winningDriver=runs[0].lap<=runs[1].lap?0:1;
 const cycle=['front','trackside','drone','cockpit','chase'];
 const shots=[{start:0,kind:'drone',driver:0,reason:'Opening shot'}];
 let nextCut=5,sequence=0,stableLeader=null,lastBattle=-20,pendingPass=null;
 const cut=(time,kind,driver,reason,duration)=>{shots.push({start:time,kind,driver,reason});nextCut=time+duration;};
 for(let time=.25;time<end;time+=.25){
  const a=sample(runs[0],time),b=sample(runs[1],time),gap=a[9]-b[9];
  const leader=gap>=0?0:1,previousLeader=stableLeader;
  if(Math.abs(gap)>1.5)stableLeader=leader; // Ignore near-ties and launch jitter.
  const changed=previousLeader!==null&&stableLeader!==previousLeader;
  if(changed&&time>3)pendingPass={time,driver:previousLeader,leader:stableLeader};
  const sinceCut=time-shots.at(-1).start;
  if(time>=firstFinish-2){cut(time,'finish',winningDriver,'Finish line',end-time);break;}
  if(pendingPass&&pendingPass.leader===stableLeader&&time-pendingPass.time<3&&sinceCut>=2.5){
   cut(time,'cockpit',pendingPass.driver,'Lead change',4.5);pendingPass=null;lastBattle=time;continue;
  }
  const oldGap=Math.abs(sample(runs[0],Math.max(0,time-1))[9]-sample(runs[1],Math.max(0,time-1))[9]);
  const close=Math.abs(gap)>3&&Math.abs(gap)<28&&Math.hypot(a[1]-b[1],a[2]-b[2])<40;
  if(time>4&&close&&oldGap-Math.abs(gap)>1.5&&time-lastBattle>=10&&sinceCut>=3){
   cut(time,'cockpit',1-leader,'Closing battle',4.5);lastBattle=time;continue;
  }
  if(time>=nextCut){
   const kind=cycle[sequence%cycle.length],driver=sequence%3===1?1-leader:leader;
   cut(time,kind,driver,'Race coverage',kind==='drone'?5.5:kind==='cockpit'?4:4.5);sequence++;
  }
 }
 return shots;
}
const broadcastShots=makeBroadcastShots(data.runs);
let broadcastShot=null;
const shotNames={drone:'LOW DRONE',front:'FRONT TRACKING',trackside:'TRACKSIDE',cockpit:'ONBOARD',chase:'REAR CHASE',finish:'FINISH LINE'};
function selectDriver(driver){
 selected=driver;$('selected').textContent=data.runs[driver].short+' / LIVE TELEMETRY';
 document.querySelectorAll('[data-driver]').forEach(el=>el.classList.toggle('active',Number(el.dataset.driver)===driver));
}
const cameraGoal=new THREE.Vector3(),targetGoal=new THREE.Vector3(),look=new THREE.Vector3();
function broadcastCamera(shot,states,forward,side){
 const car=cars[shot.driver];
 targetGoal.copy(car.position);targetGoal.y=.6;
 let fov=43;
 if(shot.kind==='drone'){
  const separation=cars[0].position.distanceTo(cars[1].position),together=separation<45;
  if(together)targetGoal.copy(cars[0].position).add(cars[1].position).multiplyScalar(.5);
  cameraGoal.copy(targetGoal).addScaledVector(forward,-22).addScaledVector(side,18);
  cameraGoal.y=30+(together?separation*.45:0);fov=50;
 }else if(shot.kind==='front'){
  cameraGoal.copy(car.position).addScaledVector(forward,16).addScaledVector(side,2.5);cameraGoal.y=2.5;fov=38;
 }else if(shot.kind==='cockpit'){
  cameraGoal.copy(car.position).addScaledVector(forward,.65);cameraGoal.y=1.08;
  targetGoal.copy(car.position).addScaledVector(forward,35);targetGoal.y=1.05;fov=68;
 }else if(shot.kind==='trackside'||shot.kind==='finish'){
  const run=data.runs[shot.driver],anchorTime=shot.kind==='finish'?run.lap:shot.start+2.25;
  const anchor=sample(run,anchorTime),before=sample(run,Math.max(0,anchorTime-1)),after=sample(run,anchorTime+1);
  const turn=Math.atan2(Math.sin(after[3]-before[3]),Math.cos(after[3]-before[3]));
  const direction=new THREE.Vector3(Math.cos(anchor[3]),0,-Math.sin(anchor[3]));
  const outside=new THREE.Vector3(Math.sin(anchor[3]),0,Math.cos(anchor[3])).multiplyScalar(turn>=0?1:-1);
  cameraGoal.set(anchor[1],0,-anchor[2]).addScaledVector(outside,20).addScaledVector(direction,8);cameraGoal.y=7.5;
  if(shot.kind==='finish'){targetGoal.set(anchor[1],.6,-anchor[2]);fov=46;}
  else fov=clamp(2*Math.atan(11/cameraGoal.distanceTo(targetGoal))*180/Math.PI,12,50);
 }else{
  cameraGoal.copy(car.position).addScaledVector(forward,-11).addScaledVector(side,7);cameraGoal.y=4;
 }
 camera.fov=innerWidth<600?Math.max(fov,60):fov;camera.updateProjectionMatrix();
}

const captureMode=new URLSearchParams(location.search).has("capture");
function tick(now){if(!captureMode)requestAnimationFrame(tick);const dt=clamp((now-last)/1000,0,.1);last=now;if(playing)t=Math.min(tmax,t+dt*rate);if(t===tmax)playing=false;
 const states=data.runs.map(r=>sample(r,t));states.forEach((s,i)=>{const c=cars[i];c.position.set(s[1],0,-s[2]);c.rotation.y=s[3];c.userData.wheels.forEach(w=>{w.pivot.rotation.y=w.front?s[5]*.35:0;w.wheel.rotation.z=-s[9]/.37;});});
 if(mode==='f1'){
  const shot=broadcastShots.findLast(shot=>shot.start<=t)||broadcastShots[0];
  if(shot!==broadcastShot){broadcastShot=shot;selectDriver(shot.driver);snap=true;}
  $('hint').textContent=`F1 · ${shotNames[shot.kind]} · ${data.runs[shot.driver].short}${shot.reason==='Lead change'?' · LEAD CHANGE':shot.reason==='Closing battle'?' · CLOSING BATTLE':''} · Recorded ghost laps`;
 }
 const c=cars[selected],s=states[selected],forward=new THREE.Vector3(Math.cos(s[3]),0,-Math.sin(s[3])),side=new THREE.Vector3(Math.sin(s[3]),0,Math.cos(s[3]));
 if(mode==='f1'){broadcastCamera(broadcastShot,states,forward,side);}
 else if(mode==='chase'){cameraGoal.copy(c.position).addScaledVector(forward,-11).addScaledVector(side,7);cameraGoal.y=4.0;targetGoal.copy(c.position).addScaledVector(forward,innerWidth<600?0:2);targetGoal.y=.5;}
 else if(mode==='duel'){const separation=cars[0].position.distanceTo(cars[1].position);targetGoal.copy(cars[0].position).add(cars[1].position).multiplyScalar(.5);targetGoal.y=.5;cameraGoal.copy(targetGoal).addScaledVector(forward,-(18+separation*1.3)).addScaledVector(side,10+separation*.15);cameraGoal.y=7+separation*.5;}
 else if(mode==='cockpit'){cameraGoal.copy(c.position).addScaledVector(forward,.65);cameraGoal.y=1.08;targetGoal.copy(c.position).addScaledVector(forward,35);targetGoal.y=1.05;}
 else if(mode==='aerial'){cameraGoal.set(650,1550,500);targetGoal.set(650,0,110);}
 if(mode!=='orbit'){const blend=snap||mode==='f1'?1:1-Math.exp(-dt*(mode==='cockpit'?70:7));camera.position.lerp(cameraGoal,blend);look.lerp(targetGoal,blend);camera.lookAt(look);}else controls.update();snap=false;
 sun.position.copy(c.position).add(sunOffset);sun.target.position.copy(c.position);sun.target.updateMatrixWorld();
 cars.forEach(car=>{car.visible=true;});markers.forEach((m,i)=>{m.visible=mode==='aerial';m.position.copy(cars[i].position);m.position.y=10;});
 $('speed').textContent=Math.round(t>=data.runs[selected].lap?0:s[4]*3.6);$('throttle').style.height=(t>=data.runs[selected].lap?0:s[6]*100)+'%';$('brake').style.height=(t>=data.runs[selected].lap?0:s[7]*100)+'%';
 $('clock').textContent=`${Math.floor(t/60)}:${(t%60).toFixed(2).padStart(5,'0')}`;$('scrub').value=t;$('play').textContent=playing?'Ⅱ':'▶';$('play').setAttribute('aria-label',playing?'Pause':'Play');
 const lead=states[0][9]-states[1][9],lag=states[0][9]>=states[1][9]?0:1,other=1-lag,delta=timeAtProgress(data.runs[other],states[other][9])-timeAtProgress(data.runs[lag],states[other][9]);
 $('gap').textContent=t>=tmax?`Final lap-time difference: ${lapDifference.toFixed(3)} seconds.`:`${data.runs[lag].short} leads · ${Math.abs(lead).toFixed(0)} m on circuit · ${Math.max(0,delta).toFixed(2)} s at matched progress`;
 $('finish').style.display=t>=winner.lap?'block':'none';drawMap(states);renderScene();
}
function setMode(next){mode=next;broadcastShot=null;camera.fov=innerWidth<600?68:43;camera.near=mode==='aerial'?100:.08;camera.updateProjectionMatrix();scene.fog.near=mode==='aerial'?2300:500;scene.fog.far=mode==='aerial'?6000:2600;controls.enabled=mode==='orbit';controls.target.copy(cars[selected].position);controls.target.y=.6;snap=true;document.querySelectorAll('[data-camera]').forEach(b=>b.classList.toggle('active',b.dataset.camera===mode));$('hint').textContent=mode==='orbit'?'Drag to orbit · scroll to zoom · right-drag to pan':'Recorded physics · shared clock · non-colliding ghost cars';}
document.querySelectorAll('[data-camera]').forEach(b=>b.onclick=()=>setMode(b.dataset.camera));
document.querySelectorAll('[data-driver]').forEach(b=>b.onclick=()=>{if(mode==='f1')setMode('chase');selectDriver(Number(b.dataset.driver));snap=true;controls.target.copy(cars[selected].position);});
document.querySelectorAll('[data-rate]').forEach(b=>b.onclick=()=>{rate=Number(b.dataset.rate);document.querySelectorAll('[data-rate]').forEach(el=>el.classList.toggle('active',el===b));});
$('play').onclick=()=>{if(t>=tmax)t=0;playing=!playing;};$('reset').onclick=()=>{t=0;snap=true;playing=true;};$('scrub').oninput=e=>{t=Number(e.target.value);snap=true;};
$('fullscreen').onclick=()=>{if(document.fullscreenElement)document.exitFullscreen();else document.documentElement.requestFullscreen().catch(()=>{});};
window.addEventListener('keydown',e=>{if(e.code==='Space'&&e.target.tagName!=='INPUT'&&e.target.tagName!=='BUTTON'){e.preventDefault();$('play').click();}});
window.addEventListener('resize',()=>{camera.aspect=innerWidth/innerHeight;camera.fov=innerWidth<600?68:43;camera.updateProjectionMatrix();renderer.setSize(innerWidth,innerHeight);if(composer)composer.setSize(innerWidth,innerHeight);if(captureMode)tick(performance.now());});
window.replay3d={seek(value){t=clamp(value,0,tmax);playing=false;snap=true;},setCamera:setMode,render(value){if(!captureMode)throw new Error("Use ?capture for frame export");t=clamp(value,0,tmax);playing=false;snap=true;tick(performance.now());},get state(){return {time:t,playing,mode,selected,broadcastShot:mode==='f1'?broadcastShot:null,broadcastShots,cameraPosition:camera.position.toArray(),cameraFov:camera.fov,laps:data.runs.map(r=>r.lap),positions:cars.map(c=>c.position.toArray()),scenery,calls:renderer.info.render.calls};}};
if(data.comparisons?.[comparison])setMode(comparison==='champions'?'chase':'duel');
if(new URLSearchParams(location.search).get('camera')==='f1')setMode('f1');
$('loading').remove();requestAnimationFrame(tick);

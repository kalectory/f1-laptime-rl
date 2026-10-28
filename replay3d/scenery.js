import * as THREE from 'three';

// Deterministic, entirely local scenery. Crowds, trees, and fence hardware use
// instancing rather than one draw call per spectator or plant.
export function buildScenery(scene, {points, trackPoint, random, box, material, label}) {
 const concrete=material('#bac0ba',.94), steel=material('#35434b',.5,.6), cream=material('#f1eadb',.7);
 const blue=material('#7584b9',.6), peach=material('#c6795b',.6);
 const glass= new THREE.MeshPhysicalMaterial({color:'#597b8b',metalness:.5,roughness:.18,clearcoat:1});
 const dummy=new THREE.Object3D(), bodies=[], heads=[], seats=[], trunks=[], crowns=[], posts=[], rails=[];
 const occupied=[], standParts=new Map();
 const crowdColors=['#c5cceb','#bb624a','#e1d9c4','#344d6c','#61908d','#5b6570','#9d8659'];
 const skinColors=['#cf9677','#9b6248','#edc9a4','#694936'];
 function instance(geometry, mat, items, shadow=false) {
  const mesh=new THREE.InstancedMesh(geometry,mat,items.length);
  items.forEach((item,i)=>{
   dummy.position.set(...item.p);dummy.rotation.set(0,item.angle||0,0);dummy.scale.set(...item.s);dummy.updateMatrix();
   mesh.setMatrixAt(i,dummy.matrix);if(item.color)mesh.setColorAt(i,new THREE.Color(item.color));
  });
  mesh.castShadow=shadow;mesh.receiveShadow=true;mesh.computeBoundingSphere();scene.add(mesh);return mesh;
 }
 function trackDistance(x,z) {
  let d=Infinity;for(let i=0;i<points.length;i+=4)d=Math.min(d,Math.hypot(x-points[i][0],z+points[i][1]));return d;
 }
 function clear(x,z,radius) {
  return trackDistance(x,z)>radius+16&&!occupied.some(o=>Math.hypot(x-o.x,z-o.z)<radius+o.radius);
 }
 function grandstand(index,side=1) {
  const anchor=trackPoint(index,side*50),ahead=trackPoint(index+1,side*50);
  if(!clear(anchor[0],anchor[2],29))return;
  const g=new THREE.Group();g.position.set(...anchor);
  // Local +z faces away from the circuit; rows rise towards the rear.
  g.rotation.y=-Math.atan2(ahead[2]-anchor[2],ahead[0]-anchor[0])+(side>0?Math.PI:0);
  scene.add(g);
  function part(w,h,d,mat,x,y,z) {
   const items=standParts.get(mat)||[];standParts.set(mat,items);
   items.push({p:g.localToWorld(new THREE.Vector3(x,y,z)).toArray(),s:[w,h,d],angle:g.rotation.y});
  }
  occupied.push({x:anchor[0],z:anchor[2],radius:33});
  part(58,.1,28,concrete,0,.03,0);
  for(let row=0;row<8;row++){
   const y=.5+row*.78,z=-9+row*2.1;
   part(52,y,2.15,concrete,0,y/2,z);
   for(let col=0;col<65;col++){
    if(col%17===0)continue; // Aisles through the seating blocks.
    const x=-25.4+col*.79;
    const at=(dx,dy,dz)=>g.localToWorld(new THREE.Vector3(x+dx,y+dy,z+dz)).toArray();
    seats.push({p:at(0,.12,0),s:[.56,.2,.55],angle:g.rotation.y,color:row%2?'#8796c4':'#d0d4df'});
    if(random()<.16)continue;
    const height=.55+random()*.13;
    bodies.push({p:at((random()-.5)*.09,.25+height/2,0),s:[.4,height,.3],angle:g.rotation.y,color:crowdColors[Math.floor(random()*crowdColors.length)]});
    heads.push({p:at(0,.35+height,0),s:[.15,.18,.15],color:skinColors[Math.floor(random()*skinColors.length)]});
   }
  }
  for(const x of [-26,-13,0,13,26]){
   part(.23,10.6,.23,steel,x,5.3,10);
   const beam=box(g,.18,.25,24,steel,x,10.4,0);beam.rotation.x=-.06;
  }
  const roof=box(g,56,.22,25,cream,0,10.8,.3);roof.rotation.x=-.06;
  part(56,.9,.15,blue,0,10.1,-12.1);
  const sign=new THREE.Mesh(new THREE.PlaneGeometry(31,.72),new THREE.MeshBasicMaterial({map:label('TRAJECTORY GRAND PRIX')}));
  sign.position.set(0,10.12,-12.2);sign.rotation.y=Math.PI;g.add(sign);
  for(const x of [-26,26]){
   part(.13,1.2,20,steel,x,7.15,0);
   for(let row=0;row<8;row++)part(.09,1.05,.09,steel,x,1.1+row*.78,-9+row*2.1);
  }
 }
 // Continuous spectator sections along the straights, with gaps for access.
 for(let i=50;i<=450;i+=40)grandstand(i,-1);
 for(const [start,end,side] of [[620,900,1],[1020,1140,-1],[1220,1460,1],[1580,1740,1],[1860,2300,1],[2400,2600,1]])
  for(let i=start;i<=end;i+=40)grandstand(i,side);
 for(const [mat,items] of standParts)instance(new THREE.BoxGeometry(1,1,1),mat,items,true);
 instance(new THREE.BoxGeometry(1,1,1),material('#ffffff',.9),seats);
 instance(new THREE.BoxGeometry(1,1,1),material('#ffffff',.93),bodies);
 instance(new THREE.IcosahedronGeometry(1,1),material('#ffffff',.95),heads);

 // Diamond-mesh catch fencing, with shared geometry for the entire circuit.
 const canvas=document.createElement('canvas');canvas.width=canvas.height=128;
 const ctx=canvas.getContext('2d');ctx.strokeStyle='#aeb8bd';ctx.lineWidth=1.1;
 for(let i=-128;i<=256;i+=16){ctx.beginPath();ctx.moveTo(i,0);ctx.lineTo(i+128,128);ctx.moveTo(i,0);ctx.lineTo(i-128,128);ctx.stroke();}
 const net=new THREE.CanvasTexture(canvas);net.wrapS=net.wrapT=THREE.RepeatWrapping;net.colorSpace=THREE.SRGBColorSpace;
 const positions=[],uv=[];
 for(const side of [-1,1])for(let i=0;i<points.length;i+=8){
  const a=trackPoint(i,side*11.6),b=trackPoint((i+8)%points.length,side*11.6),len=Math.hypot(a[0]-b[0],a[2]-b[2]);
  positions.push(a[0],.85,a[2],b[0],.85,b[2],a[0],4.25,a[2],a[0],4.25,a[2],b[0],.85,b[2],b[0],4.25,b[2]);
  uv.push(0,0,len/2,0,0,1.7,0,1.7,len/2,0,len/2,1.7);
  posts.push({p:[a[0],2.1,a[2]],s:[.065,4.2,.065]});
  rails.push({p:[(a[0]+b[0])/2,4.25,(a[2]+b[2])/2],s:[len,.055,.055],angle:-Math.atan2(b[2]-a[2],b[0]-a[0])});
 }
 const geo=new THREE.BufferGeometry();geo.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));geo.setAttribute('uv',new THREE.Float32BufferAttribute(uv,2));
 const fence=new THREE.Mesh(geo,new THREE.MeshBasicMaterial({map:net,transparent:true,opacity:.32,side:THREE.DoubleSide,depthWrite:false}));scene.add(fence);
 instance(new THREE.BoxGeometry(1,1,1),steel,posts);instance(new THREE.BoxGeometry(1,1,1),steel,rails);

 // Paddock service lane, team awnings, transporters, and hospitality tower.
 box(scene,390,.08,18,material('#6c7273',.94),215,.01,-65);
 for(let i=0;i<9;i++){
  const x=65+i*36;
  box(scene,18,3.4,7,i%2?blue:peach,x,1.7,-80);
  box(scene,4,2.8,6,cream,x+11,1.4,-80);
  for(const dx of [-6,5])for(const z of [-83.5,-76.5])box(scene,1,.8,.6,steel,x+dx,.4,z);
  const tent=new THREE.Mesh(new THREE.ConeGeometry(9,3,4),cream);tent.rotation.y=Math.PI/4;tent.position.set(x,5.5,-46);scene.add(tent);
  for(const dx of [-6,6])for(const dz of [-6,6])box(scene,.1,4,.1,steel,x+dx,2,-46+dz);
 }
 box(scene,18,17,16,glass,430,8.5,-33);
 for(const y of [1,5,9,13,17])box(scene,21,.35,19,cream,430,y,-33);
 box(scene,22,.3,20,steel,430,18,-33);
 const towerSign=new THREE.Mesh(new THREE.PlaneGeometry(17,1.7),new THREE.MeshBasicMaterial({map:label('TRAJECTORY')}));towerSign.position.set(430,15.5,-24.8);scene.add(towerSign);
 box(scene,490,.06,5,concrete,300,.03,69);
 const parked=[],windows=[],parkingLines=[];
 box(scene,390,.07,43,material('#777c7c',.96),215,.01,-121);
 for(let row=0;row<3;row++)for(let col=0;col<48;col++){
  const x=31+col*7.8,z=-106-row*13;
  parkingLines.push({p:[x-3,.06,z],s:[.08,.02,5.2]});
  if(random()<.23)continue;
  parked.push({p:[x,.6,z],s:[1.9,1.05,4.4],color:['#c6c6bb','#343f46','#8296ab','#ac6c57'][Math.floor(random()*4)]});
  windows.push({p:[x,1.25,z],s:[1.7,.5,2.5]});
 }
 instance(new THREE.BoxGeometry(1,1,1),material('#ffffff',.4,.2),parked);
 instance(new THREE.BoxGeometry(1,1,1),glass,windows);
 instance(new THREE.BoxGeometry(1,1,1),cream,parkingLines);
 // A pedestrian bridge clears both the cars and the catch fences.
 for(const z of [-17,17])box(scene,1.3,8,1.3,concrete,705,4,z);
 box(scene,4,.45,39,steel,705,8.2,0);
 for(const x of [703,707]){
  box(scene,.14,1.4,39,blue,x,9.1,0);
  const sign=new THREE.Mesh(new THREE.PlaneGeometry(30,1.2),new THREE.MeshBasicMaterial({map:label('TRAJECTORY GRAND PRIX')}));sign.position.set(x+(x<705?-.08:.08),9.1,0);sign.rotation.y=x<705?-Math.PI/2:Math.PI/2;scene.add(sign);
 }
 for(const [x,z,angle] of [[570,43,Math.PI],[1040,215,0],[670,500,Math.PI]]){
  const g=new THREE.Group();g.position.set(x,0,z);g.rotation.y=angle;scene.add(g);
  for(const dx of [-4,4])box(g,.4,8,.4,steel,dx,4,0);
  box(g,15,7,.5,steel,0,10,0);
  const screen=new THREE.Mesh(new THREE.PlaneGeometry(14.3,6.3),new THREE.MeshBasicMaterial({map:label('QWEN  ×  OPUS','#aeb8f2','#111b25')}));screen.position.set(0,10,.27);g.add(screen);
 }

 // Trees stay clear of the circuit, grandstands, and the main-straight paddock.
 const groves=[[-250,250],[1550,150],[1200,680],[450,660],[650,-420],[-100,-400],[600,140],[1150,110]];
 for(let i=0;i<5000&&trunks.length<1400;i++){
  const center=groves[Math.floor(random()*groves.length)],a=random()*Math.PI*2,r=Math.sqrt(random())*135;
  const scattered=random()<.15;
  const x=scattered?-450+random()*2250:center[0]+Math.cos(a)*r,z=scattered?-580+random()*1500:center[1]+Math.sin(a)*r;
  if(x>-30&&x<800&&z>-150&&z<100)continue;
  if(!clear(x,z,12))continue;
  const h=6+random()*6,w=2.2+random()*2;
  trunks.push({p:[x,h*.35,z],s:[.24,h*.7,.24]});
  for(let j=0;j<3;j++)crowns.push({p:[x+(random()-.5)*w,h*(.67+j*.12),z+(random()-.5)*w],s:[w,h*.3,w],color:['#405a39','#526b43','#61794a','#355444'][Math.floor(random()*4)]});
 }
 instance(new THREE.CylinderGeometry(1,1.3,1,7),material('#61503c',1),trunks);
 instance(new THREE.IcosahedronGeometry(1,1),material('#ffffff',1),crowns);
 // One continuous heightfield: flat around the venue, rising into irregular
 // wooded ridges. Several scales of smooth noise avoid repeated dome shapes.
 function noise(x,z) {
  const ix=Math.floor(x),iz=Math.floor(z),fx=x-ix,fz=z-iz;
  const hash=(a,b)=>{const v=Math.sin(a*127.1+b*311.7)*43758.5453;return v-Math.floor(v);};
  const u=fx*fx*(3-2*fx),v=fz*fz*(3-2*fz);
  return THREE.MathUtils.lerp(THREE.MathUtils.lerp(hash(ix,iz),hash(ix+1,iz),u),THREE.MathUtils.lerp(hash(ix,iz+1),hash(ix+1,iz+1),u),v);
 }
 const terrain=new THREE.PlaneGeometry(6500,6500,180,180);terrain.rotateX(-Math.PI/2);terrain.translate(650,0,100);
 const vertices=terrain.attributes.position,colors=[],green=new THREE.Color('#60764a'),rock=new THREE.Color('#85836a');
 for(let i=0;i<vertices.count;i++){
  const x=vertices.getX(i),z=vertices.getZ(i),radius=Math.hypot((x-650)/1250,(z-100)/850);
  const rise=THREE.MathUtils.smoothstep(radius,1,1.9);
  const broad=noise(x/650,z/650),detail=noise(x/180+19,z/180+7);
  const h=rise*(80+340*broad+50*detail+12*noise(x/55,z/55));
  vertices.setY(i,h-.12);
  const c=green.clone().lerp(rock,THREE.MathUtils.smoothstep(h,180,380)*.65).multiplyScalar(.88+.22*detail);
  colors.push(c.r,c.g,c.b);
 }
 terrain.setAttribute('color',new THREE.Float32BufferAttribute(colors,3));terrain.computeVertexNormals();
 const hills=new THREE.Mesh(terrain,new THREE.MeshStandardMaterial({vertexColors:true,roughness:1}));hills.receiveShadow=true;scene.add(hills);
 return {grandstands:occupied.length,spectators:bodies.length,trees:trunks.length,fencePosts:posts.length,parkedCars:parked.length};
}

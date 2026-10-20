"""Graphics mode: turn one or more lap results (with traces) into a self-contained HTML replay.

Multiple runs are overlaid as ghost cars so rollouts can be compared on the same clock.
"""

from __future__ import annotations

import json
from pathlib import Path

from f1env.track import get_track

# (label, s_start, s_end) along the centerline; panels zoom to these windows
CORNERS = [
    ("T1 · hairpin", 900.0, 1300.0),
    ("T2–T5 · esses", 1330.0, 1860.0),
    ("T8–T9 · chicane", 2680.0, 2960.0),
    ("T12–T13 · final lefts", 4900.0, 5350.0),
]


def _corner_boxes(track):
    out = []
    for label, s0, s1 in CORNERS:
        pts = [p for p, cs in zip(track.points, track.cum_s) if s0 <= cs <= s1]
        pad = track.wall + 8
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        out.append({"label": label, "s0": s0, "s1": s1,
                    "box": [min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad]})
    return out


COLORS = ["#ff3b30", "#0a84ff", "#ffd60a", "#30d158", "#bf5af2", "#ff9f0a", "#64d2ff", "#ff375f"]


def render_html(runs: list[dict], out_path: str | Path, title: str = "F1 Lap Replay") -> Path:
    """runs: [{"label": str, "result": run_lap() result incl. "trace", "code": str | None,
    "response": full model response text | None}]"""
    tr = get_track()
    track = tr.to_dict()
    payload = []
    for i, r in enumerate(runs):
        res = dict(r["result"])
        trace = res.pop("trace", [])
        res.pop("policy_stdout_tail", None)
        payload.append({"label": r["label"], "color": COLORS[i % len(COLORS)], "result": res, "trace": trace,
                        "code": r.get("code"), "response": r.get("response")})
    data = json.dumps({"track": track, "runs": payload, "title": title, "corners": _corner_boxes(tr)}, separators=(",", ":"))
    html = _TEMPLATE.replace("__DATA__", data).replace("__TITLE__", title)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    return out


_TEMPLATE = r"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#0e0f12;--panel:#17191e;--line:#2a2d35;--text:#e8e9ec;--muted:#8b8f99;--grass:#16301d;--gravel:#5a4c36;--asphalt:#3a3d44}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:13px/1.4 -apple-system,BlinkMacSystemFont,"Inter",system-ui,sans-serif}
header{display:flex;align-items:center;gap:16px;padding:12px 16px;border-bottom:1px solid var(--line)}
header h1{font-size:15px;margin:0;font-weight:600}header .sub{color:var(--muted)}
#wrap{display:grid;grid-template-columns:1fr 340px;gap:12px;padding:12px 16px}
@media (max-width:900px){#wrap{grid-template-columns:1fr}}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden}
canvas{display:block;width:100%}
#controls{display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding:10px 12px;border-top:1px solid var(--line)}
button{background:#23262d;color:var(--text);border:1px solid var(--line);border-radius:6px;padding:5px 10px;font:inherit;cursor:pointer}
button.on{background:#e8e9ec;color:#111}
input[type=range]{flex:1;min-width:120px;accent-color:#ff3b30}
#clock{font-variant-numeric:tabular-nums;font-weight:600;min-width:70px}
.run{padding:10px 12px;border-bottom:1px solid var(--line);cursor:pointer}.run.sel{background:#1f2229}
.run .top{display:flex;align-items:center;gap:8px}.dot{width:10px;height:10px;border-radius:50%}
.run .name{font-weight:600;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.res{font-variant-numeric:tabular-nums;font-weight:600}.dnf{color:#ff6b6b}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:8px;color:var(--muted);font-size:12px}
.stats b{display:block;color:var(--text);font-variant-numeric:tabular-nums;font-size:14px}
.bar{height:6px;background:#2a2d35;border-radius:3px;overflow:hidden;margin-top:3px}.bar i{display:block;height:100%}
#follow{aspect-ratio:1/1}
#corners{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}
@media (max-width:900px){#corners{grid-template-columns:1fr}#wrap>div[style]{grid-row:auto!important;grid-column:auto!important}}
.corner .cl{display:flex;justify-content:space-between;padding:8px 12px;border-bottom:1px solid var(--line);font-weight:600}
.corner .ct{padding:6px 12px 10px;font-size:12px;color:var(--muted);display:grid;gap:3px}
.corner .ct div{display:flex;gap:8px;align-items:center;font-variant-numeric:tabular-nums}.corner .ct span.n{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.corner canvas{aspect-ratio:4/3}
.modal{position:fixed;inset:0;background:rgba(0,0,0,.6);display:none;align-items:center;justify-content:center;z-index:10;padding:16px}
.modal.open{display:flex}.modal .box{background:var(--panel);border:1px solid var(--line);border-radius:10px;width:min(1000px,100%);max-height:90vh;display:flex;flex-direction:column}
.modal .hd{display:flex;align-items:center;gap:8px;padding:10px 12px;border-bottom:1px solid var(--line)}.modal .hd b{flex:1}
.modal pre{margin:0;overflow:auto;padding:12px 0;font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;counter-reset:ln}
.modal pre span{display:block;padding:0 14px 0 0;white-space:pre}.modal pre span::before{counter-increment:ln;content:counter(ln);display:inline-block;width:44px;padding-right:12px;text-align:right;color:#555b66;user-select:none}
.codebtn{margin-top:8px;font-size:12px;padding:3px 8px}
.label{padding:8px 12px;color:var(--muted);font-size:12px;border-bottom:1px solid var(--line)}
</style></head><body>
<header><h1 id="title"></h1><span class="sub" id="sub"></span></header>
<div id="wrap">
 <div class="card"><canvas id="map"></canvas>
  <div id="controls"><button id="play">Pause</button><span id="clock">0.00s</span>
   <input id="scrub" type="range" min="0" max="1000" value="0">
   <span id="speeds"></span></div></div>
 <div id="cornersWrap"><div class="label" style="border:0;padding:4px 2px 8px">Corner close-ups — each car's path through the turn (solid = selected car)</div><div id="corners"></div></div>
 <div style="grid-row:1/span 2;grid-column:2">
  <div class="card"><div class="label">Onboard camera — selected car</div><canvas id="follow"></canvas></div>
  <div class="card" style="margin-top:12px" id="runs"></div>
 </div>
</div>
<div class="modal" id="modal"><div class="box"><div class="hd"><span class="dot" id="mdot"></span><b id="mtitle"></b>
<button id="mcode" class="on">Policy code</button><button id="mresp">Full response</button><button id="mcopy">Copy</button><button id="mclose">Close</button></div><pre id="mpre"></pre></div></div>
<script>
const D=__DATA__;
const T=D.track, R=D.runs;
document.getElementById('title').textContent=D.title;
document.getElementById('sub').textContent=`${T.name} · ${(T.length/1000).toFixed(3)} km · ${R.length} run(s)`;
const C=T.centerline, N=C.length;
function offsetLine(off){const o=[];for(let i=0;i<N;i++){const a=C[(i-1+N)%N],b=C[(i+1)%N];let dx=b[0]-a[0],dy=b[1]-a[1];const L=Math.hypot(dx,dy)||1;o.push([C[i][0]-dy/L*off,C[i][1]+dx/L*off]);}return o;}
const L1=offsetLine(T.half_width),R1=offsetLine(-T.half_width),LW=offsetLine(T.wall_offset),RW=offsetLine(-T.wall_offset);
let xmin=1e9,xmax=-1e9,ymin=1e9,ymax=-1e9;for(const p of LW.concat(RW)){xmin=Math.min(xmin,p[0]);xmax=Math.max(xmax,p[0]);ymin=Math.min(ymin,p[1]);ymax=Math.max(ymax,p[1]);}
const tmax=Math.max(...R.map(r=>r.trace.length?r.trace[r.trace.length-1][0]:0),1);
let t=0,playing=true,rate=1,sel=0;
// sample a run's state at time t (linear interpolation of the 20 Hz trace)
function at(run,t){const tr=run.trace;if(!tr.length)return null;if(t>=tr[tr.length-1][0])return {s:tr[tr.length-1],done:true};let lo=0,hi=tr.length-1;while(hi-lo>1){const m=(lo+hi)>>1;if(tr[m][0]<=t)lo=m;else hi=m;}const a=tr[lo],b=tr[hi],u=(t-a[0])/((b[0]-a[0])||1);const s=a.map((v,k)=>k==3?a[3]+(((b[3]-a[3]+Math.PI)%(2*Math.PI)+2*Math.PI)%(2*Math.PI)-Math.PI)*u:v+(b[k]-v)*u);return {s,done:false};}
function poly(ctx,P,close){ctx.beginPath();P.forEach((p,i)=>i?ctx.lineTo(p[0],p[1]):ctx.moveTo(p[0],p[1]));if(close)ctx.closePath();}
function drawTrack(ctx,ppm){ctx.fillStyle=getComputedStyle(document.documentElement).getPropertyValue('--grass');ctx.fillRect(-1e5,-1e5,2e5,2e5);
 ctx.lineJoin='round';ctx.strokeStyle='#5a4c36';ctx.lineWidth=2*T.wall_offset;poly(ctx,C,true);ctx.stroke();
 ctx.strokeStyle='#3a3d44';ctx.lineWidth=2*T.half_width;poly(ctx,C,true);ctx.stroke();
 ctx.lineWidth=Math.max(0.3,1/ppm);ctx.strokeStyle='#d9d9d9';poly(ctx,L1,true);ctx.stroke();poly(ctx,R1,true);ctx.stroke();
 ctx.strokeStyle='#9aa0a6';ctx.lineWidth=Math.max(0.5,1.5/ppm);poly(ctx,LW,true);ctx.stroke();poly(ctx,RW,true);ctx.stroke();
 // start/finish chequer
 const s=C[0],h=T.start.heading,nx=-Math.sin(h),ny=Math.cos(h);ctx.strokeStyle='#fff';ctx.lineWidth=Math.max(1.5,2/ppm);ctx.beginPath();ctx.moveTo(s[0]+nx*T.half_width,s[1]+ny*T.half_width);ctx.lineTo(s[0]-nx*T.half_width,s[1]-ny*T.half_width);ctx.stroke();}
function speedColor(v){const f=Math.max(0,Math.min(1,v/95));const h=(1-f)*220;return `hsl(${h},90%,55%)`;}
function drawTrail(ctx,run,t,ppm,full){const tr=run.trace;ctx.lineWidth=Math.max(1,2.2/ppm);for(let i=1;i<tr.length&&tr[i][0]<=t;i++){if(!full&&tr[i][0]<t-12)continue;ctx.strokeStyle=speedColor(tr[i][4]);ctx.beginPath();ctx.moveTo(tr[i-1][1],tr[i-1][2]);ctx.lineTo(tr[i][1],tr[i][2]);ctx.stroke();}}
function drawCar(ctx,run,st,ppm,minPx){const [_,x,y,h]=st.s;const sc=Math.max(1,minPx/(5.6*ppm));ctx.save();ctx.translate(x,y);ctx.rotate(h);ctx.scale(sc,sc);ctx.fillStyle=run.color;ctx.strokeStyle='#000';ctx.lineWidth=0.15;
 ctx.beginPath();ctx.moveTo(2.9,0);ctx.lineTo(1.2,0.55);ctx.lineTo(-2.4,0.8);ctx.lineTo(-2.8,0.8);ctx.lineTo(-2.8,-0.8);ctx.lineTo(-2.4,-0.8);ctx.lineTo(1.2,-0.55);ctx.closePath();ctx.fill();ctx.stroke();
 ctx.fillStyle='#111';[[1.6,1],[1.6,-1],[-2,1],[-2,-1]].forEach(([wx,wy])=>ctx.fillRect(wx-0.35,wy-0.2,0.7,0.4));ctx.fillStyle=run.color;ctx.fillRect(2.4,-0.95,0.4,1.9);ctx.fillRect(-2.95,-0.9,0.35,1.8);ctx.restore();}
function setupCanvas(cv,aspect){const w=cv.clientWidth,h=aspect?w*aspect:cv.clientHeight,dpr=devicePixelRatio||1;if(cv.width!==Math.round(w*dpr)||cv.height!==Math.round(h*dpr)){cv.width=Math.round(w*dpr);cv.height=Math.round(h*dpr);cv.style.height=h+'px';}return {w,h,dpr};}
const map=document.getElementById('map'),fol=document.getElementById('follow');
function draw(){drawCorners();
 const A=(ymax-ymin+40)/(xmax-xmin+40);const m=setupCanvas(map,Math.min(A,0.75));const ctx=map.getContext('2d');
 const ppm=Math.min(m.w/(xmax-xmin+40),m.h/(ymax-ymin+40));ctx.setTransform(m.dpr*ppm,0,0,-m.dpr*ppm,m.dpr*(m.w/2-ppm*(xmin+xmax)/2),m.dpr*(m.h/2+ppm*(ymin+ymax)/2));
 drawTrack(ctx,ppm);R.forEach((r,i)=>{if(i===sel)drawTrail(ctx,r,t,ppm,true);});R.forEach((r,i)=>{const st=at(r,t);if(st)drawCar(ctx,r,st,ppm,(window.CAR_PX||1)*(i===sel?16:12));});
 // follow cam
 const f=setupCanvas(fol,window.FOLLOW_ASPECT||1);const c2=fol.getContext('2d');const run=R[sel],st=at(run,t);
 if(st){const fppm=Math.max(1.2,6-st.s[4]*0.045);const [_,x,y,h]=st.s;c2.setTransform(f.dpr*fppm,0,0,-f.dpr*fppm,0,0);
  c2.setTransform(1,0,0,1,0,0);c2.translate(f.dpr*f.w/2,f.dpr*f.h*0.62);c2.scale(f.dpr*fppm,-f.dpr*fppm);c2.rotate(Math.PI/2-h);c2.translate(-x,-y);
  drawTrack(c2,fppm);R.forEach((r,i)=>{if(i===sel)drawTrail(c2,r,t,fppm,false);});R.forEach(r=>{const s2=at(r,t);if(s2)drawCar(c2,r,s2,fppm,0);});
  c2.setTransform(1,0,0,1,0,0);c2.fillStyle='rgba(0,0,0,.55)';c2.fillRect(8*f.dpr,8*f.dpr,150*f.dpr,58*f.dpr);c2.fillStyle='#fff';c2.font=`600 ${22*f.dpr}px -apple-system,system-ui`;c2.fillText(`${(st.s[4]*3.6).toFixed(0)} km/h`,16*f.dpr,36*f.dpr);
  c2.font=`${11*f.dpr}px -apple-system,system-ui`;c2.fillStyle='#bbb';c2.fillText(`${run.label}`,16*f.dpr,56*f.dpr);}
 document.getElementById('clock').textContent=t.toFixed(2)+'s';document.getElementById('scrub').value=Math.round(t/tmax*1000);
 R.forEach((r,i)=>{const st=at(r,t),el=document.getElementById('live'+i);if(!st||!el)return;const s=st.s;
  el.innerHTML=`<div>Speed<b>${(s[4]*3.6).toFixed(0)}</b></div><div>Throttle<div class="bar"><i style="width:${s[6]*100}%;background:#30d158"></i></div></div><div>Brake<div class="bar"><i style="width:${s[7]*100}%;background:#ff3b30"></i></div></div><div>Steer<b>${(s[5]*100).toFixed(0)}%</b></div><div>Offset<b>${s[8].toFixed(1)} m</b></div><div>${st.done?'Done':'Running'}<b>${st.done?(r.result.finished?'✓':'✗'):''}</b></div>`;});
}
const K=D.corners||[];
// trace column 9 is unwrapped lap progress (m); older traces fall back to the box test
function inCorner(row,c){if(row.length>9)return row[9]>=c.s0&&row[9]<=c.s1;const b=c.box;return row[1]>=b[0]&&row[1]<=b[2]&&row[2]>=b[1]&&row[2]<=b[3];}
function cornerStats(run,c){const rows=run.trace.filter(r=>inCorner(r,c));if(rows.length<2)return null;return {time:rows[rows.length-1][0]-rows[0][0],vmin:Math.min(...rows.map(r=>r[4]))*3.6,complete:run.trace.some(r=>r.length>9?r[9]>c.s1:false)||!run.result||run.result.finished};}
function buildCorners(){const el=document.getElementById('corners');el.innerHTML='';K.forEach((c,ci)=>{const d=document.createElement('div');d.className='card corner';
 const rows=R.map((r,i)=>{const st=cornerStats(r,c);return `<div><span class="dot" style="background:${r.color}"></span><span class="n">${r.label}</span>${st?`<span>${st.time.toFixed(2)}s</span><span>min ${st.vmin.toFixed(0)} km/h</span>`:'<span>—</span>'}</div>`;}).join('');
 d.innerHTML=`<div class="cl"><span>${c.label}</span></div><canvas id="corner${ci}"></canvas><div class="ct">${rows}</div>`;el.appendChild(d);});}
function drawCorners(){K.forEach((c,ci)=>{const cv=document.getElementById('corner'+ci);if(!cv)return;const m=setupCanvas(cv,0.75);const ctx=cv.getContext('2d');const b=c.box;
 const ppm=Math.min(m.w/(b[2]-b[0]),m.h/(b[3]-b[1]));ctx.setTransform(m.dpr*ppm,0,0,-m.dpr*ppm,m.dpr*(m.w/2-ppm*(b[0]+b[2])/2),m.dpr*(m.h/2+ppm*(b[1]+b[3])/2));
 drawTrack(ctx,ppm);
 R.forEach((r,i)=>{if(i===sel)return;ctx.strokeStyle=r.color;ctx.globalAlpha=0.75;ctx.lineWidth=1.6/ppm;ctx.setLineDash([5/ppm,3/ppm]);ctx.beginPath();let on=false;for(const row of r.trace){if(row[0]>t)break;if(inCorner(row,c)){on?ctx.lineTo(row[1],row[2]):ctx.moveTo(row[1],row[2]);on=true;}else on=false;}ctx.stroke();});
 ctx.setLineDash([]);ctx.globalAlpha=1;const r=R[sel];if(r){ctx.lineWidth=3/ppm;let prev=null;for(const row of r.trace){if(row[0]>t)break;if(inCorner(row,c)&&prev&&inCorner(prev,c)){ctx.strokeStyle=speedColor(row[4]);ctx.beginPath();ctx.moveTo(prev[1],prev[2]);ctx.lineTo(row[1],row[2]);ctx.stroke();}prev=row;}}
 R.forEach((r,i)=>{const st=at(r,t);if(st&&inCorner(st.s,c))drawCar(ctx,r,st,ppm,i===sel?14:10);});});}
function runsPanel(){const el=document.getElementById('runs');el.innerHTML='';const order=R.map((r,i)=>i);
 R.forEach((r,i)=>{const res=r.result;const d=document.createElement('div');d.className='run'+(i===sel?' sel':'');
  d.innerHTML=`<div class="top"><span class="dot" style="background:${r.color}"></span><span class="name">${r.label}</span><span class="res ${res.finished?'':'dnf'}">${res.finished?res.lap_time.toFixed(3)+'s':'DNF · '+res.reason}</span></div>
  <div class="stats" style="margin-top:4px"><div>Reward<b>${res.reward.toFixed(4)}</b></div><div>Top speed<b>${res.max_speed_kph.toFixed(0)}</b></div><div>Progress<b>${(res.progress*100).toFixed(1)}%</b></div></div>
  <div class="stats" id="live${i}"></div>`+(res.detail?`<div style="color:var(--muted);font-size:11px;margin-top:6px;white-space:pre-wrap;max-height:80px;overflow:auto">${res.detail.replace(/[<&]/g,c=>c=='<'?'&lt;':'&amp;')}</div>`:'');
  if(r.code||r.response){const b=document.createElement('button');b.className='codebtn';b.textContent='View code';b.onclick=e=>{e.stopPropagation();openCode(i,r.code?'code':'response');};d.appendChild(b);}
  d.onclick=()=>{sel=i;runsPanel();};el.appendChild(d);});}
let mrun=0,mview='code';
function openCode(i,view){mrun=i;mview=view;const r=R[i];document.getElementById('mdot').style.background=r.color;
 document.getElementById('mtitle').textContent=`${r.label} — ${r.result.finished?r.result.lap_time.toFixed(3)+'s':'DNF · '+r.result.reason}`;
 const txt=(view==='code'?r.code:r.response)||'(none)';const pre=document.getElementById('mpre');pre.innerHTML='';
 txt.split('\n').forEach(l=>{const s=document.createElement('span');s.textContent=l||' ';pre.appendChild(s);});
 document.getElementById('mcode').classList.toggle('on',view==='code');document.getElementById('mresp').classList.toggle('on',view!=='code');
 document.getElementById('mresp').style.display=r.response?'':'none';document.getElementById('modal').classList.add('open');pre.scrollTop=0;}
document.getElementById('mcode').onclick=()=>openCode(mrun,'code');document.getElementById('mresp').onclick=()=>openCode(mrun,'response');
document.getElementById('mclose').onclick=()=>document.getElementById('modal').classList.remove('open');
document.getElementById('modal').onclick=e=>{if(e.target.id==='modal')e.target.classList.remove('open');};
addEventListener('keydown',e=>{if(e.key==='Escape')document.getElementById('modal').classList.remove('open');});
document.getElementById('mcopy').onclick=e=>{const r=R[mrun];navigator.clipboard.writeText((mview==='code'?r.code:r.response)||'');e.target.textContent='Copied';setTimeout(()=>e.target.textContent='Copy',1200);};
const sp=document.getElementById('speeds');[1,2,5,10].forEach(v=>{const b=document.createElement('button');b.textContent=v+'×';b.onclick=()=>{rate=v;[...sp.children].forEach(c=>c.classList.toggle('on',c===b));};if(v===1)b.classList.add('on');sp.appendChild(b);});
document.getElementById('play').onclick=e=>{playing=!playing;e.target.textContent=playing?'Pause':'Play';if(playing&&t>=tmax)t=0;};
document.getElementById('scrub').oninput=e=>{t=e.target.value/1000*tmax;draw();};
let last=performance.now();function loop(now){const dt=(now-last)/1000;last=now;if(playing){t=Math.min(tmax,t+dt*rate);if(t>=tmax){playing=false;document.getElementById('play').textContent='Play';}}draw();requestAnimationFrame(loop);}
runsPanel();buildCorners();requestAnimationFrame(loop);addEventListener('resize',draw);
</script></body></html>"""

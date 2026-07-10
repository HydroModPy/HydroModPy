"""Interactive mesh-top depression map (HTML, opens in any browser).

    mamba activate hmp_refact
    python tools/diagnostics/cheze_interactive_mesh.py <solver_dir> [out.html]

Answers "does projecting the reworked DEM onto the DISV mesh create depressions?".
It loads the MODFLOW 6 model, takes each layer-0 cell TOP elevation (the elevation
carried by the mesh, not the raw raster), builds the Voronoi face adjacency
(cells sharing an edge), and for every active cell finds its steepest-descent
neighbour. Each cell is classified:

  * normal      -> an arrow to its lowest neighbour (water leaves the cell)
  * DEPRESSION  -> interior, non-lake, strictly lower than ALL its neighbours: a
                   pit the meshing introduced (RED, sized by how deep it sits below
                   the lowest neighbour = spill depth)
  * flat        -> a same-top neighbour exists (amber ring)
  * boundary    -> touches the inactive domain: drains off-grid (small blue dot)
  * lake bed    -> a lake cell that is a local minimum (expected, not a defect)

The HTML embeds every cell polygon (no server, no external file): a mesh you pan by
dragging and zoom with the wheel. Hover a cell for its top, class and spill depth.
The side panel lists the depressions by depth; click one to fly to it.
"""

import os
import sys
from collections import defaultdict

import flopy
import numpy as np

D = sys.argv[1]
OUT = (
    sys.argv[2]
    if len(sys.argv) > 2 and sys.argv[2].endswith(".html")
    else os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "examples",
        "projects",
        "19_cheze_reservoir",
        "figures",
        "cheze_75m",
        "mesh_depressions.html",
    )
)


def c2d(cid):
    return int(cid[1]) if isinstance(cid, (tuple, list, np.void)) else int(cid)


sim = flopy.mf6.MFSimulation.load(sim_ws=D, verbosity_level=0)
gwf = sim.get_model()
mg = gwf.modelgrid
ncpl = mg.ncpl
xc = np.asarray(mg.xcellcenters).reshape(-1)
yc = np.asarray(mg.ycellcenters).reshape(-1)
top = np.asarray(mg.top).reshape(-1)
iverts = mg.iverts
verts = np.asarray(mg.verts)
idom = np.asarray(mg.idomain)
il0 = idom[0].reshape(-1) if idom.ndim == 2 else idom.reshape(mg.nlay, -1)[0]
active = (il0 > 0) & np.isfinite(top) & (top > -1e3)

# Voronoi face adjacency: two cells sharing an edge (a vertex pair) are neighbours.
edge = defaultdict(list)
for i in range(ncpl):
    vs = [int(k) for k in iverts[i] if k is not None]
    for a in range(len(vs)):
        edge[tuple(sorted((vs[a], vs[(a + 1) % len(vs)])))].append(i)
adj = defaultdict(set)
for cells in edge.values():
    if len(cells) == 2:
        adj[cells[0]].add(cells[1])
        adj[cells[1]].add(cells[0])

lake_cells = {c2d(r["cellid"]) for r in gwf.get_package("lak").connectiondata.get_data()}

# classify + steepest-descent target
CLS_NORMAL, CLS_DEPR, CLS_FLAT, CLS_BOUND, CLS_LAKEBED = 0, 1, 2, 3, 4
cls = np.full(ncpl, -1, int)
tgt = np.full(ncpl, -1, int)
depth = np.zeros(ncpl, float)
for i in range(ncpl):
    if not active[i]:
        continue
    has_inactive = any(not active[j] for j in adj[i])
    best_j, best_slope, eq = -1, 0.0, False
    lowest_nb = np.inf
    for j in adj[i]:
        if not active[j]:
            continue
        lowest_nb = min(lowest_nb, top[j])
        dz = top[i] - top[j]
        if abs(dz) < 1e-6:
            eq = True
        elif dz > 0:
            dist = max(np.hypot(xc[i] - xc[j], yc[i] - yc[j]), 1.0)
            s = dz / dist
            if s > best_slope:
                best_slope, best_j = s, j
    if best_j >= 0:
        cls[i], tgt[i] = CLS_NORMAL, best_j
    elif eq:
        cls[i] = CLS_FLAT
    elif has_inactive:
        cls[i] = CLS_BOUND
    elif i in lake_cells:
        cls[i] = CLS_LAKEBED
    else:
        cls[i] = CLS_DEPR
        depth[i] = float(lowest_nb - top[i]) if np.isfinite(lowest_nb) else 0.0

n_depr = int((cls == CLS_DEPR).sum())
n_flat = int((cls == CLS_FLAT).sum())
n_bound = int((cls == CLS_BOUND).sum())
n_lakebed = int((cls == CLS_LAKEBED).sum())
print(f"cellules actives (couche 0) : {int(active.sum())}")
print(f"DEPRESSIONS interieures hors lac (creees par le passage altitude->mesh) : {n_depr}")
print(
    f"flats : {n_flat}   bord de domaine (drainent dehors) : {n_bound}   lits de lac (min) : {n_lakebed}"
)
_order = sorted((i for i in range(ncpl) if cls[i] == CLS_DEPR), key=lambda i: -depth[i])
for i in _order[:15]:
    print(f"   creux {depth[i]:.2f} m  cell {i}  X={xc[i]:.0f} Y={yc[i]:.0f} top={top[i]:.2f}")

# ---------------------------------------------------------------- colours (terrain by top)
import matplotlib

matplotlib.use("Agg")
from matplotlib import cm
from matplotlib.colors import Normalize

tvals = top[active]
vmin, vmax = float(np.percentile(tvals, 1)), float(np.percentile(tvals, 99))
norm = Normalize(vmin=vmin, vmax=vmax)
terr = cm.terrain


def hexcol(t):
    r, g, b, _ = terr(norm(t))
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


# ---------------------------------------------------------------- pack cells (compact verts)
vmap = {}
VX, VY = [], []


def vidx(k):
    if k not in vmap:
        vmap[k] = len(VX)
        VX.append(round(float(verts[k, 0]), 1))
        VY.append(round(float(verts[k, 1]), 1))
    return vmap[k]


cells = []
for i in range(ncpl):
    if not active[i]:
        continue
    poly = [vidx(int(k)) for k in iverts[i] if k is not None]
    rec = {
        "p": poly,
        "x": round(float(xc[i]), 1),
        "y": round(float(yc[i]), 1),
        "t": round(float(top[i]), 2),
        "c": hexcol(top[i]),
        "k": int(cls[i]),
        "lk": 1 if i in lake_cells else 0,
    }
    if cls[i] == CLS_NORMAL:
        rec["tx"] = round(float(xc[tgt[i]]), 1)
        rec["ty"] = round(float(yc[tgt[i]]), 1)
    if cls[i] == CLS_DEPR:
        rec["d"] = round(float(depth[i]), 2)
    cells.append(rec)

data = {
    "cells": cells,
    "vx": VX,
    "vy": VY,
    "xmin": float(np.min(VX)),
    "xmax": float(np.max(VX)),
    "ymin": float(np.min(VY)),
    "ymax": float(np.max(VY)),
    "n_active": int(active.sum()),
    "n_depr": n_depr,
    "n_flat": n_flat,
    "n_bound": n_bound,
    "vmin": round(vmin, 1),
    "vmax": round(vmax, 1),
}

HTML = (
    """<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cheze - depressions du mesh (top couche 0)</title>
<style>
  :root{--bg:#0f1115;--pan:#171a21;--ink:#e8eaed;--mut:#9aa3af;--line:#2a2f3a}
  *{box-sizing:border-box}
  html,body{margin:0;height:100%;background:var(--bg);color:var(--ink);
    font:14px/1.45 system-ui,Segoe UI,Roboto,sans-serif}
  #wrap{display:flex;height:100%}
  #cv{flex:1;display:block;cursor:grab;background:#0b0d11}
  #cv.grabbing{cursor:grabbing}
  #side{width:300px;flex:none;background:var(--pan);border-left:1px solid var(--line);
    padding:14px 16px;overflow:auto}
  h1{font-size:15px;margin:0 0 4px}
  .sub{color:var(--mut);font-size:12px;margin-bottom:12px}
  .kpi{display:flex;gap:8px;margin:10px 0}
  .card{flex:1;background:#0f1219;border:1px solid var(--line);border-radius:8px;padding:8px 6px;text-align:center}
  .card b{display:block;font-size:19px;line-height:1.1}
  .card.ok b{color:#34d399}.card.bad b{color:#f87171}.card span{font-size:10.5px;color:var(--mut)}
  .leg{margin:14px 0;border-top:1px solid var(--line);padding-top:12px}
  .leg div{display:flex;align-items:center;gap:8px;margin:6px 0;font-size:12.5px}
  .sw{width:20px;height:12px;border-radius:3px;flex:none}
  .arrowsw{width:20px;height:12px;flex:none;font-size:15px;text-align:center;line-height:12px}
  .btn{background:#1f2430;border:1px solid var(--line);color:var(--ink);border-radius:6px;
    padding:5px 10px;font-size:12px;cursor:pointer;margin-right:6px;margin-top:6px}
  #read{margin-top:12px;font-size:12px;background:#0f1219;border:1px solid var(--line);
    border-radius:8px;padding:8px 10px;min-height:64px;white-space:pre-line}
  #pits{margin-top:12px}
  #pits button{display:block;width:100%;text-align:left;background:#241318;color:#fca5a5;
    border:1px solid #7f1d1d;border-radius:6px;padding:5px 8px;margin:4px 0;font-size:11.5px;cursor:pointer}
  #hint{color:var(--mut);font-size:11.5px;margin-top:12px;border-top:1px solid var(--line);padding-top:10px}
  #tip{position:fixed;pointer-events:none;background:#0b0d11ee;border:1px solid var(--line);
    border-radius:6px;padding:6px 9px;font-size:12px;display:none;z-index:9;white-space:pre-line}
</style></head><body>
<div id="wrap">
  <canvas id="cv"></canvas>
  <div id="side">
    <h1>Depressions du mesh</h1>
    <div class="sub">Top de la couche 0 (altitude portee par les cellules DISV). Une fleche = ecoulement vers la cellule voisine la plus basse.</div>
    <div class="kpi">
      <div class="card"><b id="k_active">0</b><span>cellules</span></div>
      <div class="card" id="c_depr"><b id="k_depr">0</b><span>depressions</span></div>
      <div class="card"><b id="k_flat">0</b><span>plats</span></div>
    </div>
    <div class="leg">
      <div><span class="arrowsw">&#8594;</span> ecoulement vers la cellule voisine aval</div>
      <div><span class="sw" style="background:#e11d48"></span> DEPRESSION (creux cree par le mesh)</div>
      <div><span class="sw" style="background:#f59e0b"></span> cellule plate (top egal a un voisin)</div>
      <div><span class="sw" style="background:#38bdf8"></span> bord du domaine (draine dehors)</div>
      <div><span class="sw" style="background:#1d4ed8;opacity:.5"></span> cellule-lac</div>
    </div>
    <div>
      <button class="btn" id="fit">Recadrer</button>
      <button class="btn" id="toggleArrows">Fleches on/off</button>
    </div>
    <div id="read">Survole une cellule.</div>
    <div id="pits"></div>
    <div id="hint">Glisser = deplacer &middot; molette = zoom. Les fleches n'apparaissent qu'en zoomant.</div>
  </div>
</div>
<div id="tip"></div>
<script>
const D = __DATA__;
const cv=document.getElementById('cv'), ctx=cv.getContext('2d'), tip=document.getElementById('tip');
let showArrows=true;
document.getElementById('k_active').textContent=D.n_active;
document.getElementById('k_depr').textContent=D.n_depr;
document.getElementById('k_flat').textContent=D.n_flat;
document.getElementById('c_depr').classList.add(D.n_depr?'bad':'ok');

let scale=1, ox=0, oy=0;
function resize(){cv.width=cv.clientWidth*devicePixelRatio;cv.height=cv.clientHeight*devicePixelRatio;
  ctx.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0);}
// world -> screen (y flipped: north up)
const sx=(x)=>ox+(x-D.xmin)*scale, sy=(y)=>oy+(D.ymax-y)*scale;
function fit(){const w=cv.clientWidth,h=cv.clientHeight,pad=24;
  scale=Math.min((w-2*pad)/(D.xmax-D.xmin),(h-2*pad)/(D.ymax-D.ymin));
  ox=(w-(D.xmax-D.xmin)*scale)/2; oy=(h-(D.ymax-D.ymin)*scale)/2; draw();}

function draw(){
  const w=cv.clientWidth,h=cv.clientHeight; ctx.clearRect(0,0,w,h);
  const cellpx=scale*75, drawArrows=showArrows&&cellpx>10;
  // polygons
  for(const c of D.cells){
    const p=c.p; ctx.beginPath();
    ctx.moveTo(sx(D.vx[p[0]]),sy(D.vy[p[0]]));
    for(let a=1;a<p.length;a++) ctx.lineTo(sx(D.vx[p[a]]),sy(D.vy[p[a]]));
    ctx.closePath();
    ctx.fillStyle=c.lk?'#1e40af':c.c; ctx.fill();
    if(cellpx>4){ctx.lineWidth=0.35;ctx.strokeStyle='rgba(0,0,0,0.35)';ctx.stroke();}
  }
  // arrows (zoomed in only)
  if(drawArrows){
    ctx.strokeStyle='rgba(10,12,18,0.85)'; ctx.lineWidth=Math.max(0.7,cellpx*0.05);
    ctx.beginPath();
    for(const c of D.cells){
      if(c.k!==0) continue;
      const x=sx(c.x),y=sy(c.y);
      if(x<-20||y<-20||x>w+20||y>h+20) continue;
      let ex=sx(c.tx),ey=sy(c.ty);
      const dx=ex-x,dy=ey-y,L=Math.hypot(dx,dy)||1, f=Math.min(1,(cellpx*0.5)/L);
      ex=x+dx*f; ey=y+dy*f;
      const hd=Math.min(cellpx*0.2,5), a=Math.atan2(ey-y,ex-x);
      ctx.moveTo(x,y);ctx.lineTo(ex,ey);
      ctx.moveTo(ex,ey);ctx.lineTo(ex-hd*Math.cos(a-0.5),ey-hd*Math.sin(a-0.5));
      ctx.moveTo(ex,ey);ctx.lineTo(ex-hd*Math.cos(a+0.5),ey-hd*Math.sin(a+0.5));
    }
    ctx.stroke();
  }
  // markers
  for(const c of D.cells){
    const x=sx(c.x),y=sy(c.y);
    if(x<-10||y<-10||x>w+10||y>h+10) continue;
    if(c.k===2){ctx.strokeStyle='#f59e0b';ctx.lineWidth=1.3;
      ctx.beginPath();ctx.arc(x,y,Math.max(2.5,cellpx*0.22),0,7);ctx.stroke();}
    else if(c.k===3){ctx.fillStyle='#38bdf8';
      ctx.beginPath();ctx.arc(x,y,Math.max(1.6,cellpx*0.12),0,7);ctx.fill();}
    else if(c.k===1){
      const sz=Math.max(4,Math.min(cellpx*0.7,7+c.d*4));
      ctx.fillStyle='#e11d48';ctx.strokeStyle='#000';ctx.lineWidth=1.2;
      ctx.fillRect(x-sz/2,y-sz/2,sz,sz);ctx.strokeRect(x-sz/2,y-sz/2,sz,sz);
    }
  }
}

// nearest-centroid hover
function pick(px,py){
  let best=-1,bd=1e18;
  for(let i=0;i<D.cells.length;i++){
    const c=D.cells[i], dx=sx(c.x)-px, dy=sy(c.y)-py, d=dx*dx+dy*dy;
    if(d<bd){bd=d;best=i;}
  }
  return (bd < (scale*75*0.9)**2 || bd<400) ? best : -1;
}
const CL=['ecoule vers le voisin aval','DEPRESSION (creux du mesh)','PLAT (top egal a un voisin)',
  'bord du domaine (draine dehors)','lit de lac (minimum attendu)'];
function hover(e){
  const r=cv.getBoundingClientRect(), i=pick(e.clientX-r.left,e.clientY-r.top);
  if(i<0){tip.style.display='none';document.getElementById('read').textContent='Survole une cellule.';return;}
  const c=D.cells[i];
  let s=`X=${c.x.toFixed(0)}  Y=${c.y.toFixed(0)}\ntop = ${c.t} m\n${CL[c.k]}`;
  if(c.k===1) s+=`\ncreux = ${c.d} m sous le voisin le plus bas`;
  if(c.lk&&c.k!==4) s+=`\n(cellule-lac)`;
  document.getElementById('read').textContent=s;
  tip.textContent=s;tip.style.display='block';
  tip.style.left=(e.clientX+14)+'px';tip.style.top=(e.clientY+14)+'px';
}
cv.addEventListener('mouseleave',()=>{tip.style.display='none';});

let drag=null;
cv.addEventListener('mousedown',e=>{drag={x:e.clientX,y:e.clientY,ox,oy};cv.classList.add('grabbing');});
window.addEventListener('mouseup',()=>{drag=null;cv.classList.remove('grabbing');});
window.addEventListener('mousemove',e=>{
  if(drag){ox=drag.ox+(e.clientX-drag.x);oy=drag.oy+(e.clientY-drag.y);draw();return;}
  hover(e);
});
cv.addEventListener('wheel',e=>{
  e.preventDefault();
  const r=cv.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;
  const f=Math.exp(-e.deltaY*0.0012), wx=(mx-ox)/scale+D.xmin, wy=D.ymax-(my-oy)/scale;
  scale*=f; ox=mx-(wx-D.xmin)*scale; oy=my-(D.ymax-wy)*scale; draw();
},{passive:false});

// depression list (deepest first)
const pl=document.getElementById('pits');
const dl=D.cells.filter(c=>c.k===1).sort((a,b)=>b.d-a.d);
if(dl.length===0){
  const ok=document.createElement('div');
  ok.style.cssText='color:#34d399;font-size:12px;background:#0c1f16;border:1px solid #14532d;border-radius:8px;padding:8px 10px';
  ok.textContent='Aucune depression interieure : le mesh porte une surface qui s ecoule partout.';
  pl.appendChild(ok);
}
for(const c of dl){
  const b=document.createElement('button');
  b.textContent=`creux ${c.d} m  X=${c.x.toFixed(0)} Y=${c.y.toFixed(0)} (top ${c.t})`;
  b.onclick=()=>{scale=Math.max(scale,3.2);
    ox=cv.clientWidth/2-(c.x-D.xmin)*scale; oy=cv.clientHeight/2-(D.ymax-c.y)*scale; draw();};
  pl.appendChild(b);
}

document.getElementById('fit').onclick=fit;
document.getElementById('toggleArrows').onclick=()=>{showArrows=!showArrows;draw();};
window.addEventListener('resize',()=>{resize();draw();});
resize(); fit();
</script></body></html>"""
).replace("__DATA__", __import__("json").dumps(data))

os.makedirs(os.path.dirname(os.path.abspath(OUT)), exist_ok=True)
with open(OUT, "w") as f:
    f.write(HTML)
print("HTML ecrit :", os.path.abspath(OUT))
print("Ouvre-le dans un navigateur (double-clic). Aucun serveur requis.")

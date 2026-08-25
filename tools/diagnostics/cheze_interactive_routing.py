"""Interactive routing map (self-contained HTML, opens in any browser, no server).

    mamba activate hmp_refact
    python tools/diagnostics/cheze_interactive_routing.py <solver_dir> [out.html]

Zoomable pan/drag map of the Cheze two-lake model built from the kept MF6 files.
Every layer-0 cell is coloured by its role and carries a flow arrow to the
neighbour its water leaves towards (steepest descent on the conditioned mesh top,
the same single-flow-direction the topographic DRN router follows):

  * LAK cells         reservoir (blue) / pre-retenue (orange)
  * SFR reach cells    the one-cell-wide stream network (dark blue)
  * DRN cells          coloured by the water body they drain to via MVR:
                       -> reservoir, -> pre-retenue, -> a SFR reach, or buffer (out)
  * red stars          SFR -> lake entries (where a stream feeds a lake)

Drag to pan, wheel to zoom, hover a cell for its role / target / top. Arrows show
up when you zoom in.
"""

import json
import os
import sys
from collections import defaultdict

import flopy
import numpy as np

from hydromodpy.spatial.mesh.ops.mesh_flow import steepest_descent_receiver

D = sys.argv[1]
OUT = (
    sys.argv[2]
    if len(sys.argv) > 2 and sys.argv[2].endswith(".html")
    else os.path.join(
        os.path.dirname(os.path.abspath(D)), "..", "figures", "cheze_routing_interactive.html"
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
il0 = idom.reshape(mg.nlay, -1)[0]
active = (il0 > 0) & np.isfinite(top) & (top > -1e3)

# face adjacency (shared edge) for the steepest-descent flow direction
edge = defaultdict(list)
for i in range(ncpl):
    vs = [int(k) for k in iverts[i] if k is not None]
    for a in range(len(vs)):
        edge[tuple(sorted((vs[a], vs[(a + 1) % len(vs)])))].append(i)
adj = defaultdict(set)
for cc in edge.values():
    if len(cc) == 2:
        adj[cc[0]].add(cc[1])
        adj[cc[1]].add(cc[0])

lak = gwf.get_package("lak")
names = {int(r["ifno"]): str(r["boundname"]) for r in lak.packagedata.array}
lake_of_cell = {}
for r in lak.connectiondata.array:
    lake_of_cell.setdefault(c2d(r["cellid"]), int(r["ifno"]))
lake_cells = set(lake_of_cell)
pre_lid = next(li for li, nm in names.items() if "preret" in nm.lower())
res_lid = next(li for li, nm in names.items() if "reserv" in nm.lower())

# Lake-bed cells are inactive in the aquifer (idomain <= 0) but are still part of the
# lake body: draw them as the lake so the lake reads as a filled water body, not an
# empty (background-coloured) hole.
is_lake = np.array([i in lake_cells for i in range(ncpl)])
drawn = active | is_lake

sfr = gwf.get_package("sfr")
reach_cell = {int(r["ifno"]): c2d(r["cellid"]) for r in sfr.packagedata.array}
sfr_cells = set(reach_cell.values())

drn = [c2d(r["cellid"]) for r in gwf.get_package("drn").stress_period_data.get_data(0)]
mvr = gwf.get_package("mvr").perioddata.get_data(0)
drn2lak, drn2sfr, sfr2lak, lak2sfr = {}, set(), [], []
for r in mvr:
    p1, i1, p2, i2 = str(r["pname1"]), int(r["id1"]), str(r["pname2"]), int(r["id2"])
    if p1 == "drn" and p2 == "lak":
        drn2lak[drn[i1]] = i2
    elif p1 == "drn" and p2 == "sfr":
        drn2sfr.add(drn[i1])
    elif p1 == "sfr" and p2 == "lak":
        sfr2lak.append((i1, i2))
    elif p1 == "lak" and p2 == "sfr":
        lak2sfr.append((i1, i2))  # spillway release: LAK outlet -> downstream reach

# role per cell
# 0 LAK reservoir, 1 LAK pre-retenue, 2 SFR, 3 DRN->reservoir, 4 DRN->pre-retenue,
# 5 DRN->SFR, 6 DRN buffer/out, 7 other active
ROLE_LABELS = [
    "lac reservoir",
    "lac pre-retenue",
    "cellule SFR (ruisseau)",
    "DRN -> reservoir",
    "DRN -> pre-retenue",
    "DRN -> ruisseau SFR",
    "DRN -> hors bassin (buffer)",
    "cellule active",
]
drn_set = set(drn)
role = np.full(ncpl, 7, int)
for i in range(ncpl):
    if not drawn[i]:
        role[i] = -1
        continue
    if i in lake_cells:
        role[i] = 0 if lake_of_cell[i] == res_lid else 1
    elif i in sfr_cells:
        role[i] = 2
    elif i in drn_set:
        if drn2lak.get(i) == res_lid:
            role[i] = 3
        elif drn2lak.get(i) == pre_lid:
            role[i] = 4
        elif i in drn2sfr:
            role[i] = 5
        else:
            role[i] = 6

# steepest-descent flow target per active non-lake cell (the physical flow direction),
# using the shared solver-agnostic primitive instead of a local copy of the algorithm.
flow_active = active & ~is_lake
tgt = steepest_descent_receiver(
    top, [adj[i] for i in range(ncpl)], np.column_stack([xc, yc]), active=flow_active
)

# LAK outlets = the weirs. The external spillway (lakeout < 0) is drawn where it
# discharges: on the reservoir shoreline nearest the reach its LAK -> SFR mover feeds
# (or, with no mover, the lowest shoreline cell = the natural spill point). The
# reciprocal lake<->lake sill is at the closest cross-lake pair (drawn once). No
# hard-coded outlet coordinate: everything is derived from the built model.
lak2sfr_reach_cell = {oid: reach_cell[rid] for oid, rid in lak2sfr if rid in reach_cell}
cells_by_lid = defaultdict(list)
for cell_id, lid in lake_of_cell.items():
    cells_by_lid[lid].append(cell_id)
weirs = []
weir_xy_by_outletno = {}
try:
    outlets = lak.outlets.array
except (AttributeError, TypeError):
    outlets = None
seen_pairs = set()
for r in outlets if outlets is not None else []:
    lin, lout, invert = int(r["lakein"]), int(r["lakeout"]), float(r["invert"])
    if lout < 0:
        cand = cells_by_lid.get(lin, [])
        if not cand:
            continue
        target = lak2sfr_reach_cell.get(int(r["outletno"]))
        if target is not None:
            cell = min(cand, key=lambda c: np.hypot(xc[c] - xc[target], yc[c] - yc[target]))
        else:
            cell = min(cand, key=lambda c: float(top[c]))
        wx, wy = round(float(xc[cell]), 1), round(float(yc[cell]), 1)
        weir_xy_by_outletno[int(r["outletno"])] = (wx, wy)
        weirs.append(
            {"x": wx, "y": wy, "label": f"deversoir {names[lin]} -> aval (seuil {invert:.2f} m)"}
        )
    else:
        key = tuple(sorted((lin, lout)))
        a, b = cells_by_lid.get(lin, []), cells_by_lid.get(lout, [])
        if key in seen_pairs or not a or not b:
            continue
        seen_pairs.add(key)
        ca, cb = min(
            ((p, q) for p in a for q in b),
            key=lambda pq: np.hypot(xc[pq[0]] - xc[pq[1]], yc[pq[0]] - yc[pq[1]]),
        )
        weirs.append(
            {
                "x": round(0.5 * float(xc[ca] + xc[cb]), 1),
                "y": round(0.5 * float(yc[ca] + yc[cb]), 1),
                "label": f"seuil {names[lin]} <-> {names[lout]} ({invert:.2f} m)",
            }
        )

# Spillway release links: a line from the LAK spillway weir to the reach it feeds.
spill_links = []
for oid, rid in lak2sfr:
    src = weir_xy_by_outletno.get(oid)
    cell = reach_cell.get(rid)
    if src is not None and cell is not None:
        spill_links.append(
            {
                "x1": src[0],
                "y1": src[1],
                "x2": round(float(xc[cell]), 1),
                "y2": round(float(yc[cell]), 1),
            }
        )

counts = {int(k): int((role == k).sum()) for k in range(8)}
print("roles:", {ROLE_LABELS[k]: counts[k] for k in range(8)})
print("SFR -> lake feeders:", [(ri, names[li]) for ri, li in sfr2lak])
print("weirs:", [w["label"] for w in weirs])
print("LAK -> SFR spillway links:", len(spill_links))

COLORS = ["#2563eb", "#ea8c00", "#0b2f6b", "#9ecae1", "#f6c37a", "#3fb59a", "#6b7280", "#3a3f4b"]

vmap: dict[int, int] = {}
VX: list[float] = []
VY: list[float] = []


def vidx(k: int) -> int:
    if k not in vmap:
        vmap[k] = len(VX)
        VX.append(round(float(verts[k, 0]), 1))
        VY.append(round(float(verts[k, 1]), 1))
    return vmap[k]


cells = []
for i in range(ncpl):
    if not drawn[i]:
        continue
    rec = {
        "p": [vidx(int(k)) for k in iverts[i] if k is not None],
        "x": round(float(xc[i]), 1),
        "y": round(float(yc[i]), 1),
        "t": round(float(top[i]), 2),
        "r": int(role[i]),
    }
    if tgt[i] >= 0:
        rec["tx"] = round(float(xc[tgt[i]]), 1)
        rec["ty"] = round(float(yc[tgt[i]]), 1)
    cells.append(rec)

feeders = []
for ri, li in sfr2lak:
    cell = reach_cell.get(ri)
    if cell is not None:
        feeders.append(
            {"x": round(float(xc[cell]), 1), "y": round(float(yc[cell]), 1), "lake": names[li]}
        )

data = {
    "cells": cells,
    "vx": VX,
    "vy": VY,
    "feeders": feeders,
    "weirs": weirs,
    "spillLinks": spill_links,
    "colors": COLORS,
    "labels": ROLE_LABELS,
    "counts": counts,
    "xmin": float(np.min(VX)),
    "xmax": float(np.max(VX)),
    "ymin": float(np.min(VY)),
    "ymax": float(np.max(VY)),
}

HTML = r"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cheze - routage (flux, SFR, LAK, entrees)</title>
<style>
  :root{--bg:#0f1115;--pan:#171a21;--ink:#e8eaed;--mut:#9aa3af;--line:#2a2f3a}
  *{box-sizing:border-box}
  html,body{margin:0;height:100%;background:var(--bg);color:var(--ink);
    font:14px/1.45 system-ui,Segoe UI,Roboto,sans-serif}
  #wrap{display:flex;height:100%}
  #cv{flex:1;display:block;cursor:grab;background:#0b0d11}
  #cv.grabbing{cursor:grabbing}
  #side{width:310px;flex:none;background:var(--pan);border-left:1px solid var(--line);
    padding:14px 16px;overflow:auto}
  h1{font-size:15px;margin:0 0 4px}
  .sub{color:var(--mut);font-size:12px;margin-bottom:10px}
  .leg{margin:12px 0;border-top:1px solid var(--line);padding-top:10px}
  .leg div{display:flex;align-items:center;gap:8px;margin:5px 0;font-size:12.5px}
  .sw{width:18px;height:12px;border-radius:3px;flex:none}
  .star{color:#ef4444;font-size:15px;width:18px;text-align:center;flex:none}
  .arrowsw{width:18px;text-align:center;font-size:15px;flex:none}
  .btn{background:#1f2430;border:1px solid var(--line);color:var(--ink);border-radius:6px;
    padding:5px 10px;font-size:12px;cursor:pointer;margin:6px 6px 0 0}
  #read{margin-top:12px;font-size:12px;background:#0f1219;border:1px solid var(--line);
    border-radius:8px;padding:8px 10px;min-height:56px;white-space:pre-line}
  #hint{color:var(--mut);font-size:11.5px;margin-top:12px;border-top:1px solid var(--line);padding-top:10px}
  #tip{position:fixed;pointer-events:none;background:#0b0d11ee;border:1px solid var(--line);
    border-radius:6px;padding:6px 9px;font-size:12px;display:none;z-index:9;white-space:pre-line}
</style></head><body>
<div id="wrap">
  <canvas id="cv"></canvas>
  <div id="side">
    <h1>Routage Cheze</h1>
    <div class="sub">Chaque cellule est coloree par son role et porte une fleche vers la cellule ou son eau part (plus forte pente sur le top conditionne). Les etoiles rouges = entrees d'un ruisseau dans un lac.</div>
    <div class="leg" id="leg"></div>
    <div class="leg">
      <div><span class="arrowsw">&#8594;</span> direction du flux (par cellule)</div>
      <div><span class="star">&#9733;</span> entree SFR -&gt; lac</div>
      <div><span class="arrowsw" style="color:#22d3ee">&#9670;</span> deversoir / seuil (LAK outlet)</div>
      <div><span class="arrowsw" style="color:#22d3ee">&#8674;</span> trop-plein LAK -&gt; SFR aval</div>
    </div>
    <div>
      <button class="btn" id="fit">Recadrer</button>
      <button class="btn" id="toggleArrows">Fleches on/off</button>
    </div>
    <div id="read">Survole une cellule.</div>
    <div id="hint">Glisser = deplacer &middot; molette = zoom. Les fleches apparaissent en zoomant.</div>
  </div>
</div>
<div id="tip"></div>
<script>
const D = __DATA__;
const cv=document.getElementById('cv'), ctx=cv.getContext('2d'), tip=document.getElementById('tip');
let showArrows=true;
// legend
const leg=document.getElementById('leg');
for(let k=0;k<D.labels.length;k++){
  if(!D.counts[k]) continue;
  const d=document.createElement('div');
  d.innerHTML=`<span class="sw" style="background:${D.colors[k]}"></span> ${D.labels[k]} (${D.counts[k]})`;
  leg.appendChild(d);
}
let scale=1, ox=0, oy=0;
function resize(){cv.width=cv.clientWidth*devicePixelRatio;cv.height=cv.clientHeight*devicePixelRatio;
  ctx.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0);}
const sx=(x)=>ox+(x-D.xmin)*scale, sy=(y)=>oy+(D.ymax-y)*scale;
function fit(){const w=cv.clientWidth,h=cv.clientHeight,pad=24;
  scale=Math.min((w-2*pad)/(D.xmax-D.xmin),(h-2*pad)/(D.ymax-D.ymin));
  ox=(w-(D.xmax-D.xmin)*scale)/2; oy=(h-(D.ymax-D.ymin)*scale)/2; draw();}
function draw(){
  const w=cv.clientWidth,h=cv.clientHeight; ctx.clearRect(0,0,w,h);
  const cellpx=scale*75, drawArrows=showArrows&&cellpx>9;
  for(const c of D.cells){
    const p=c.p; ctx.beginPath();
    ctx.moveTo(sx(D.vx[p[0]]),sy(D.vy[p[0]]));
    for(let a=1;a<p.length;a++) ctx.lineTo(sx(D.vx[p[a]]),sy(D.vy[p[a]]));
    ctx.closePath();
    ctx.fillStyle=D.colors[c.r]; ctx.fill();
    if(cellpx>4){ctx.lineWidth=0.3;ctx.strokeStyle='rgba(0,0,0,0.35)';ctx.stroke();}
  }
  if(drawArrows){
    ctx.strokeStyle='rgba(230,233,238,0.9)'; ctx.lineWidth=Math.max(0.6,cellpx*0.045);
    ctx.beginPath();
    for(const c of D.cells){
      if(c.tx===undefined) continue;
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
  // SFR -> lake entries
  const sr=Math.max(4,Math.min(cellpx*0.6,11));
  for(const fdr of D.feeders){
    const x=sx(fdr.x),y=sy(fdr.y);
    ctx.fillStyle='#ef4444';ctx.strokeStyle='#000';ctx.lineWidth=1;
    ctx.beginPath();
    for(let a=0;a<5;a++){const ang=-Math.PI/2+a*4*Math.PI/5;
      const px=x+sr*Math.cos(ang),py=y+sr*Math.sin(ang); a?ctx.lineTo(px,py):ctx.moveTo(px,py);}
    ctx.closePath();ctx.fill();ctx.stroke();
  }
  // spillway release links: dashed cyan line from the weir to the reach it feeds
  if(D.spillLinks && D.spillLinks.length){
    ctx.strokeStyle='#22d3ee';ctx.lineWidth=Math.max(1.2,cellpx*0.06);ctx.setLineDash([8,5]);
    for(const s of D.spillLinks){
      const x1=sx(s.x1),y1=sy(s.y1),x2=sx(s.x2),y2=sy(s.y2);
      ctx.beginPath();ctx.moveTo(x1,y1);ctx.lineTo(x2,y2);ctx.stroke();
      const a=Math.atan2(y2-y1,x2-x1),hd=Math.max(6,cellpx*0.25);
      ctx.beginPath();ctx.moveTo(x2,y2);
      ctx.lineTo(x2-hd*Math.cos(a-0.4),y2-hd*Math.sin(a-0.4));
      ctx.moveTo(x2,y2);ctx.lineTo(x2-hd*Math.cos(a+0.4),y2-hd*Math.sin(a+0.4));ctx.stroke();
    }
    ctx.setLineDash([]);
  }
  // weirs / spillways (LAK outlets): cyan diamond + label
  const wr=Math.max(5,Math.min(cellpx*0.7,13));
  for(const wv of D.weirs){
    const x=sx(wv.x),y=sy(wv.y);
    ctx.fillStyle='#22d3ee';ctx.strokeStyle='#083344';ctx.lineWidth=1.5;
    ctx.beginPath();
    ctx.moveTo(x,y-wr);ctx.lineTo(x+wr,y);ctx.lineTo(x,y+wr);ctx.lineTo(x-wr,y);
    ctx.closePath();ctx.fill();ctx.stroke();
    if(cellpx>7){ctx.fillStyle='#a5f3fc';ctx.font='11px system-ui';ctx.textAlign='left';
      ctx.fillText(wv.label,x+wr+3,y+4);}
  }
}
function pick(px,py){let best=-1,bd=1e18;
  for(let i=0;i<D.cells.length;i++){const c=D.cells[i],dx=sx(c.x)-px,dy=sy(c.y)-py,d=dx*dx+dy*dy;
    if(d<bd){bd=d;best=i;}}
  return (bd<(scale*75*0.9)**2||bd<400)?best:-1;}
function hover(e){
  const r=cv.getBoundingClientRect(), i=pick(e.clientX-r.left,e.clientY-r.top);
  if(i<0){tip.style.display='none';document.getElementById('read').textContent='Survole une cellule.';return;}
  const c=D.cells[i];
  const s=`X=${c.x.toFixed(0)}  Y=${c.y.toFixed(0)}\ntop = ${c.t} m\n${D.labels[c.r]}`;
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
  hover(e);});
cv.addEventListener('wheel',e=>{
  e.preventDefault();
  const r=cv.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;
  const f=Math.exp(-e.deltaY*0.0012), wx=(mx-ox)/scale+D.xmin, wy=D.ymax-(my-oy)/scale;
  scale*=f; ox=mx-(wx-D.xmin)*scale; oy=my-(D.ymax-wy)*scale; draw();
},{passive:false});
document.getElementById('fit').onclick=fit;
document.getElementById('toggleArrows').onclick=()=>{showArrows=!showArrows;draw();};
window.addEventListener('resize',()=>{resize();draw();});
resize(); fit();
</script></body></html>""".replace("__DATA__", json.dumps(data))

os.makedirs(os.path.dirname(os.path.abspath(OUT)), exist_ok=True)
with open(OUT, "w") as fh:
    fh.write(HTML)
print("HTML ecrit :", os.path.abspath(OUT))

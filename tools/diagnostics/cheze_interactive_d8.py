"""Build a self-contained interactive D8 flow map (HTML, opens in any browser).

    mamba activate hmp_refact
    python tools/diagnostics/cheze_interactive_d8.py <routing_dem> [out.html] [x_outlet y_outlet]

`routing_dem` is the enforced routing DEM the delineation runs on. Accept either
a GeoTIFF or a zarr `geographic/` group directory (reads its `watershed_dem`
array + transform/crs/nodata attrs). The tool recomputes the D8 steepest-descent
direction of every cell and classifies each one:

  * normal  -> an arrow pointing to its downstream (lowest) neighbour
  * flat    -> a same-elevation neighbour exists, water still moves (amber ring)
  * pit     -> ALL neighbours are strictly higher: a closed depression / cuvette
              that traps water before the outlet (red square)

The single global-minimum cell is the basin outlet, drawn as a magenta diamond
(not a cuvette). Any OTHER red square is a real cuvette to worry about.

The output HTML embeds all cell data (no server, no external file): a shaded-relief
canvas you pan by dragging and zoom with the wheel. Arrows and pits stay crisp at
any zoom; hover a cell to read its coordinates, elevation and flow direction.
"""

import json
import os
import sys

import numpy as np

# ---------------------------------------------------------------- inputs
DEM = sys.argv[1]
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
        "d8_interactive.html",
    )
)
_rest = [a for a in sys.argv[3:] if not a.endswith(".html")]
XO = float(_rest[0]) if len(_rest) > 0 else None
YO = float(_rest[1]) if len(_rest) > 1 else None


def load_dem(path):
    """Return (z float array, cellsize, x_west, y_north, nodata) from tif or zarr."""
    if path.endswith(".tif") or path.endswith(".tiff"):
        import rasterio

        with rasterio.open(path) as s:
            z = s.read(1).astype(float)
            tr = s.transform
            return z, abs(tr.a), tr.c, tr.f, s.nodata
    # zarr geographic group -> watershed_dem
    import zarr

    g = zarr.open_group(path, mode="r")
    a = g["watershed_dem"]
    z = np.asarray(a[:], dtype=float)
    t = list(a.attrs["transform"])  # [a, b, c, d, e, f]
    return z, abs(t[0]), t[2], t[5], a.attrs.get("nodata", -9999.0)


def load_fill(path):
    """Load the pipeline's depression-filled DEM (zarr `watershed_fill`), or None."""
    if path.endswith(".tif") or path.endswith(".tiff"):
        return None
    try:
        import zarr

        a = zarr.open_group(path, mode="r")["watershed_fill"]
        t = list(a.attrs["transform"])
        return np.asarray(a[:], float), abs(t[0]), t[2], t[5], a.attrs.get("nodata", -99999.0)
    except Exception:
        return None


z, cs, x0, y0, nod = load_dem(DEM)
nrow, ncol = z.shape
valid = np.isfinite(z) & (z != nod) & (z > -1e4)

# depression-filled DEM = what the pipeline actually routes on. A raw-DEM pit that is
# still a pit here would trap water in the model (RED). One resolved by the fill is
# harmless DEM noise (amber). Cross-referenced by world coordinates (both 75m aligned).
_fill = load_fill(DEM)
fill_pit = None
if _fill is not None:
    zf, csf, x0f, y0f, nodf = _fill
    vf = np.isfinite(zf) & (zf != nodf) & (zf > -1e4)
    nrf, ncf = zf.shape
    fill_pit = np.zeros_like(zf, bool)
    for r in range(nrf):
        for c in range(ncf):
            if not vf[r, c]:
                continue
            # trap = strict local minimum: no neighbour is lower OR equal. A filled
            # depression becomes a flat plateau (equal neighbours) that still spills
            # to the outlet, so an equal neighbour means "not a trap".
            escape = False
            for dc, dr in [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]:
                rr, cc = r + dr, c + dc
                if 0 <= rr < nrf and 0 <= cc < ncf and vf[rr, cc] and zf[r, c] - zf[rr, cc] > -1e-6:
                    escape = True
                    break
            fill_pit[r, c] = not escape


def persists_after_fill(r, c):
    """True if the raw-DEM pit at (r,c) is still a pit on the filled DEM."""
    if fill_pit is None:
        return True
    wx, wy = x0 + (c + 0.5) * cs, y0 - (r + 0.5) * cs
    cf = int(round((wx - x0f) / csf - 0.5))
    rf = int(round((y0f - wy) / csf - 0.5))
    if 0 <= rf < fill_pit.shape[0] and 0 <= cf < fill_pit.shape[1]:
        return bool(fill_pit[rf, cf])
    return True


# ---------------------------------------------------------------- D8 steepest descent
# 8 neighbours, clockwise from East. (dcol, drow); drow>0 goes south (down a row).
NB = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
DIAG = [False, True, False, True, False, True, False, True]

direction = np.full((nrow, ncol), -9, dtype=int)  # 0..7 arrow, -1 pit, -2 flat
for r in range(nrow):
    for c in range(ncol):
        if not valid[r, c]:
            continue
        zc = z[r, c]
        best_i, best_slope, has_equal = -1, 0.0, False
        for i, (dc, dr) in enumerate(NB):
            rr, cc = r + dr, c + dc
            if rr < 0 or rr >= nrow or cc < 0 or cc >= ncol or not valid[rr, cc]:
                continue
            dz = zc - z[rr, cc]
            if abs(dz) < 1e-6:
                has_equal = True
                continue
            if dz > 0:
                dist = cs * (2**0.5 if DIAG[i] else 1.0)
                slope = dz / dist
                if slope > best_slope:
                    best_slope, best_i = slope, i
        if best_i >= 0:
            direction[r, c] = best_i
        elif has_equal:
            direction[r, c] = -2  # flat
        else:
            direction[r, c] = -1  # pit / cuvette

# outlet = global minimum valid cell (drains out of the clipped basin)
zv = np.where(valid, z, np.inf)
orow, ocol = np.unravel_index(int(np.argmin(zv)), zv.shape)
outlet_idx = orow * ncol + ocol

# Reclassify raw pits: -1 = survives the fill (real trap, red), -3 = filled away (amber).
# The outlet is the global minimum; it reads as a pit but is the basin exit, not a cuvette.
real_pits, filled_pits = [], []
for r in range(nrow):
    for c in range(ncol):
        if direction[r, c] != -1 or (r, c) == (orow, ocol):
            continue
        if persists_after_fill(r, c):
            real_pits.append((r, c))
        else:
            direction[r, c] = -3
            filled_pits.append((r, c))
flat_cells = [(r, c) for r in range(nrow) for c in range(ncol) if direction[r, c] == -2]
n_valid = int(valid.sum())
print(f"cellules valides dans le bassin : {n_valid}")
print(f"CUVETTES REELLES (survivent au fill du pipeline) : {len(real_pits)}")
print(f"depressions ponctuelles du DEM brut, comblees par le fill : {len(filled_pits)}")
print(f"cellules plates (flat) : {len(flat_cells)}")
print(f"exutoire (cellule la plus basse) : cellule ({orow},{ocol})")
for r, c in real_pits[:20]:
    cx, cy = x0 + (c + 0.5) * cs, y0 - (r + 0.5) * cs
    print(f"   CUVETTE reelle a X={cx:.0f} Y={cy:.0f} z={z[r, c]:.2f} m")

# ---------------------------------------------------------------- shaded-relief colours
import matplotlib

matplotlib.use("Agg")
from matplotlib import cm
from matplotlib.colors import LightSource, Normalize

zmasked = np.ma.masked_where(~valid, z)
vmin, vmax = float(z[valid].min()), float(z[valid].max())
ls = LightSource(azdeg=315, altdeg=45)
rgb = ls.shade(
    zmasked,
    cmap=cm.terrain,
    norm=Normalize(vmin=vmin, vmax=vmax),
    vert_exag=4.0,
    blend_mode="soft",
)  # (nrow, ncol, 4)

# ---------------------------------------------------------------- pack cells for JS
col_a, row_a, dir_a, z_a, hex_a = [], [], [], [], []
for r in range(nrow):
    for c in range(ncol):
        if not valid[r, c]:
            continue
        col_a.append(c)
        row_a.append(r)
        dir_a.append(int(direction[r, c]))
        z_a.append(round(float(z[r, c]), 2))
        rr, gg, bb, _ = rgb[r, c]
        hex_a.append(f"#{int(rr * 255):02x}{int(gg * 255):02x}{int(bb * 255):02x}")

data = {
    "ncol": ncol,
    "nrow": nrow,
    "cs": cs,
    "x0": x0,
    "y0": y0,
    "vmin": round(vmin, 1),
    "vmax": round(vmax, 1),
    "outlet": outlet_idx,
    "orow": int(orow),
    "ocol": int(ocol),
    "xo_cfg": XO,
    "yo_cfg": YO,
    "nb": NB,
    "col": col_a,
    "row": row_a,
    "dir": dir_a,
    "z": z_a,
    "rgb": hex_a,
    "n_pit": len(real_pits),
    "n_filled": len(filled_pits),
    "n_flat": len(flat_cells),
    "n_valid": n_valid,
    "has_fill": fill_pit is not None,
}

HTML = (
    """<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cheze - ecoulement gravitaire D8 (interactif)</title>
<style>
  :root{--bg:#0f1115;--pan:#171a21;--ink:#e8eaed;--mut:#9aa3af;--line:#2a2f3a}
  *{box-sizing:border-box}
  html,body{margin:0;height:100%;background:var(--bg);color:var(--ink);
    font:14px/1.45 system-ui,Segoe UI,Roboto,sans-serif}
  #wrap{display:flex;height:100%}
  #cv{flex:1;display:block;cursor:grab;background:#0b0d11}
  #cv.grabbing{cursor:grabbing}
  #side{width:290px;flex:none;background:var(--pan);border-left:1px solid var(--line);
    padding:14px 16px;overflow:auto}
  h1{font-size:15px;margin:0 0 4px}
  .sub{color:var(--mut);font-size:12px;margin-bottom:12px}
  .kpi{display:flex;gap:8px;margin:10px 0}
  .card{flex:1;background:#0f1219;border:1px solid var(--line);border-radius:8px;padding:8px 6px;text-align:center}
  .card b{display:block;font-size:19px;line-height:1.1}
  .card.ok b{color:#34d399}.card.bad b{color:#f87171}.card span{font-size:10.5px;color:var(--mut)}
  .leg{margin:14px 0;border-top:1px solid var(--line);padding-top:12px}
  .leg div{display:flex;align-items:center;gap:8px;margin:6px 0;font-size:12.5px}
  .sw{width:22px;height:12px;border-radius:3px;flex:none}
  .arrowsw{width:22px;height:12px;flex:none;color:#e8eaed;font-size:15px;text-align:center;line-height:12px}
  #hint{color:var(--mut);font-size:11.5px;margin-top:12px;border-top:1px solid var(--line);padding-top:10px}
  #read{margin-top:12px;font-size:12px;background:#0f1219;border:1px solid var(--line);
    border-radius:8px;padding:8px 10px;min-height:70px;white-space:pre-line}
  #pits{margin-top:12px}
  #pits button{display:block;width:100%;text-align:left;background:#241318;color:#fca5a5;
    border:1px solid #7f1d1d;border-radius:6px;padding:5px 8px;margin:4px 0;font-size:11.5px;cursor:pointer}
  #tip{position:fixed;pointer-events:none;background:#0b0d11ee;border:1px solid var(--line);
    border-radius:6px;padding:6px 9px;font-size:12px;display:none;z-index:9;white-space:pre-line}
  .btn{background:#1f2430;border:1px solid var(--line);color:var(--ink);border-radius:6px;
    padding:5px 10px;font-size:12px;cursor:pointer;margin-right:6px;margin-top:6px}
</style></head><body>
<div id="wrap">
  <canvas id="cv"></canvas>
  <div id="side">
    <h1>Ecoulement gravitaire (D8)</h1>
    <div class="sub">DEM de routage enforced du bassin de la Cheze. Une fleche par cellule vers son voisin aval.</div>
    <div class="kpi">
      <div class="card"><b id="k_valid">0</b><span>cellules</span></div>
      <div class="card" id="c_pit"><b id="k_pit">0</b><span>cuvettes reelles</span></div>
      <div class="card"><b id="k_filled">0</b><span>comblees fill</span></div>
    </div>
    <div class="leg">
      <div><span class="arrowsw">&#8594;</span> ecoulement vers la cellule aval</div>
      <div><span class="sw" style="background:#e11d48"></span> CUVETTE reelle (survit au fill, piege l'eau)</div>
      <div><span class="sw" style="background:#f59e0b"></span> depression du DEM brut, comblee par le fill</div>
      <div><span class="sw" style="background:#d946ef"></span> exutoire du bassin (point le plus bas)</div>
    </div>
    <div>
      <button class="btn" id="fit">Recadrer</button>
      <button class="btn" id="toggleArrows">Fleches on/off</button>
    </div>
    <div id="read">Survole une cellule.</div>
    <div id="pits"></div>
    <div id="hint">Glisser = deplacer &middot; molette = zoom &middot; les fleches restent nettes a tout zoom.</div>
  </div>
</div>
<div id="tip"></div>
<script>
const D = __DATA__;
const cv = document.getElementById('cv'), ctx = cv.getContext('2d');
const tip = document.getElementById('tip');
let showArrows = true;
document.getElementById('k_valid').textContent = D.n_valid;
document.getElementById('k_pit').textContent = D.n_pit;
document.getElementById('k_filled').textContent = D.n_filled;
document.getElementById('c_pit').classList.add(D.n_pit ? 'bad' : 'ok');

// index cells by (row,col) for hover lookup
const N = D.col.length;
const key = (r,c)=>r*D.ncol+c;
const cellAt = new Map();
for(let i=0;i<N;i++) cellAt.set(key(D.row[i],D.col[i]), i);

let scale=1, ox=0, oy=0;         // px per cell, canvas offset of grid origin
function resize(){ cv.width=cv.clientWidth*devicePixelRatio; cv.height=cv.clientHeight*devicePixelRatio;
  ctx.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0); }
function fit(){
  const w=cv.clientWidth, h=cv.clientHeight, pad=24;
  scale=Math.min((w-2*pad)/D.ncol,(h-2*pad)/D.nrow);
  ox=(w-D.ncol*scale)/2; oy=(h-D.nrow*scale)/2; draw();
}
// grid(col,row) -> screen px (cell centre)
const sx=(c)=>ox+(c+0.5)*scale, sy=(r)=>oy+(r+0.5)*scale;

function draw(){
  const w=cv.clientWidth, h=cv.clientHeight;
  ctx.clearRect(0,0,w,h);
  const s=scale, half=s/2;
  // cells (shaded relief)
  for(let i=0;i<N;i++){
    const x=ox+D.col[i]*s, y=oy+D.row[i]*s;
    if(x>w||y>h||x+s<0||y+s<0) continue;
    ctx.fillStyle=D.rgb[i];
    ctx.fillRect(x,y,s+0.6,s+0.6);
  }
  // arrows
  if(showArrows && s>2.2){
    ctx.lineWidth=Math.max(0.6,s*0.09);
    ctx.strokeStyle='rgba(15,17,23,0.85)';
    const L=s*0.40, head=Math.min(s*0.22,4+s*0.05);
    ctx.beginPath();
    for(let i=0;i<N;i++){
      const d=D.dir[i]; if(d<0) continue;
      const x=sx(D.col[i]), y=sy(D.row[i]);
      if(x<-s||y<-s||x>w+s||y>h+s) continue;
      const nb=D.nb[d]; const ux=nb[0], uy=nb[1];
      const nrm=Math.hypot(ux,uy);
      const ex=x+ux/nrm*L, ey=y+uy/nrm*L;
      ctx.moveTo(x-ux/nrm*L*0.3, y-uy/nrm*L*0.3); ctx.lineTo(ex,ey);
      // head
      const a=Math.atan2(uy,ux);
      ctx.moveTo(ex,ey); ctx.lineTo(ex-head*Math.cos(a-0.5),ey-head*Math.sin(a-0.5));
      ctx.moveTo(ex,ey); ctx.lineTo(ex-head*Math.cos(a+0.5),ey-head*Math.sin(a+0.5));
    }
    ctx.stroke();
  }
  const mk=Math.max(3,s*0.42);
  // depressions filled away by the pipeline (harmless DEM noise) = amber squares
  for(let i=0;i<N;i++){
    if(D.dir[i]!==-3) continue;
    const x=sx(D.col[i]), y=sy(D.row[i]);
    ctx.fillStyle='#f59e0b'; ctx.strokeStyle='#5a3800'; ctx.lineWidth=1;
    ctx.fillRect(x-mk/2,y-mk/2,mk,mk); ctx.strokeRect(x-mk/2,y-mk/2,mk,mk);
  }
  // real cuvettes: pits that survive the fill (trap water), excluding the outlet
  for(let i=0;i<N;i++){
    if(D.dir[i]!==-1) continue;
    if(D.row[i]===D.orow && D.col[i]===D.ocol) continue;
    const x=sx(D.col[i]), y=sy(D.row[i]);
    ctx.fillStyle='#e11d48'; ctx.strokeStyle='#000'; ctx.lineWidth=1.4;
    ctx.fillRect(x-mk/2,y-mk/2,mk,mk); ctx.strokeRect(x-mk/2,y-mk/2,mk,mk);
  }
  // outlet
  const ox2=sx(D.ocol), oy2=sy(D.orow), r=Math.max(5,s*0.7);
  ctx.save(); ctx.translate(ox2,oy2); ctx.rotate(Math.PI/4);
  ctx.fillStyle='#d946ef'; ctx.strokeStyle='#000'; ctx.lineWidth=1.4;
  ctx.fillRect(-r/1.4,-r/1.4,r*1.4,r*1.4); ctx.strokeRect(-r/1.4,-r/1.4,r*1.4,r*1.4);
  ctx.restore();
}

// ---- interaction ----
let drag=null;
cv.addEventListener('mousedown',e=>{drag={x:e.clientX,y:e.clientY,ox,oy};cv.classList.add('grabbing');});
window.addEventListener('mouseup',()=>{drag=null;cv.classList.remove('grabbing');});
window.addEventListener('mousemove',e=>{
  if(drag){ ox=drag.ox+(e.clientX-drag.x); oy=drag.oy+(e.clientY-drag.y); draw(); return; }
  hover(e);
});
cv.addEventListener('wheel',e=>{
  e.preventDefault();
  const rect=cv.getBoundingClientRect(), mx=e.clientX-rect.left, my=e.clientY-rect.top;
  const f=Math.exp(-e.deltaY*0.0012);
  const gc=(mx-ox)/scale, gr=(my-oy)/scale;
  scale*=f; ox=mx-gc*scale; oy=my-gr*scale; draw();
},{passive:false});
function hover(e){
  const rect=cv.getBoundingClientRect();
  const c=Math.floor((e.clientX-rect.left-ox)/scale), r=Math.floor((e.clientY-rect.top-oy)/scale);
  const i=cellAt.get(key(r,c));
  if(i===undefined){ tip.style.display='none'; document.getElementById('read').textContent='Survole une cellule.'; return; }
  const cx=(D.x0+(c+0.5)*D.cs).toFixed(0), cy=(D.y0-(r+0.5)*D.cs).toFixed(0);
  const compass=['E','SE','S','SO','O','NO','N','NE'];
  let flow;
  const d=D.dir[i];
  if(d>=0) flow='ecoule vers le '+compass[d];
  else if(d===-2) flow='PLAT (voisin de meme cote)';
  else if(d===-3) flow='depression du DEM brut, comblee par le fill';
  else if(r===D.orow&&c===D.ocol) flow='EXUTOIRE du bassin';
  else flow='CUVETTE reelle (survit au fill, piege l\\'eau)';
  const txt=`X=${cx}  Y=${cy}\nz = ${D.z[i]} m\n${flow}`;
  document.getElementById('read').textContent=txt;
  tip.textContent=txt; tip.style.display='block';
  tip.style.left=(e.clientX+14)+'px'; tip.style.top=(e.clientY+14)+'px';
}
cv.addEventListener('mouseleave',()=>{tip.style.display='none';});

// pit list = real cuvettes (survive the fill). Click to zoom onto one.
const sx0=(c)=>(c+0.5)*scale, sy0=(r)=>(r+0.5)*scale;
const pl=document.getElementById('pits');
if(D.n_pit===0){
  const ok=document.createElement('div');
  ok.style.cssText='color:#34d399;font-size:12px;background:#0c1f16;border:1px solid #14532d;'
    +'border-radius:8px;padding:8px 10px';
  ok.textContent='Aucune cuvette reelle : apres le fill du pipeline, chaque cellule s ecoule '
    +'vers l exutoire. Les '+D.n_filled+' points orange sont des depressions ponctuelles du '
    +'DEM brut, toutes comblees par le fill.';
  pl.appendChild(ok);
}
for(let i=0;i<N;i++){
  if(D.dir[i]!==-1) continue;
  if(D.row[i]===D.orow&&D.col[i]===D.ocol) continue;
  const cx=(D.x0+(D.col[i]+0.5)*D.cs).toFixed(0), cy=(D.y0-(D.row[i]+0.5)*D.cs).toFixed(0);
  const b=document.createElement('button');
  b.textContent='Cuvette X='+cx+' Y='+cy+' ('+D.z[i]+' m)';
  b.onclick=()=>{ const w=cv.clientWidth,h=cv.clientHeight; scale=Math.max(scale,14);
    ox=w/2-sx0(D.col[i]); oy=h/2-sy0(D.row[i]); draw(); };
  pl.appendChild(b);
}

document.getElementById('fit').onclick=fit;
document.getElementById('toggleArrows').onclick=()=>{showArrows=!showArrows;draw();};
window.addEventListener('resize',()=>{resize();draw();});
resize(); fit();
</script></body></html>"""
).replace("__DATA__", json.dumps(data, default=lambda o: o.item() if hasattr(o, "item") else o))

os.makedirs(os.path.dirname(os.path.abspath(OUT)), exist_ok=True)
with open(OUT, "w") as f:
    f.write(HTML)
print("HTML ecrit :", os.path.abspath(OUT))
print("Ouvre-le dans un navigateur (double-clic). Aucun serveur requis.")

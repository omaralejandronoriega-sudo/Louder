#!/usr/bin/env python3
import json, html
from pathlib import Path
import build_artists as ba

ROOT=Path(__file__).resolve().parents[1]
artists=json.loads((ROOT/"data/artists.json").read_text(encoding="utf-8")).get("artists",[])
g=json.loads((ROOT/"data/galleries.json").read_text(encoding="utf-8")).get("artists",{})
g=ba.apply_identity_fallbacks(g)
g=ba.apply_reviewed_profile_overrides(g)
public,_=ba.prepare_public_artists([a for a in artists if isinstance(a,dict)])

def bio(a,x): return bool(str(a.get("bio") or x.get("bio_es") or x.get("bio_en") or "").strip())
def img(a,x): return bool(ba.preferred_image(a,x))
rows=[]
for a in public:
 x=g.get(str(a.get("slug") or ""),{}) or {}
 hi,hb=img(a,x),bio(a,x)
 rows.append({"name":a.get("name",""),"slug":a.get("slug",""),"image":hi,"bio":hb,"complete":hi and hb,"plays":int(a.get("plays") or 0)})
total=len(rows); both=sum(r["complete"] for r in rows); photos=sum(r["image"] for r in rows); bios=sum(r["bio"] for r in rows)
pct=lambda n: round(n*100/total,2) if total else 0
payload={"total":total,"complete":both,"complete_pct":pct(both),"photos":photos,"photos_pct":pct(photos),"bios":bios,"bios_pct":pct(bios),"target":90,"target_count":int((total*.9)+.9999),"remaining_to_90":max(0,int((total*.9)+.9999)-both),"rows":sorted(rows,key=lambda r:(r["complete"],-r["plays"],r["name"].casefold()))}
out=ROOT/"docs/control/artistas"; out.mkdir(parents=True,exist_ok=True)
data=json.dumps(payload,ensure_ascii=False).replace("</","<\\/")
page="""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>Artistas · Louder Control</title><style>
:root{--bg:#080808;--card:#111;--line:#292929;--text:#f6f6f2;--muted:#a9a9a3;--green:#b7ff32;--purple:#a778ff}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Arial,sans-serif}main{max-width:1100px;margin:auto;padding:24px}h1{font-family:Georgia,serif;font-size:clamp(32px,7vw,68px);margin:8px 0}.sub{color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:24px 0}.card{background:var(--card);border:1px solid var(--line);padding:18px;border-radius:14px}.num{font-size:34px;font-weight:900}.bar{height:12px;background:#222;border-radius:99px;overflow:hidden;margin-top:10px}.bar i{display:block;height:100%;background:var(--green)}.target i{background:var(--purple)}input{width:100%;padding:14px;background:#111;border:1px solid var(--line);color:white;border-radius:10px;font-size:16px}table{width:100%;border-collapse:collapse;margin-top:16px}th,td{text-align:left;padding:11px;border-bottom:1px solid var(--line)}.ok{color:var(--green);font-weight:bold}.no{color:#ff7b7b;font-weight:bold}@media(max-width:760px){.grid{grid-template-columns:1fr 1fr}.num{font-size:28px}th,td{padding:10px 6px;font-size:14px}th:nth-child(2),td:nth-child(2),th:nth-child(3),td:nth-child(3){font-size:12px}} </style></head><body><main><div class="sub">LOUDER · ARTISTAS</div><h1>Foto + biografía</h1><div class="sub">Control interno · Meta operativa: 90% con foto + biografía.</div><section class="grid" id="cards"></section><div style="display:grid;grid-template-columns:1fr 1fr;gap:8px"><input id="q" placeholder="Buscar artista"><select id="f" style="padding:14px;background:#111;border:1px solid var(--line);color:white;border-radius:10px"><option value="all">Todos</option><option value="complete">Completos</option><option value="photo">Falta foto</option><option value="bio">Falta bio</option><option value="both">Faltan ambos</option></select><select id="sort" style="padding:14px;background:#111;border:1px solid var(--line);color:white;border-radius:10px"><option value="az">A–Z</option><option value="za">Z–A</option></select></div><div id="pager" style="display:flex;justify-content:space-between;align-items:center;margin-top:14px"></div><table><thead><tr><th>Artista</th><th>Foto</th><th>Bio</th><th>Perfil</th></tr></thead><tbody id="rows"></tbody></table></main><script id="d" type="application/json">DATA</script><script>
const d=JSON.parse(document.getElementById('d').textContent); const cards=document.getElementById('cards');
const c=(t,n,p,cl='')=>'<div class="card"><div class="sub">'+t+'</div><div class="num">'+n+'</div><div>'+p+'%</div><div class="bar '+cl+'"><i style="width:'+Math.min(100,p)+'%"></i></div></div>';
cards.innerHTML=c('Foto + bio',d.complete+' / '+d.total,d.complete_pct,'target')+c('Con foto',d.photos,d.photos_pct)+c('Con biografía',d.bios,d.bios_pct)+c('Faltan para 90%',d.remaining_to_90,Math.max(0,90-d.complete_pct),'target');
const tb=document.getElementById('rows'),q=document.getElementById('q'),f=document.getElementById('f'),sort=document.getElementById('sort'),pager=document.getElementById('pager');let page=1;const per=50;
function filtered(){let s=q.value.toLowerCase(),a=d.rows.filter(r=>r.name.toLowerCase().includes(s));let v=f.value;if(v==='complete')a=a.filter(r=>r.complete);if(v==='photo')a=a.filter(r=>!r.image);if(v==='bio')a=a.filter(r=>!r.bio);if(v==='both')a=a.filter(r=>!r.image&&!r.bio);a.sort((x,y)=>x.name.localeCompare(y.name,'es',{sensitivity:'base'}));if(sort.value==='za')a.reverse();return a}
function draw(){let a=filtered(),pages=Math.max(1,Math.ceil(a.length/per));page=Math.min(page,pages);let slice=a.slice((page-1)*per,page*per);tb.innerHTML=slice.map(r=>'<tr><td><strong>'+r.name+'</strong></td><td class="'+(r.image?'ok':'no')+'">'+(r.image?'Sí':'Falta')+'</td><td class="'+(r.bio?'ok':'no')+'">'+(r.bio?'Sí':'Falta')+'</td><td><a style="color:var(--green);margin-right:10px" target="_blank" href="/artistas/'+r.slug+'/">ABRIR ↗</a><a style="color:var(--purple)" target="_blank" href="https://github.com/omaralejandronoriega-sudo/Louder/blob/main/data/artist_review_overrides.json#L1">Editar</a></td></tr>').join('');pager.innerHTML='<button '+(page<=1?'disabled':'')+' id="prev">← Anterior</button><span>Página '+page+' / '+pages+' · '+a.length+' artistas</span><button '+(page>=pages?'disabled':'')+' id="next">Siguiente →</button>';let p=document.getElementById('prev'),n=document.getElementById('next');if(p)p.onclick=()=>{page--;draw()};if(n)n.onclick=()=>{page++;draw()}}
[q,f,sort].forEach(x=>x.oninput=()=>{page=1;draw()});draw();
</script></body></html>""".replace("DATA",data)
(out/"index.html").write_text(page,encoding="utf-8")
print(json.dumps({k:v for k,v in payload.items() if k!="rows"},ensure_ascii=False))

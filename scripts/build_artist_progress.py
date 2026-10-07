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
out=ROOT/"docs/progreso-artistas"; out.mkdir(parents=True,exist_ok=True)
data=json.dumps(payload,ensure_ascii=False).replace("</","<\\/")
page="""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Progreso Artistas · Louder</title><style>
:root{--bg:#080808;--card:#111;--line:#292929;--text:#f6f6f2;--muted:#a9a9a3;--green:#b7ff32;--purple:#a778ff}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Arial,sans-serif}main{max-width:1100px;margin:auto;padding:24px}h1{font-family:Georgia,serif;font-size:clamp(32px,7vw,68px);margin:8px 0}.sub{color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:24px 0}.card{background:var(--card);border:1px solid var(--line);padding:18px;border-radius:14px}.num{font-size:34px;font-weight:900}.bar{height:12px;background:#222;border-radius:99px;overflow:hidden;margin-top:10px}.bar i{display:block;height:100%;background:var(--green)}.target i{background:var(--purple)}input{width:100%;padding:14px;background:#111;border:1px solid var(--line);color:white;border-radius:10px;font-size:16px}table{width:100%;border-collapse:collapse;margin-top:16px}th,td{text-align:left;padding:11px;border-bottom:1px solid var(--line)}.ok{color:var(--green);font-weight:bold}.no{color:#ff7b7b;font-weight:bold}@media(max-width:760px){.grid{grid-template-columns:1fr 1fr}.num{font-size:28px}th:nth-child(4),td:nth-child(4){display:none}} </style></head><body><main><div class="sub">LOUDER · ARTISTAS</div><h1>Foto + biografía</h1><div class="sub">Meta operativa: 90%. El panel se reconstruye con los datos reales publicados.</div><section class="grid" id="cards"></section><input id="q" placeholder="Buscar artista"><table><thead><tr><th>Artista</th><th>Foto</th><th>Bio</th><th>Reproducciones</th></tr></thead><tbody id="rows"></tbody></table></main><script id="d" type="application/json">DATA</script><script>
const d=JSON.parse(document.getElementById('d').textContent); const cards=document.getElementById('cards');
const c=(t,n,p,cl='')=>'<div class="card"><div class="sub">'+t+'</div><div class="num">'+n+'</div><div>'+p+'%</div><div class="bar '+cl+'"><i style="width:'+Math.min(100,p)+'%"></i></div></div>';
cards.innerHTML=c('Foto + bio',d.complete+' / '+d.total,d.complete_pct,'target')+c('Con foto',d.photos,d.photos_pct)+c('Con biografía',d.bios,d.bios_pct)+c('Faltan para 90%',d.remaining_to_90,Math.max(0,90-d.complete_pct),'target');
const tb=document.getElementById('rows'),q=document.getElementById('q'); function draw(){let s=q.value.toLowerCase();tb.innerHTML=d.rows.filter(r=>r.name.toLowerCase().includes(s)).slice(0,500).map(r=>'<tr><td><a style="color:inherit" href="../artistas/'+r.slug+'/">'+r.name+'</a></td><td class="'+(r.image?'ok':'no')+'">'+(r.image?'Sí':'Falta')+'</td><td class="'+(r.bio?'ok':'no')+'">'+(r.bio?'Sí':'Falta')+'</td><td>'+r.plays+'</td></tr>').join('')}q.oninput=draw;draw();
</script></body></html>""".replace("DATA",data)
(out/"index.html").write_text(page,encoding="utf-8")
print(json.dumps({k:v for k,v in payload.items() if k!="rows"},ensure_ascii=False))

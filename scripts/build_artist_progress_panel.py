#!/usr/bin/env python3
"""Generate the existing Louder internal artist-control route on GitHub Pages.
The page polls GitHub's PUBLIC Actions API. No requests hit WordPress."""
import json
from pathlib import Path
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/"docs"/"control"/"artistas"
DEST.mkdir(parents=True,exist_ok=True)
def read(path,default):
    try: return json.loads((ROOT/path).read_text(encoding="utf-8"))
    except (OSError, ValueError): return default

raw=read("data/artists.json",{})
entries=raw.get("artists",[]) if isinstance(raw,dict) else raw
entries=[a for a in entries if isinstance(a,dict) and a.get("name")]
state=read("data/identity_research_progress.json",{})
review=state.get("artists") if isinstance(state.get("artists"),dict) else {}
rows=[]
for a in entries:
    name=str(a.get("name","")).strip()
    if not name: continue
    key=" ".join(name.casefold().split())
    info=review.get(key,{})
    bio=bool(str(a.get("bio") or "").strip())
    img=bool(str(a.get("image") or "").strip())
    status="investigado" if info.get("status")=="identity_candidate_only" else ("revisar" if info.get("status")=="manual_review" else ("error" if info.get("status")=="retry" else "pendiente"))
    rows.append({"name":name,"slug":str(a.get("slug") or ""),"bio":bio,"image":img,"status":status})
rows.sort(key=lambda x:x["name"].casefold())
counts={key:sum(1 for v in review.values() if isinstance(v,dict) and v.get("status")==status)
        for key,status in (("candidates","identity_candidate_only"),("manual_review","manual_review"),("retry","retry"))}
researched=counts["candidates"]+counts["manual_review"]
data={"updated_at":datetime.now(timezone.utc).isoformat(),"research_updated_at":state.get("updated_at"),"cursor":state.get("cursor",0),"total":len(rows),"researched":researched,"counts":counts,"rows":rows}
(DEST/"data.json").write_text(json.dumps(data,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
html=r'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>Control de Artistas · Louder</title>
<style>:root{font-family:Arial,Helvetica,sans-serif;color:#eceeec;background:#0b0d0c}*{box-sizing:border-box}body{margin:0}header{padding:30px clamp(18px,4vw,60px);border-bottom:1px solid #303531;display:flex;align-items:center;justify-content:space-between;gap:15px;flex-wrap:wrap}.brand{font-weight:900;letter-spacing:.07em;color:#b2fc30}.tag{color:#aaa;font-size:12px}main{max-width:1300px;margin:0 auto;padding:30px 18px}h1{font-size:clamp(26px,4vw,42px);margin:0 0 8px}p{color:#aab3a8}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:13px;margin:24px 0}.metric,.pane{border:1px solid #303831;background:#141916;border-radius:15px;padding:20px}.metric b{display:block;font-size:28px;margin:8px 0}.metric span{font-size:13px;color:#a4b1a5}.line{height:16px;background:#323b32;border-radius:50px;overflow:hidden}.fill{height:100%;width:0;background:#a7ef35;transition:width .5s}.working{width:100%!important;background:repeating-linear-gradient(110deg,#a7ef35 0,#a7ef35 20px,#7cb91e 20px,#7cb91e 40px);background-size:200% 100%;animation:move 1.5s linear infinite}@keyframes move{from{background-position:0 0}to{background-position:160px 0}}.flex{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.sub{font-size:12px;color:#91a097}.pane{margin-bottom:17px}input,select,button{color:#eee;background:#18211a;border:1px solid #405343;border-radius:9px;padding:10px;font-size:14px}input{min-width:200px;flex:1}button{cursor:pointer}button:disabled{opacity:.4}table{width:100%;border-collapse:collapse}th,td{padding:12px 9px;border-bottom:1px solid #28302a;text-align:left;font-size:13px}th{color:#abb6ad}a{color:#a7ef35;text-decoration:none}.table-wrap{overflow:auto}.chips{font-size:11px;color:#bdc5be}#latest{color:#e5eae5}#error{color:#ffbf80} .small{font-size:12px} .badge{display:inline-block;border:1px solid #4e614c;border-radius:99px;padding:4px 8px}.nowrap{white-space:nowrap}</style></head>
<body><header><div><span class="brand">LOUDER</span> <span class="tag">/ CONTROL / ARTISTAS</span></div><span class="tag">Panel de seguimiento · GitHub, fuera del hosting</span></header>
<main><h1>Progreso de Artistas</h1><p>Seguimiento del procesamiento externo. La investigación y la publicación editorial se contabilizan por separado.</p>
<section class="metrics"><div class="metric"><span>Artistas del catálogo</span><b id="total">—</b></div><div class="metric"><span>Revisados por GitHub</span><b id="researched">—</b></div><div class="metric"><span>Pendientes de investigación</span><b id="pending">—</b></div><div class="metric"><span>Estado del último flujo</span><b id="run">—</b></div></section>
<section class="pane"><div class="flex"><b>Avance acumulado de investigación</b><strong id="percentage">0%</strong></div><div class="line" role="progressbar" aria-label="Artistas investigados" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" id="progress"><div class="fill" id="fill"></div></div><p class="sub" id="remaining">Cargando datos...</p></section>
<section class="pane"><div class="flex"><b>Lote de GitHub</b><span id="live" class="badge">Consultando...</span></div><p id="latest">Comprobando ejecuciones.</p><div class="line"><div class="fill" id="jobfill"></div></div><p class="sub" id="time">Última comprobación: —</p><p id="error" class="small"></p><a id="actionlink" target="_blank" rel="noopener" href="https://github.com/omaralejandronoriega-sudo/Louder/actions/workflows/artistas-investigacion-externa.yml">Abrir ejecución en GitHub ↗</a><p class="sub">Durante una ejecución, GitHub informa su estado en vivo. El contador de artistas procesados se actualiza al finalizar y guardar el lote; la barra no simula pasos individuales.</p></section>
<section class="pane"><div class="flex"><b>Perfiles del catálogo</b><span id="paging" class="sub"></span></div><div class="flex" style="margin:16px 0"><input id="search" type="search" placeholder="Buscar artista"/><select id="filter"><option value="all">Todos los estados</option><option value="investigado">Investigados</option><option value="pendiente">Pendientes</option><option value="revisar">Por revisar</option><option value="error">Error</option></select></div><div class="table-wrap"><table><thead><tr><th>Artista</th><th>Biografía en catálogo</th><th>Imagen en catálogo</th><th>Investigación externa</th><th>Perfil</th></tr></thead><tbody id="tbody"></tbody></table></div><div class="flex" style="margin-top:16px"><button id="prev">← Anterior</button><span id="page"></span><button id="next">Siguiente →</button></div></section>
</main><script>
const REPO="omaralejandronoriega-sudo/Louder",WF="artistas-investigacion-externa.yml";
const $=id=>document.getElementById(id);let data={rows:[],total:0,researched:0},page=1;
function escapeHTML(s){return String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))}
function render(){let q=$("search").value.toLocaleLowerCase("es"),f=$("filter").value;let rows=data.rows.filter(r=>r.name.toLocaleLowerCase("es").includes(q)&&(f==="all"||r.status===f));let pages=Math.max(1,Math.ceil(rows.length/50));page=Math.max(1,Math.min(page,pages));$("paging").textContent=rows.length+" coincidencias";$("page").textContent="Página "+page+" de "+pages;$("prev").disabled=page<=1;$("next").disabled=page>=pages;$("tbody").innerHTML=rows.slice((page-1)*50,page*50).map(r=>'<tr><td>'+escapeHTML(r.name)+'</td><td>'+ (r.bio?"Sí":"Pendiente")+'</td><td>'+(r.image?"Sí":"Pendiente")+'</td><td>'+escapeHTML(r.status)+'</td><td><a target="_blank" rel="noopener" href="https://loudermx.com/artistas/'+encodeURIComponent(r.slug)+'/">Ver ↗</a></td></tr>').join("")}
async function refreshData(){try{let res=await fetch("data.json?v="+Date.now(),{cache:"no-store"});if(!res.ok)throw Error("Datos "+res.status);data=await res.json();$("total").textContent=data.total.toLocaleString("es-MX");$("researched").textContent=data.researched.toLocaleString("es-MX");$("pending").textContent=Math.max(0,data.total-data.researched).toLocaleString("es-MX");let p=data.total?Math.min(100,100*data.researched/data.total):0;$("percentage").textContent=p.toFixed(1)+"%";$("fill").style.width=p+"%";$("progress").setAttribute("aria-valuenow",p.toFixed(1));$("remaining").textContent=Math.max(0,data.total-data.researched)+" pendientes de investigación (incluye reintentos) · candidatos: "+(data.counts?.candidates??0)+" · revisión manual: "+(data.counts?.manual_review??0)+" · reintentos: "+(data.counts?.retry??0)+" · último archivo: "+(data.research_updated_at||"sin ejecución guardada");render()}catch(e){$("error").textContent="Error al cargar datos del archivo: "+e.message}}
async function refreshRun(){try{let url="https://api.github.com/repos/"+REPO+"/actions/workflows/"+WF+"/runs?per_page=1";let res=await fetch(url,{cache:"no-store",headers:{"Accept":"application/vnd.github+json"}});if(!res.ok)throw Error("GitHub "+res.status);let runs=(await res.json()).workflow_runs||[],run=runs[0];$("time").textContent="Última comprobación: "+new Date().toLocaleTimeString("es-MX");if(!run){$("run").textContent="Sin ejecuciones";$("live").textContent="Esperando primer lote";return}$("run").textContent=run.conclusion||run.status;$("live").textContent=run.status==="completed"?(run.conclusion==="success"?"Terminado":"Con errores"):"Procesando ahora";$("latest").textContent="Ejecución #"+run.run_number+" · "+(run.status==="completed"?"Finalizada":"En ejecución")+" · "+new Date(run.created_at).toLocaleString("es-MX");$("jobfill").classList.toggle("working",run.status!=="completed");$("jobfill").style.width=run.status==="completed"?"100%":"0%";$("actionlink").href=run.html_url;if(run.conclusion==="failure")$("error").textContent="El último lote falló. Abre GitHub para ver la causa.";else $("error").textContent=""}catch(e){$("live").textContent="Estado no disponible";$("error").textContent="No pude consultar GitHub: "+e.message}}
$("search").addEventListener("input",()=>{page=1;render()});$("filter").addEventListener("change",()=>{page=1;render()});$("prev").onclick=()=>{page--;render()};$("next").onclick=()=>{page++;render()};refreshData();refreshRun();setInterval(refreshRun,20000);setInterval(refreshData,60000);
</script></body></html>'''
(DEST/"index.html").write_text(html,encoding="utf-8")
print("control_artistas_panel total=",len(rows),"reviewed=",len(review),"route=/control/artistas/")

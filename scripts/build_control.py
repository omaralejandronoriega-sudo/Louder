#!/usr/bin/env python3
"""Build Louder Control PWA into docs/control/."""

from __future__ import annotations

import html
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "control.json"
OUT = ROOT / "docs" / "control"
LOGO = ROOT / "assets" / "logo_louder.png"


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def main() -> None:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "data.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if LOGO.exists():
        shutil.copy2(LOGO, OUT / "logo_louder.png")

    manifest = {
        "name": "Louder Control",
        "short_name": "Louder Control",
        "description": "Centro de control móvil de Louder.",
        "start_url": "./",
        "scope": "./",
        "display": "standalone",
        "background_color": "#090a0a",
        "theme_color": "#caff00",
        "lang": "es-MX",
        "icons": [
            {
                "src": "./icon.svg",
                "sizes": "any",
                "type": "image/svg+xml",
                "purpose": "any maskable",
            }
        ],
    }
    (OUT / "manifest.webmanifest").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    icon = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
<rect width="512" height="512" rx="96" fill="#090a0a"/>
<path d="M116 104h76v238h210v70H116z" fill="#caff00"/>
<circle cx="376" cy="142" r="38" fill="#f4f4ef"/>
</svg>"""
    (OUT / "icon.svg").write_text(icon, encoding="utf-8")

    sw = """const CACHE='louder-control-v1';
const CORE=['./','./index.html','./data.json','./manifest.webmanifest','./icon.svg','./logo_louder.png'];
self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(CORE.filter(Boolean))).then(()=>self.skipWaiting())));
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',e=>{
  if(e.request.method!=='GET') return;
  const u=new URL(e.request.url);
  if(u.origin!==location.origin) return;
  e.respondWith(fetch(e.request).then(r=>{const copy=r.clone();caches.open(CACHE).then(c=>c.put(e.request,copy));return r;}).catch(()=>caches.match(e.request)));
});
self.addEventListener('message',e=>{
  if(e.data&&e.data.type==='NOTIFY'){
    self.registration.showNotification(e.data.title||'Louder Control',{
      body:e.data.body||'Tienes un recordatorio pendiente.',
      icon:'./icon.svg',
      badge:'./icon.svg',
      tag:e.data.tag||'louder-control',
      renotify:false
    });
  }
});"""
    (OUT / "sw.js").write_text(sw, encoding="utf-8")

    seed = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html_doc = f"""<!doctype html>
<html lang="es-MX">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#caff00">
<meta name="robots" content="noindex,nofollow">
<link rel="manifest" href="./manifest.webmanifest">
<link rel="icon" href="./icon.svg" type="image/svg+xml">
<title>Louder Control</title>
<style>
:root{{
 --bg:#090a0a;--panel:#111313;--panel2:#171919;--line:#2b2e2e;--text:#f4f4ef;--muted:#a5aaa7;
 --accent:#caff00;--accentText:#0a0b0a;--warn:#ffd166;--danger:#ff6868;--ok:#70e09b;--info:#7bc5ff;
 --radius:18px;--shadow:0 16px 44px rgba(0,0,0,.26)
}}
*{{box-sizing:border-box}}
html{{background:var(--bg);color-scheme:dark}}
body{{margin:0;background:var(--bg);color:var(--text);font-family:Syne,Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;min-height:100vh}}
button,input,select,textarea{{font:inherit}}
button,a,input,select,textarea{{-webkit-tap-highlight-color:transparent}}
button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{{outline:3px solid var(--accent);outline-offset:2px}}
.skip{{position:absolute;left:-9999px;top:8px;background:var(--accent);color:#000;padding:10px;z-index:1000}}
.skip:focus{{left:8px}}
.shell{{max-width:1120px;margin:auto;padding:0 16px 100px}}
header{{position:sticky;top:0;z-index:20;background:rgba(9,10,10,.92);backdrop-filter:blur(18px);border-bottom:1px solid rgba(255,255,255,.06);padding-top:env(safe-area-inset-top)}}
.head{{max-width:1120px;margin:auto;padding:13px 16px 12px;display:flex;align-items:center;gap:12px}}
.logo{{width:104px;max-height:34px;object-fit:contain;object-position:left center}}
.brand-fallback{{font-weight:900;letter-spacing:.12em}}
.head-copy{{min-width:0;flex:1}}
.head-copy strong{{display:block;font-size:14px}}
.head-copy span{{display:block;color:var(--muted);font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.live-pill{{display:flex;align-items:center;gap:7px;border:1px solid var(--line);border-radius:999px;padding:8px 10px;font-size:11px;color:var(--muted);white-space:nowrap}}
.live-pill i{{width:7px;height:7px;border-radius:50%;background:var(--ok);display:block}}
.hero{{padding:26px 0 14px}}
.eyebrow{{text-transform:uppercase;color:var(--accent);font-weight:900;font-size:11px;letter-spacing:.18em}}
h1{{font-size:clamp(42px,11vw,78px);letter-spacing:-.065em;line-height:.88;margin:8px 0 12px}}
.hero p{{color:var(--muted);line-height:1.5;margin:0;max-width:760px}}
.quick{{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;margin:20px 0 24px}}
.metric{{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:14px;min-height:94px}}
.metric strong{{display:block;font-size:28px;letter-spacing:-.04em}}
.metric span{{display:block;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em;margin-top:4px}}
.metric.attn strong{{color:var(--danger)}} .metric.work strong{{color:var(--warn)}} .metric.done strong{{color:var(--ok)}}
.section{{margin:24px 0}}
.section-head{{display:flex;align-items:end;justify-content:space-between;gap:16px;margin-bottom:12px}}
.section-head h2{{margin:0;font-size:23px;letter-spacing:-.03em}}
.section-head p{{margin:4px 0 0;color:var(--muted);font-size:13px}}
.toolbar{{display:flex;gap:8px;flex-wrap:wrap}}
.btn{{border:1px solid var(--line);background:var(--panel2);color:var(--text);border-radius:12px;padding:10px 12px;min-height:42px;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;justify-content:center;gap:7px}}
.btn.primary{{background:var(--accent);border-color:var(--accent);color:var(--accentText);font-weight:800}}
.btn.ghost{{background:transparent}}
.btn.small{{padding:7px 9px;min-height:36px;font-size:12px}}
.btn[disabled]{{opacity:.45;cursor:not-allowed}}
.priority-list{{display:grid;gap:9px}}
.priority-card{{display:grid;grid-template-columns:auto 1fr auto;gap:12px;align-items:center;background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:14px}}
.rank{{width:34px;height:34px;border-radius:10px;background:var(--accent);color:#000;display:grid;place-items:center;font-weight:900}}
.priority-card h3{{margin:0 0 4px;font-size:15px}}
.priority-card p{{margin:0;color:var(--muted);font-size:12px;line-height:1.4}}
.progress-mini{{font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums}}
.alerts{{display:grid;gap:9px}}
.alert{{border:1px solid var(--line);border-left-width:4px;border-radius:14px;background:var(--panel);padding:13px 14px;display:grid;grid-template-columns:1fr auto;gap:10px}}
.alert.danger{{border-left-color:var(--danger)}} .alert.warning{{border-left-color:var(--warn)}} .alert.info{{border-left-color:var(--info)}} .alert.ok{{border-left-color:var(--ok)}}
.alert strong{{display:block;font-size:13px}} .alert p{{margin:4px 0 0;color:var(--muted);font-size:12px;line-height:1.45}}
.alert time{{color:var(--muted);font-size:11px;white-space:nowrap}}
.searchrow{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}}
.search{{flex:1;min-width:210px;background:var(--panel);border:1px solid var(--line);color:var(--text);border-radius:12px;padding:11px 12px}}
.select{{background:var(--panel);border:1px solid var(--line);color:var(--text);border-radius:12px;padding:11px 12px}}
.projects{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}}
.project{{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:16px;box-shadow:var(--shadow);display:flex;flex-direction:column;min-height:245px}}
.project-top{{display:flex;justify-content:space-between;gap:12px;align-items:start}}
.project h3{{margin:6px 0 6px;font-size:21px;letter-spacing:-.035em}}
.area{{font-size:10px;text-transform:uppercase;letter-spacing:.14em;color:var(--accent);font-weight:800}}
.status{{border:1px solid var(--line);border-radius:999px;padding:6px 8px;font-size:10px;white-space:nowrap;text-transform:uppercase;letter-spacing:.08em}}
.status.attention{{border-color:rgba(255,104,104,.55);color:var(--danger)}} .status.active{{color:var(--warn)}} .status.done{{color:var(--ok)}}
.project p{{color:var(--muted);font-size:12px;line-height:1.5;margin:6px 0 12px}}
.bar{{height:8px;background:#232626;border-radius:999px;overflow:hidden;margin:4px 0 8px}}
.bar>i{{height:100%;background:var(--accent);display:block;border-radius:inherit}}
.prog{{display:flex;justify-content:space-between;color:var(--muted);font-size:11px}}
.next{{margin-top:12px;border-top:1px solid var(--line);padding-top:12px}}
.next b{{display:block;color:var(--text);font-size:11px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px}}
.project-actions{{margin-top:auto;padding-top:14px;display:flex;gap:8px;flex-wrap:wrap}}
.source{{margin-top:10px;color:#777f7b;font-size:10px}}
.pending-list,.activity-list,.reminder-list{{display:grid;gap:8px}}
.pending{{display:grid;grid-template-columns:auto 1fr auto;gap:10px;align-items:center;background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:12px}}
.pending input{{width:20px;height:20px;accent-color:var(--accent)}}
.pending strong{{display:block;font-size:13px}} .pending span{{display:block;color:var(--muted);font-size:11px;margin-top:2px}}
.empty{{border:1px dashed var(--line);border-radius:16px;padding:24px;color:var(--muted);text-align:center}}
.panel{{display:none}} .panel.active{{display:block}}
.bottom{{position:fixed;z-index:30;bottom:0;left:0;right:0;background:rgba(12,13,13,.96);border-top:1px solid var(--line);padding:8px 8px calc(8px + env(safe-area-inset-bottom));display:flex;justify-content:center}}
.nav{{width:min(680px,100%);display:grid;grid-template-columns:repeat(5,1fr);gap:4px}}
.nav button{{border:0;background:transparent;color:var(--muted);border-radius:10px;padding:8px 3px;font-size:10px;min-height:50px;cursor:pointer}}
.nav button strong{{display:block;font-size:16px;line-height:1.2;margin-bottom:3px}}
.nav button.active{{background:var(--panel2);color:var(--text)}}
dialog{{width:min(720px,calc(100% - 22px));max-height:88vh;background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:22px;padding:0;box-shadow:0 30px 90px #000}}
dialog::backdrop{{background:rgba(0,0,0,.72);backdrop-filter:blur(5px)}}
.modal-head{{position:sticky;top:0;background:var(--panel);display:flex;gap:12px;justify-content:space-between;align-items:start;padding:18px;border-bottom:1px solid var(--line);z-index:2}}
.modal-head h2{{margin:4px 0 0;font-size:24px}} .modal-body{{padding:18px}}
.close{{width:40px;height:40px;border-radius:50%;border:1px solid var(--line);background:var(--panel2);color:var(--text);cursor:pointer}}
.checklist{{display:grid;gap:8px;margin:14px 0 22px}}
.check{{display:grid;grid-template-columns:auto 1fr;gap:10px;align-items:start;border:1px solid var(--line);border-radius:12px;padding:11px}}
.check input{{width:20px;height:20px;accent-color:var(--accent);margin-top:1px}}
.field{{display:grid;gap:6px;margin:12px 0}}
.field label{{font-size:11px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);font-weight:800}}
.field input,.field textarea{{width:100%;background:#0d0f0f;border:1px solid var(--line);color:var(--text);border-radius:12px;padding:11px}}
.field textarea{{min-height:90px;resize:vertical}}
.inline{{display:flex;gap:8px;align-items:center;flex-wrap:wrap}}
.note{{font-size:11px;color:var(--muted);line-height:1.5}}
.reminder-form{{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:14px;display:grid;gap:10px}}
.reminder-grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
.reminder{{display:grid;grid-template-columns:1fr auto;gap:10px;background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:12px}}
.reminder.due{{border-color:rgba(255,209,102,.6)}} .reminder strong{{display:block}} .reminder span{{font-size:11px;color:var(--muted)}}
.activity{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:12px}}
.activity strong{{display:block;font-size:13px}} .activity span{{color:var(--muted);font-size:11px}} .activity a{{color:var(--accent)}}
.install-card{{display:flex;align-items:center;justify-content:space-between;gap:12px;background:linear-gradient(120deg,#caff00,#eaff91);color:#090a0a;border-radius:18px;padding:16px;margin:14px 0}}
.install-card h3{{margin:0 0 4px}} .install-card p{{margin:0;font-size:12px;opacity:.8}}
.install-card .btn{{border-color:#090a0a;color:#090a0a;background:transparent}}
@media(max-width:760px){{
 .quick{{grid-template-columns:repeat(2,1fr)}} .projects{{grid-template-columns:1fr}} .project{{min-height:0}}
 .head-copy span{{display:none}} .live-pill{{padding:7px 8px}} .reminder-grid{{grid-template-columns:1fr}}
}}
@media(max-width:420px){{.logo{{width:88px}}h1{{font-size:52px}}.shell{{padding-left:12px;padding-right:12px}}}}
@media(prefers-reduced-motion:reduce){{*{{scroll-behavior:auto!important;transition:none!important}}}}
</style>
</head>
<body>
<a class="skip" href="#main">Saltar al contenido</a>
<header>
 <div class="head">
  <img class="logo" src="./logo_louder.png" alt="Louder" onerror="this.hidden=true;this.nextElementSibling.hidden=false">
  <span class="brand-fallback" hidden>LOUDER</span>
  <div class="head-copy"><strong>CONTROL</strong><span>Operación, pendientes y automatizaciones</span></div>
  <div class="live-pill" id="livePill"><i></i><span>Actualizando</span></div>
 </div>
</header>

<main id="main" class="shell">
 <section class="panel active" data-panel="today">
  <div class="hero">
   <div class="eyebrow">Centro de operaciones</div>
   <h1>Louder<br>hoy.</h1>
   <p id="heroText">Lo urgente, lo que sigue y cualquier proceso que necesite atención.</p>
  </div>
  <div id="installCard" class="install-card" hidden>
   <div><h3>Instalar en Android</h3><p>Queda como app en tu pantalla de inicio.</p></div>
   <button class="btn" id="installBtn" type="button">Instalar</button>
  </div>
  <div class="quick" id="quickMetrics"></div>
  <section class="section">
   <div class="section-head"><div><h2>Prioridad ahora</h2><p>Calculada por criticidad, pendientes y alertas.</p></div></div>
   <div class="priority-list" id="priorityList"></div>
  </section>
  <section class="section">
   <div class="section-head"><div><h2>Necesita atención</h2><p>Fallos, estancamiento y mejoras detectadas.</p></div><button class="btn small" id="refreshLive" type="button">Actualizar</button></div>
   <div class="alerts" id="alerts"></div>
  </section>
 </section>

 <section class="panel" data-panel="projects">
  <div class="hero"><div class="eyebrow">Todos los frentes</div><h1>Proyectos.</h1><p>El avance sale de tareas terminadas. Los estados de GitHub se consultan en vivo.</p></div>
  <div class="searchrow">
   <input class="search" id="projectSearch" type="search" placeholder="Buscar proyecto, área o chat…">
   <select class="select" id="projectFilter" aria-label="Filtrar proyectos"><option value="">Todos</option><option value="critical">Críticos</option><option value="high">Alta prioridad</option><option value="attention">Con atención</option></select>
  </div>
  <div class="projects" id="projectsGrid"></div>
 </section>

 <section class="panel" data-panel="pending">
  <div class="hero"><div class="eyebrow">Checklist global</div><h1>Pendientes.</h1><p>Marca tareas desde el teléfono; los cambios quedan guardados en este dispositivo.</p></div>
  <div class="pending-list" id="pendingList"></div>
 </section>

 <section class="panel" data-panel="alerts">
  <div class="hero"><div class="eyebrow">Inteligencia operativa</div><h1>Alertas.</h1><p>Recordatorios, fallos y sugerencias concretas de mejora para que ningún frente se quede dormido.</p></div>
  <section class="section">
   <div class="section-head"><div><h2>Sugerencias</h2><p>Se regeneran a partir del estado actual.</p></div></div>
   <div class="alerts" id="alertsFull"></div>
  </section>
  <section class="section">
   <div class="section-head"><div><h2>Recordatorios</h2><p>Persisten en tu Android. Si das permiso, pueden avisarte mientras la app esté activa.</p></div><button class="btn small" id="notifyBtn" type="button">Activar avisos</button></div>
   <form class="reminder-form" id="reminderForm">
    <div class="field"><label for="reminderText">Qué recordar</label><input id="reminderText" required placeholder="Ej. revisar el siguiente TikTok"></div>
    <div class="reminder-grid">
     <div class="field"><label for="reminderWhen">Cuándo</label><input id="reminderWhen" type="datetime-local" required></div>
     <div class="field"><label for="reminderProject">Proyecto</label><select class="select" id="reminderProject"></select></div>
    </div>
    <div><button class="btn primary" type="submit">Guardar recordatorio</button></div>
   </form>
   <div class="reminder-list" id="reminderList" style="margin-top:10px"></div>
  </section>
 </section>

 <section class="panel" data-panel="activity">
  <div class="hero"><div class="eyebrow">Estado técnico</div><h1>Actividad.</h1><p>Últimas ejecuciones conocidas de los repositorios de Louder conectados.</p></div>
  <div class="toolbar" style="margin-bottom:12px"><button class="btn" id="exportBtn" type="button">Exportar control</button></div>
  <div class="activity-list" id="activityList"></div>
 </section>
</main>

<nav class="bottom" aria-label="Navegación principal">
 <div class="nav">
  <button class="active" data-nav="today" type="button"><strong>●</strong>Hoy</button>
  <button data-nav="projects" type="button"><strong>▦</strong>Proyectos</button>
  <button data-nav="pending" type="button"><strong>✓</strong>Pendientes</button>
  <button data-nav="alerts" type="button"><strong>!</strong>Alertas</button>
  <button data-nav="activity" type="button"><strong>↻</strong>Actividad</button>
 </div>
</nav>

<dialog id="projectDialog">
 <div class="modal-head">
  <div><div class="area" id="modalArea"></div><h2 id="modalTitle"></h2></div>
  <button class="close" id="modalClose" aria-label="Cerrar" type="button">×</button>
 </div>
 <div class="modal-body">
  <p id="modalSummary" style="color:var(--muted);line-height:1.5"></p>
  <div class="inline"><span class="status" id="modalStatus"></span><span class="progress-mini" id="modalProgress"></span></div>
  <h3>Checklist</h3><div class="checklist" id="modalChecklist"></div>
  <div class="field"><label for="modalNote">Notas tuyas</label><textarea id="modalNote" placeholder="Decisiones, bloqueos, lo que quieras recordar…"></textarea></div>
  <div class="field"><label for="modalChat">Enlace al chat de ChatGPT</label><input id="modalChat" type="url" placeholder="Pega aquí el enlace del chat"></div>
  <div class="inline">
   <button class="btn primary" id="saveProject" type="button">Guardar</button>
   <a class="btn" id="openChat" href="https://chatgpt.com/" target="_blank" rel="noopener">Abrir ChatGPT</a>
  </div>
  <p class="note">Los enlaces de chat y tus notas se guardan localmente en este teléfono; no se publican en GitHub.</p>
 </div>
</dialog>

<script id="seed-data" type="application/json">{seed}</script>
<script>
const seed=JSON.parse(document.getElementById('seed-data').textContent);
const STORE='louder-control-state-v1';
const state=JSON.parse(localStorage.getItem(STORE)||'null')||{{tasks:{{}},notes:{{}},chats:{{}},reminders:[],notified:{{}},activity:{{}}}};
let live={{}};
let currentProject=null;
let deferredInstall=null;
const $=(q,r=document)=>r.querySelector(q);
const $$=(q,r=document)=>[...r.querySelectorAll(q)];

function save(){{localStorage.setItem(STORE,JSON.stringify(state));}}
function taskDone(t){{return Object.prototype.hasOwnProperty.call(state.tasks,t.id)?!!state.tasks[t.id]:!!t.done;}}
function projectProgress(p){{
 const total=p.tasks.length||1,done=p.tasks.filter(taskDone).length;
 return Math.round(done/total*100);
}}
function mergedProject(p){{return {{...p,progress:projectProgress(p),pending:p.tasks.filter(t=>!taskDone(t)).length}};}}
function priorityScore(p){{
 let s={{critical:100,high:70,normal:40}}[p.priority]||30;
 if(p.status==='attention')s+=35;
 s+=Math.max(0,50-projectProgress(p));
 const repo=live[p.repo];
 if(repo?.conclusion==='failure')s+=70;
 if(repo?.status==='in_progress')s+=8;
 return s;
}}
function statusLabel(s){{return s==='attention'?'Atención':s==='done'?'Terminado':'En proceso';}}
function fmtDate(v){{
 if(!v)return '—';
 try{{return new Intl.DateTimeFormat('es-MX',{{dateStyle:'medium',timeStyle:v.includes('T')?'short':undefined}}).format(new Date(v));}}catch{{return v}}
}}
function daysSince(v){{if(!v)return 999;return Math.floor((Date.now()-new Date(v+'T12:00:00').getTime())/86400000);}}
function projectById(id){{return seed.projects.find(p=>p.id===id);}}

function alerts(){{
 const out=[];
 for(const p of seed.projects){{
  const prog=projectProgress(p), repo=live[p.repo];
  if(repo?.conclusion==='failure') out.push({{level:'danger',title:'Falló una automatización',body:`${p.name}: ${repo.name||'workflow'} terminó con error. Conviene revisar el run antes de seguir acumulando tareas.`,date:repo.updated_at||repo.created_at,project:p.id}});
  if(repo?.status==='in_progress') out.push({{level:'info',title:'Proceso ejecutándose',body:`${p.name}: ${repo.name||'workflow'} sigue en curso.`,date:repo.updated_at||repo.created_at,project:p.id}});
  if(p.status==='attention') out.push({{level:'warning',title:`${p.name} necesita revisión`,body:p.next,date:p.updated,project:p.id}});
  if((p.priority==='critical'||p.priority==='high')&&prog<50) out.push({{level:'warning',title:'Mucho pendiente en un frente prioritario',body:`${p.name} va en ${prog}% según su checklist. Siguiente acción: ${p.next}`,date:p.updated,project:p.id}});
  if(daysSince(p.updated)>=7&&p.status!=='done') out.push({{level:'info',title:'Proyecto sin movimiento reciente',body:`${p.name} lleva ${daysSince(p.updated)} días sin una actualización registrada. Conviene decidir si sigue activo, está bloqueado o puede cerrarse.`,date:p.updated,project:p.id}});
  if(p.event_date){{
   const d=Math.ceil((new Date(p.event_date+'T12:00:00')-Date.now())/86400000);
   if(d>=0&&d<=45) out.push({{level:'warning',title:'Fecha de evento acercándose',body:`${p.name}: faltan ${d} días para el evento. ${p.next}`,date:p.event_date,project:p.id}});
  }}
 }}
 const failed=out.some(x=>x.level==='danger');
 if(!failed && Object.keys(live).length) out.push({{level:'ok',title:'Sin fallos nuevos en los últimos runs consultados',body:'Los repositorios que respondieron no muestran un fallo como ejecución más reciente.',date:new Date().toISOString()}});
 return out.sort((a,b)=>({{danger:4,warning:3,info:2,ok:1}}[b.level]-({{danger:4,warning:3,info:2,ok:1}}[a.level]));
}}
function metrics(){{
 const ps=seed.projects.map(mergedProject);
 const a=alerts();
 return {{
  attention:ps.filter(p=>p.status==='attention').length+a.filter(x=>x.level==='danger').length,
  active:ps.filter(p=>p.status==='active').length,
  pending:ps.reduce((n,p)=>n+p.pending,0),
  done:ps.reduce((n,p)=>n+p.tasks.filter(taskDone).length,0)
 }};
}}
function renderMetrics(){{
 const m=metrics();
 $('#quickMetrics').innerHTML=`
 <div class="metric attn"><strong>${m.attention}</strong><span>requieren atención</span></div>
 <div class="metric work"><strong>${m.active}</strong><span>proyectos activos</span></div>
 <div class="metric"><strong>${m.pending}</strong><span>tareas pendientes</span></div>
 <div class="metric done"><strong>${m.done}</strong><span>tareas cerradas</span></div>`;
}}
function renderPriority(){{
 const ps=seed.projects.map(mergedProject).sort((a,b)=>priorityScore(b)-priorityScore(a)).slice(0,4);
 $('#priorityList').innerHTML=ps.map((p,i)=>`<button class="priority-card" data-open="${p.id}" type="button" style="text-align:left;color:inherit;width:100%">
 <span class="rank">${i+1}</span><span><h3>${p.name}</h3><p>${p.next}</p></span><span class="progress-mini">${p.progress}%</span></button>`).join('');
}}
function alertHtml(x){{return `<article class="alert ${x.level}" ${x.project?`data-open="${x.project}"`:''}><div><strong>${x.title}</strong><p>${x.body}</p></div><time>${fmtDate(x.date)}</time></article>`;}}
function renderAlerts(){{
 const a=alerts();
 $('#alerts').innerHTML=a.slice(0,5).map(alertHtml).join('')||'<div class="empty">Sin alertas.</div>';
 $('#alertsFull').innerHTML=a.map(alertHtml).join('')||'<div class="empty">Sin alertas.</div>';
}}
function renderProjects(){{
 const q=$('#projectSearch')?.value.toLowerCase().trim()||'', f=$('#projectFilter')?.value||'';
 const ps=seed.projects.map(mergedProject).filter(p=>{{
  const match=!q||(`${p.name} ${p.area} ${p.chat_title} ${p.summary}`).toLowerCase().includes(q);
  const filt=!f||(f==='attention'?p.status==='attention':p.priority===f);
  return match&&filt;
 }});
 $('#projectsGrid').innerHTML=ps.map(p=>`<article class="project">
  <div class="project-top"><div><div class="area">${p.area}</div><h3>${p.name}</h3></div><span class="status ${p.status}">${statusLabel(p.status)}</span></div>
  <p>${p.summary}</p>
  <div class="bar" aria-label="Avance ${p.progress}%"><i style="width:${p.progress}%"></i></div>
  <div class="prog"><span>${p.tasks.length-p.pending}/${p.tasks.length} tareas</span><strong>${p.progress}%</strong></div>
  <div class="next"><b>Siguiente</b><p>${p.next}</p></div>
  <div class="project-actions"><button class="btn small primary" data-open="${p.id}" type="button">Abrir</button>${p.repo?`<a class="btn small" href="https://github.com/${p.repo}/actions" target="_blank" rel="noopener">GitHub</a>`:''}</div>
  <div class="source">Fuente: ${p.source} · actualización ${fmtDate(p.updated)}</div>
 </article>`).join('')||'<div class="empty">No hay proyectos con ese filtro.</div>';
}}
function renderPending(){{
 const rows=[];
 seed.projects.forEach(p=>p.tasks.forEach(t=>{{if(!taskDone(t))rows.push({{p,t}});}}));
 rows.sort((a,b)=>priorityScore(b.p)-priorityScore(a.p));
 $('#pendingList').innerHTML=rows.map(({p,t})=>`<label class="pending"><input type="checkbox" data-task="${t.id}"><span><strong>${t.text}</strong><span>${p.name} · ${p.area}</span></span><button class="btn small" data-open="${p.id}" type="button">Ver</button></label>`).join('')||'<div class="empty">No quedan tareas pendientes.</div>';
}}
function renderReminderProjectOptions(){{
 $('#reminderProject').innerHTML='<option value="">General</option>'+seed.projects.map(p=>`<option value="${p.id}">${p.name}</option>`).join('');
}}
function renderReminders(){{
 const list=[...state.reminders].sort((a,b)=>new Date(a.when)-new Date(b.when));
 $('#reminderList').innerHTML=list.map(r=>{{
  const due=new Date(r.when)<=new Date();
  const p=projectById(r.project);
  return `<article class="reminder ${due?'due':''}"><div><strong>${r.text}</strong><span>${fmtDate(r.when)}${p?' · '+p.name:''}</span></div><button class="btn small" data-reminder-delete="${r.id}" type="button">Borrar</button></article>`;
 }}).join('')||'<div class="empty">Todavía no hay recordatorios.</div>';
}}
function renderActivity(){{
 const rows=seed.repositories.map(r=>{{
  const x=live[r.repo];
  if(!x)return `<article class="activity"><strong>${r.name}</strong><span>${r.label} · sin datos todavía</span></article>`;
  const result=x.status==='in_progress'?'en curso':(x.conclusion||x.status);
  return `<article class="activity"><strong>${r.name} · ${x.name||'workflow'}</strong><span>${r.label} · ${result} · ${fmtDate(x.updated_at||x.created_at)}</span>${x.html_url?` · <a href="${x.html_url}" target="_blank" rel="noopener">ver run</a>`:''}</article>`;
 }}).join('');
 $('#activityList').innerHTML=rows;
}}
function renderAll(){{renderMetrics();renderPriority();renderAlerts();renderProjects();renderPending();renderReminders();renderActivity();bindOpeners();}}

function bindOpeners(){{$('[data-open]')}}
function attachOpeners(){{$$('[data-open]').forEach(el=>{{if(el.dataset.bound)return;el.dataset.bound='1';el.addEventListener('click',e=>{{if(e.target.matches('a,input'))return;openProject(el.dataset.open);}});}});}}
const _renderAll=renderAll;
renderAll=function(){{_renderAll();attachOpeners();}};

function openProject(id){{
 const p=projectById(id);if(!p)return;currentProject=p;
 $('#modalArea').textContent=p.area;$('#modalTitle').textContent=p.name;$('#modalSummary').textContent=p.summary;
 const st=$('#modalStatus');st.textContent=statusLabel(p.status);st.className='status '+p.status;
 $('#modalProgress').textContent=`${projectProgress(p)}% · ${p.tasks.filter(taskDone).length}/${p.tasks.length} tareas`;
 $('#modalChecklist').innerHTML=p.tasks.map(t=>`<label class="check"><input type="checkbox" data-modal-task="${t.id}" ${taskDone(t)?'checked':''}><span>${t.text}</span></label>`).join('');
 $('#modalNote').value=state.notes[p.id]||'';
 $('#modalChat').value=state.chats[p.id]||'';
 $('#openChat').href=state.chats[p.id]||'https://chatgpt.com/';
 $('#projectDialog').showModal();
}}
$('#modalClose').addEventListener('click',()=>$('#projectDialog').close());
$('#saveProject').addEventListener('click',()=>{{
 if(!currentProject)return;
 $$('[data-modal-task]').forEach(x=>state.tasks[x.dataset.modalTask]=x.checked);
 state.notes[currentProject.id]=$('#modalNote').value.trim();
 state.chats[currentProject.id]=$('#modalChat').value.trim();
 save();$('#projectDialog').close();renderAll();
}});

document.addEventListener('change',e=>{{
 const box=e.target.closest?.('[data-task]');
 if(box){{state.tasks[box.dataset.task]=box.checked;save();renderAll();}}
}});
document.addEventListener('click',e=>{{
 const del=e.target.closest?.('[data-reminder-delete]');
 if(del){{state.reminders=state.reminders.filter(r=>r.id!==del.dataset.reminderDelete);save();renderReminders();}}
}});
$('#projectSearch').addEventListener('input',renderProjects);$('#projectFilter').addEventListener('change',renderProjects);

$$('[data-nav]').forEach(btn=>btn.addEventListener('click',()=>{{
 $$('[data-nav]').forEach(x=>x.classList.toggle('active',x===btn));
 $$('[data-panel]').forEach(p=>p.classList.toggle('active',p.dataset.panel===btn.dataset.nav));
 window.scrollTo({{top:0,behavior:'smooth'}});
}}));

$('#reminderForm').addEventListener('submit',e=>{{
 e.preventDefault();
 const text=$('#reminderText').value.trim(),when=$('#reminderWhen').value,project=$('#reminderProject').value;
 if(!text||!when)return;
 state.reminders.push({{id:'r'+Date.now(),text,when:new Date(when).toISOString(),project}});
 save();e.target.reset();renderReminders();checkReminders();
}});
async function enableNotifications(){{
 if(!('Notification'in window))return alert('Este navegador no ofrece notificaciones web.');
 const p=await Notification.requestPermission();
 $('#notifyBtn').textContent=p==='granted'?'Avisos activados':'Activar avisos';
}}
$('#notifyBtn').addEventListener('click',enableNotifications);
async function notify(title,body,tag){{
 if(Notification.permission!=='granted')return;
 const reg=await navigator.serviceWorker?.ready;
 if(reg) reg.active?.postMessage({{type:'NOTIFY',title,body,tag}});
 else new Notification(title,{{body}});
}}
function checkReminders(){{
 const now=Date.now();
 state.reminders.forEach(r=>{{
  if(new Date(r.when).getTime()<=now&&!state.notified[r.id]){{
   state.notified[r.id]=true;save();
   notify('Louder Control',r.text,r.id);
  }}
 }});
 renderReminders();
}}
setInterval(checkReminders,60000);

async function fetchLive(){{
 const pill=$('#livePill');pill.querySelector('span').textContent='Actualizando';
 let ok=0;
 await Promise.all(seed.repositories.map(async r=>{{
  try{{
   const res=await fetch(`https://api.github.com/repos/${r.repo}/actions/runs?per_page=1`,{{headers:{{Accept:'application/vnd.github+json'}}}});
   if(!res.ok)throw new Error(res.status);
   const j=await res.json();const x=j.workflow_runs?.[0];
   if(x){{live[r.repo]={{name:x.name,status:x.status,conclusion:x.conclusion,created_at:x.created_at,updated_at:x.updated_at,html_url:x.html_url,run_number:x.run_number}};ok++;}}
  }}catch(err){{console.warn('GitHub',r.repo,err);}}
 }}));
 state.activity={{...live,checked:new Date().toISOString()}};save();
 pill.querySelector('span').textContent=ok?`${ok}/${seed.repositories.length} en vivo`:'Sin conexión';
 renderAll();
}}
$('#refreshLive').addEventListener('click',fetchLive);

$('#exportBtn').addEventListener('click',()=>{{
 const payload={{exported_at:new Date().toISOString(),seed_version:seed.meta.version,state,projects:seed.projects.map(mergedProject),live}};
 const blob=new Blob([JSON.stringify(payload,null,2)],{{type:'application/json'}});
 const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='louder-control-export.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);
}});

window.addEventListener('beforeinstallprompt',e=>{{e.preventDefault();deferredInstall=e;$('#installCard').hidden=false;}});
$('#installBtn').addEventListener('click',async()=>{{if(!deferredInstall)return;deferredInstall.prompt();await deferredInstall.userChoice;deferredInstall=null;$('#installCard').hidden=true;}});
window.addEventListener('appinstalled',()=>$('#installCard').hidden=true);

if('serviceWorker'in navigator)navigator.serviceWorker.register('./sw.js').catch(console.warn);
if(state.activity&&state.activity.checked){{
 live={{...state.activity}};delete live.checked;
}}
renderReminderProjectOptions();renderAll();checkReminders();fetchLive();
</script>
</body>
</html>"""
    (OUT / "index.html").write_text(html_doc, encoding="utf-8")
    print(f"Louder Control built: {len(data.get('projects') or [])} projects")


if __name__ == "__main__":
    main()

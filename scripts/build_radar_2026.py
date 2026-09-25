#!/usr/bin/env python3
"""Build the internal Louder Radar 2026 dashboard into docs/radar-2026/."""

from __future__ import annotations

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "radar_2026.json"
OUT = ROOT / "docs" / "radar-2026"


def esc(v: object) -> str:
    return html.escape(str(v or ""), quote=True)


def main() -> None:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    tracks = data.get("tracks") or []
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "data.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    rows = []
    for t in tracks:
        src = (t.get("sources") or {}).get("musicbrainz") or "#"
        rows.append(f"""
<article class="track" data-track
 data-search="{esc((t.get('artist') or '') + ' ' + (t.get('title') or ''))}"
 data-status="{esc(t.get('download_status'))}"
 data-availability="{esc(t.get('availability') or 'released')}"
 data-fit="{esc(t.get('louder_fit'))}">
  <div class="date">{esc(t.get('original_release_date'))}</div>
  <div class="main">
    <strong>{esc(t.get('artist'))}</strong>
    <span>{esc(t.get('title'))}</span>
    <small>{esc(t.get('id'))}</small>
  </div>
  <div><span class="pill fit-{esc(t.get('louder_fit'))}">Louder: {esc(t.get('louder_fit'))}</span></div>
  <div><span class="pill st-{esc(t.get('download_status'))}">{esc(t.get('download_status'))}</span></div>
  <div class="actions">
    <a href="{esc(src)}" target="_blank" rel="noopener">Ver fuente</a>
    <button type="button" data-copy="{esc(t.get('id'))}">Copiar ID</button>
  </div>
</article>""")

    stats = data.get("stats") or {}
    html_doc = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Radar Louder 2026</title>
<style>
:root{{--bg:#0b0b0d;--panel:#141417;--text:#f4f4f2;--muted:#a3a3aa;--line:#2a2a30;--accent:#cbff00}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--text);font-family:Arial,Helvetica,sans-serif}}
.wrap{{max-width:1280px;margin:auto;padding:32px 18px 80px}}
.top{{display:flex;justify-content:space-between;gap:20px;align-items:end;flex-wrap:wrap}}
h1{{font-size:clamp(36px,7vw,82px);margin:0;letter-spacing:-.05em;line-height:.9}}
.kicker{{text-transform:uppercase;letter-spacing:.16em;color:var(--accent);font-weight:800}}
.note{{color:var(--muted);max-width:760px;line-height:1.5}}
.stats{{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px;margin:26px 0}}
.stat{{background:var(--panel);border:1px solid var(--line);padding:16px;border-radius:14px}}
.stat strong{{display:block;font-size:28px}} .stat span{{color:var(--muted);font-size:12px;text-transform:uppercase}}
.tools{{display:flex;gap:10px;flex-wrap:wrap;position:sticky;top:0;background:rgba(11,11,13,.92);padding:12px 0;backdrop-filter:blur(10px);z-index:2}}
input,select{{background:var(--panel);border:1px solid var(--line);color:var(--text);padding:12px;border-radius:10px}}
input{{flex:1;min-width:220px}}
.track{{display:grid;grid-template-columns:110px minmax(260px,1fr) 130px 130px 180px;gap:16px;align-items:center;padding:16px 0;border-bottom:1px solid var(--line)}}
.main strong,.main span,.main small{{display:block}} .main span{{font-size:18px;margin:4px 0}} .main small{{color:var(--muted)}}
.date{{font-variant-numeric:tabular-nums;color:var(--muted)}}
.pill{{display:inline-block;padding:7px 9px;border:1px solid var(--line);border-radius:999px;font-size:12px}}
.fit-yes,.st-downloaded,.st-programmed{{border-color:var(--accent)}} .fit-review,.st-pending{{color:#ffd36a}}
.actions{{display:flex;gap:8px;flex-wrap:wrap}} a,button{{background:none;color:var(--text);border:1px solid var(--line);padding:8px 10px;border-radius:8px;text-decoration:none;cursor:pointer}}
.empty{{padding:50px 0;color:var(--muted)}}
@media(max-width:850px){{.stats{{grid-template-columns:repeat(2,1fr)}}.track{{grid-template-columns:1fr 1fr}}.main{{grid-column:1/-1;grid-row:1}}}}
</style>
</head>
<body>
<main class="wrap">
  <div class="top">
    <div><div class="kicker">Control interno · solo 2026</div><h1>Radar Louder</h1></div>
    <p class="note">Canciones cuya primera publicación registrada es 2026. Reediciones, remasters y material originalmente publicado antes de 2026 quedan fuera o pasan a revisión.</p>
  </div>
  <section class="stats">
    <div class="stat"><strong>{len(tracks)}</strong><span>detectadas</span></div>
    <div class="stat"><strong>{stats.get('pending',0)}</strong><span>por descargar</span></div>
    <div class="stat"><strong>{stats.get('downloaded',0)}</strong><span>descargadas</span></div>
    <div class="stat"><strong>{stats.get('programmed',0)}</strong><span>programadas</span></div>
    <div class="stat"><strong>{stats.get('review_queue',0)}</strong><span>revisar</span></div>
    <div class="stat"><strong>{stats.get('upcoming',0)}</strong><span>próximamente</span></div>
  </section>
  <div class="tools">
    <input id="q" placeholder="Buscar artista o canción…">
    <select id="status"><option value="">Todos los estados</option><option value="pending">por descargar</option><option value="downloaded">descargada</option><option value="programmed">programada</option><option value="review">revisar</option><option value="upcoming">próximamente</option><option value="discarded">descartada</option></select>
    <select id="fit"><option value="">Todo Louder</option><option value="yes">sí encaja</option><option value="review">revisar</option><option value="no">no</option></select>
  </div>
  <section id="tracks">{"".join(rows) if rows else '<div class="empty">El radar todavía no ha ejecutado su primera recolección.</div>'}</section>
</main>
<script>
const q=document.querySelector('#q'), status=document.querySelector('#status'), fit=document.querySelector('#fit');
function apply(){{
  const needle=q.value.toLowerCase().trim();
  document.querySelectorAll('[data-track]').forEach(el=>{{
    const ok=(!needle||el.dataset.search.toLowerCase().includes(needle))
      &&(!status.value||el.dataset.status===status.value)
      &&(!fit.value||el.dataset.fit===fit.value);
    el.hidden=!ok;
  }});
}}
[q,status,fit].forEach(x=>x.addEventListener('input',apply));
document.querySelectorAll('[data-copy]').forEach(btn=>btn.addEventListener('click',async()=>{{
  await navigator.clipboard.writeText(btn.dataset.copy); btn.textContent='ID copiado';
  setTimeout(()=>btn.textContent='Copiar ID',1200);
}}));
</script>
</body></html>"""
    (OUT / "index.html").write_text(html_doc, encoding="utf-8")
    print(f"Radar 2026 built: {len(tracks)} tracks")


if __name__ == "__main__":
    main()

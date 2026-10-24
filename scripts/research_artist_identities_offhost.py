#!/usr/bin/env python3
"""Louder artists: lightweight OFF-HOST identity research. Never writes to WordPress."""
import json, os, re, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "artists.json"
STATE = ROOT / "data" / "identity_research_progress.json"
OUT = ROOT / "artifacts" / "artist-review"
OUT.mkdir(parents=True, exist_ok=True)

def names_from(data):
    if isinstance(data, list):
        for row in data:
            if isinstance(row, str): yield row
            elif isinstance(row, dict):
                for field in ("name", "artist", "artist_name", "title"):
                    if isinstance(row.get(field), str) and row[field].strip():
                        yield row[field]; break
    elif isinstance(data, dict):
        for key in ("artists", "items", "rows", "data"):
            if isinstance(data.get(key), (list, dict)):
                yield from names_from(data[key]); return
        for key, row in data.items():
            if isinstance(row, dict):
                yield row.get("name") or row.get("artist") or row.get("artist_name") or key

def normalize(s):
    return re.sub(r"\s+", " ", str(s).strip()).casefold()

def get_json(url):
    req = Request(url, headers={"User-Agent": "Louder-ArtistResearch/1.1 (https://loudermx.com)", "Accept": "application/json"})
    with urlopen(req, timeout=12) as response:
        return json.load(response)

def suspicious_name(name):
    """Do not assign external identities to obvious import/track-number artifacts."""
    cleaned = name.strip()
    # Explicitly retained numeric artist 424 must not be discarded.
    if re.fullmatch(r"\\d{3,}", cleaned) and cleaned not in {"424"}:
        return True
    if re.match(r"^\\.\\s+\\S", cleaned):
        return True
    if re.match(r"^0\\d{1,2}\\s+\\S", cleaned):
        return True
    return False

def lookup(name):
    if suspicious_name(name):
        return {"name": name, "status": "manual_review", "reason": "suspicious_import_name", "matches": 0}
    url = "https://musicbrainz.org/ws/2/artist/?" + urlencode({"query": 'artist:"' + name.replace('"', "") + '"', "fmt": "json", "limit": 8})
    artists = get_json(url).get("artists", [])
    exact = [r for r in artists if normalize(r.get("name", "")) == normalize(name)]
    if len(exact) != 1:
        return {"name": name, "status": "manual_review", "reason": "ambiguous_or_missing", "matches": len(exact)}
    match = exact[0]
    mbid = str(match.get("id") or "")
    result = {"name": name, "status": "identity_candidate_only", "mbid": mbid, "type": match.get("type", ""),
              "country": match.get("country", ""), "disambiguation": match.get("disambiguation", ""),
              "genres": [g.get("name") for g in match.get("genres", []) if g.get("name")],
              "source": "https://musicbrainz.org/artist/" + mbid}
    # Information remains a review candidate, never an automatically verified biography.
    time.sleep(1.1)
    try:
        detail = get_json("https://musicbrainz.org/ws/2/artist/" + mbid + "?inc=url-rels+genres&fmt=json")
        relations = detail.get("relations", [])
        links = []
        for rel in relations:
            resource = str((rel.get("url") or {}).get("resource") or "")
            if resource.startswith("https://") and any(host in resource for host in (
                "wikipedia.org/wiki/", "wikidata.org/wiki/", "bandcamp.com", "instagram.com/",
                "facebook.com/", "youtube.com/", "soundcloud.com/", "musicbrainz.org/")):
                links.append({"type": rel.get("type", ""), "url": resource})
        result["evidence_links"] = links[:20]
        result["genres"] = result["genres"] or [g.get("name") for g in detail.get("genres", []) if g.get("name")]
        result["life_span"] = detail.get("life-span", {})
    except Exception as exc:
        result["details_warning"] = str(exc)[:160]
    return result

def main():
    data = json.loads(DATA.read_text(encoding="utf-8"))
    names = list(dict.fromkeys(x.strip() for x in names_from(data) if isinstance(x, str) and x.strip()))
    # Canonical alphabetical order makes each hourly slot deterministic across runs.
    names.sort(key=normalize)
    if not names: raise SystemExit("No artist names found; no changes published.")
    batch = max(1, min(25, int(os.environ.get("BATCH_SIZE", "20"))))
    try:
        state = json.loads(STATE.read_text(encoding="utf-8"))
        if not isinstance(state, dict): state = {}
    except (FileNotFoundError, ValueError):
        state = {}
    previous = state.get("artists") if isinstance(state.get("artists"), dict) else {}
    cursor = max(0, int(state.get("cursor", 0))) % len(names)
    slot = cursor // batch
    selected = [names[(cursor + i) % len(names)] for i in range(min(batch, len(names)))]
    out = {"generated_at": datetime.now(timezone.utc).isoformat(), "source": "GitHub Actions; WordPress untouched",
           "batch": slot, "catalog_size": len(names), "records": []}
    for name in selected:
        try: out["records"].append(lookup(name))
        except Exception as exc:
            out["records"].append({"name": name, "status": "retry", "error": str(exc)[:180]})
        time.sleep(1.15)  # MusicBrainz max 1 request/sec
    target = OUT / "identity-candidates.json"
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    for row in out["records"]:
        key = normalize(row["name"])
        old = previous.get(key, {})
        if row["status"] != "retry" or not old:
            previous[key] = row
    STATE.write_text(json.dumps({"cursor": (cursor + len(selected)) % len(names),
                                  "total_catalog": len(names), "updated_at": out["generated_at"],
                                  "artists": previous}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not out["records"]:
        raise SystemExit("Empty batch: inspect catalog format")
    counts = {s: sum(row["status"] == s for row in out["records"]) for s in ("identity_candidate_only", "manual_review", "retry")}
    print("No WordPress writes. Candidate identities require editorial verification.", counts)
    if counts["retry"] == len(selected):
        raise SystemExit("All MusicBrainz requests failed; report retained for inspection")
    with open(os.environ.get("GITHUB_STEP_SUMMARY", "/dev/null"), "a", encoding="utf-8") as summary:
        summary.write(f"### Louder: revisión externa de identidades\nProcesados: {len(selected)} / {len(names)}. Candidatos: {counts['identity_candidate_only']}; revisión: {counts['manual_review']}; reintentos: {counts['retry']}. Ninguna publicación automática.\n")

if __name__ == "__main__": main()

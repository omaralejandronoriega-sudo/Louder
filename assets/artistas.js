(() => {
  "use strict";

  const ARTISTS_ORIGIN = "https://artistas.loudermx.com";
  const q = (s, root = document) => root.querySelector(s);
  const qa = (s, root = document) => Array.from(root.querySelectorAll(s));

  function normalize(value) {
    const raw = String(value || "").trim();
    const normal = raw
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, " ")
      .trim();
    if (normal) return normal;
    return "symbol:" + Array.from(raw).map((ch) => ch.codePointAt(0).toString(16)).join("-");
  }

  const months = { ene:0,feb:1,mar:2,abr:3,may:4,jun:5,jul:6,ago:7,sep:8,oct:9,nov:10,dic:11 };
  function parseLouderDate(value) {
    const raw = String(value || "").trim().toLowerCase();
    if (!raw) return 0;
    const iso = Date.parse(raw);
    if (Number.isFinite(iso)) return iso;
    const m = raw.match(/(\d{1,2})\s+(ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)\s+(\d{4})(?:\s*[·|-]\s*(\d{1,2}):(\d{2}))?/);
    if (!m) return 0;
    return new Date(Number(m[3]), months[m[2]], Number(m[1]), Number(m[4] || 0), Number(m[5] || 0)).getTime();
  }

  const grid = q("[data-artist-grid]");
  if (grid) {
    const search = q("[data-artist-search]");
    const sort = q("[data-artist-sort]");
    const count = q("[data-visible-count]");
    const totalCount = q("[data-total-count]");
    const empty = q("[data-empty]");
    const letters = qa("[data-letter]");
    const more = q("[data-load-more]");
    let activeLetter = "";
    let limit = 120;
    let catalog = qa("[data-artist-card]", grid).map((card) => ({
      name: card.querySelector("h2")?.textContent || "",
      slug: (card.getAttribute("href") || "").replace(/^\.\//, "").replace(/\/$/, ""),
      plays: Number(card.dataset.plays || 0),
      first: card.dataset.first || "",
      last: card.dataset.last || "",
      image: card.querySelector("img")?.src || "",
    }));
    let filtered = catalog.slice();

    function makeCard(item) {
      const a = document.createElement("a");
      a.className = "artist-card";
      a.href = ARTISTS_ORIGIN + "/artistas/" + item.slug + "/";
      a.dataset.artistCard = "";
      a.dataset.name = normalize(item.name);
      a.dataset.letter = normalize(item.name).slice(0, 1).toUpperCase();
      a.dataset.plays = String(item.plays || 0);
      a.dataset.first = item.first || "";
      a.dataset.last = item.last || "";

      const media = document.createElement("div");
      media.className = "artist-card-media";
      if (item.image) {
        const img = document.createElement("img");
        img.src = item.image;
        img.alt = item.name || "";
        img.loading = "lazy";
        img.decoding = "async";
        media.appendChild(img);
      } else {
        const span = document.createElement("span");
        span.textContent = String(item.name || "?").slice(0, 2);
        media.appendChild(span);
      }

      const body = document.createElement("div");
      body.className = "artist-card-body";
      const h2 = document.createElement("h2");
      h2.textContent = item.name || "";
      const p = document.createElement("p");
      p.textContent = Number(item.plays || 0).toLocaleString("es-MX") +
        " reproducciones · última aparición " + (item.last || "—");
      body.append(h2, p);
      a.append(media, body);
      return a;
    }

    function apply(reset = true) {
      if (reset) limit = 120;
      const term = normalize(search?.value || "");
      filtered = catalog.filter((item) => {
        const name = normalize(item.name);
        const letter = name.slice(0, 1).toUpperCase();
        return (!term || name.includes(term)) && (!activeLetter || letter === activeLetter);
      });

      const key = sort?.value || "az";
      filtered.sort((a, b) => {
        if (key === "plays") return Number(b.plays || 0) - Number(a.plays || 0);
        if (key === "first") return parseLouderDate(a.first) - parseLouderDate(b.first);
        if (key === "last") return parseLouderDate(b.last) - parseLouderDate(a.last);
        return String(a.name || "").localeCompare(String(b.name || ""), "es", { sensitivity:"base", numeric:true });
      });

      const shown = filtered.slice(0, limit);
      const frag = document.createDocumentFragment();
      shown.forEach((item) => frag.appendChild(makeCard(item)));
      grid.replaceChildren(frag);

      if (count) count.textContent = String(shown.length);
      if (totalCount) totalCount.textContent = String(filtered.length);
      if (empty) empty.hidden = filtered.length !== 0;
      if (more) more.hidden = shown.length >= filtered.length;
    }

    search?.addEventListener("input", () => apply(true));
    sort?.addEventListener("change", () => apply(true));
    letters.forEach((button) => {
      button.addEventListener("click", () => {
        activeLetter = button.dataset.letter || "";
        letters.forEach((x) => x.classList.toggle("active", x === button));
        apply(true);
      });
    });
    more?.addEventListener("click", () => {
      limit += 120;
      apply(false);
    });

    q("[data-shuffle]")?.addEventListener("click", () => {
      if (!filtered.length) return;
      const pick = filtered[Math.floor(Math.random() * filtered.length)];
      window.location.href = ARTISTS_ORIGIN + "/artistas/" + pick.slug + "/";
    });

    fetch(new URL("/artists-index.json", ARTISTS_ORIGIN), { cache:"force-cache" })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error("catalog")))
      .then((data) => {
        if (Array.isArray(data?.artists) && data.artists.length) {
          catalog = data.artists;
          apply(true);
        }
      })
      .catch(() => apply(true));
  }

  const currentSlug = q("[data-shuffle-from]")?.dataset.shuffleFrom || "";
  q("[data-shuffle-from]")?.addEventListener("click", async () => {
    try {
      const response = await fetch(new URL("/artists-index.json", ARTISTS_ORIGIN), { cache:"force-cache" });
      if (!response.ok) throw new Error("index");
      const data = await response.json();
      const rows = (data.artists || []).filter((item) => item.slug && item.slug !== currentSlug);
      if (!rows.length) throw new Error("empty");
      const pick = rows[Math.floor(Math.random() * rows.length)];
      window.location.href = ARTISTS_ORIGIN + "/artistas/" + pick.slug + "/";
    } catch (_) {
      window.location.href = ARTISTS_ORIGIN + "/artistas/";
    }
  });

  const galleryButtons = qa("[data-gallery-image]");
  if (galleryButtons.length) {
    const overlay = document.createElement("div");
    overlay.className = "gallery-lightbox";
    overlay.hidden = true;
    overlay.innerHTML = '<button class="gallery-close" type="button" aria-label="Cerrar">×</button><figure><img alt=""><figcaption></figcaption></figure>';
    document.body.appendChild(overlay);
    const image = q("img", overlay);
    const caption = q("figcaption", overlay);

    function closeGallery() {
      overlay.hidden = true;
      image?.removeAttribute("src");
      document.body.classList.remove("gallery-open");
    }

    galleryButtons.forEach((button) => {
      button.addEventListener("click", () => {
        if (!image || !caption) return;
        image.src = button.dataset.full || q("img", button)?.src || "";
        image.alt = q("img", button)?.alt || "";
        caption.textContent = button.dataset.caption || "";
        overlay.hidden = false;
        document.body.classList.add("gallery-open");
      });
    });
    q(".gallery-close", overlay)?.addEventListener("click", closeGallery);
    overlay.addEventListener("click", (event) => { if (event.target === overlay) closeGallery(); });
    document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !overlay.hidden) closeGallery(); });
  }

  const trackList = q("[data-track-list]");
  if (trackList) {
    const PER_PAGE = 10;
    const allRows = qa("[data-track]", trackList);
    const section = trackList.closest(".section") || trackList.parentElement;
    const albumFilter = q("[data-track-album-filter]", section);
    let page = 1;
    let nav = trackList.nextElementSibling?.matches?.("[data-track-pagination]") ? trackList.nextElementSibling : null;
    if (!nav && allRows.length > PER_PAGE) {
      nav = document.createElement("nav");
      nav.className = "lmx-track-pagination";
      nav.dataset.trackPagination = "1";
      nav.innerHTML = '<div class="lmx-track-pagination-info"></div><div class="lmx-track-pagination-buttons"></div>';
      trackList.insertAdjacentElement("afterend", nav);
    }
    const render = () => {
      const selected = albumFilter?.value || "__all__";
      const rows = allRows.filter((row) => selected === "__all__" || row.dataset.album === selected);
      const pages = Math.max(1, Math.ceil(rows.length / PER_PAGE));
      page = Math.min(Math.max(1, page), pages);
      const start = (page - 1) * PER_PAGE;
      const end = Math.min(start + PER_PAGE, rows.length);
      allRows.forEach((row) => { row.hidden = true; });
      rows.forEach((row, i) => { row.hidden = i < start || i >= end; });
      if (!nav) return;
      nav.hidden = pages <= 1;
      const info = q(".lmx-track-pagination-info", nav);
      const buttons = q(".lmx-track-pagination-buttons", nav);
      if (info) info.textContent = rows.length ? `${start + 1}–${end} de ${rows.length} canciones` : "0 canciones";
      if (buttons) {
        const parts = [];
        if (pages > 1) {
          parts.push(`<button class="lmx-track-page" type="button" data-page="${page-1}" ${page===1?"disabled":""}>←</button>`);
          let from = Math.max(1, page - 2);
          let to = Math.min(pages, from + 4);
          from = Math.max(1, to - 4);
          for (let n=from;n<=to;n++) parts.push(`<button class="lmx-track-page ${n===page?"active":""}" type="button" data-page="${n}">${n}</button>`);
          parts.push(`<button class="lmx-track-page" type="button" data-page="${page+1}" ${page===pages?"disabled":""}>→</button>`);
        }
        buttons.innerHTML = parts.join("");
      }
    };
    nav?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-page]");
      if (!button || button.disabled) return;
      page = Number(button.dataset.page || 1);
      render();
    });
    albumFilter?.addEventListener("change", () => { page = 1; render(); });
    render();
  }

  const navToggle = q("[data-nav-toggle]");
  navToggle?.addEventListener("click", () => {
    const nav = q("[data-main-nav]");
    const open = nav?.classList.toggle("open") || false;
    navToggle.setAttribute("aria-expanded", open ? "true" : "false");
  });

  const searchToggle = q("[data-site-search]");
  const searchPanel = q("[data-site-search-panel]");
  searchToggle?.addEventListener("click", () => {
    if (!searchPanel) return;
    searchPanel.hidden = !searchPanel.hidden;
    if (!searchPanel.hidden) q('input[name="s"]', searchPanel)?.focus();
  });

  let artistIndexPromise = null;
  function artistIndex() {
    if (!artistIndexPromise) {
      const indexUrl = new URL("/artists-index.json", ARTISTS_ORIGIN);
      artistIndexPromise = fetch(indexUrl.href, { cache:"force-cache" })
        .then((r) => r.ok ? r.json() : Promise.reject(new Error("artist-index")))
        .catch(() => ({ artists:[], aliases:{} }));
    }
    return artistIndexPromise;
  }

  function artistSlugFor(name, index) {
    const key = normalize(name);
    const alias = index?.aliases?.[key];
    if (alias) return alias;
    return (index?.artists || []).find((x) => normalize(x.name) === key)?.slug || "";
  }

  async function resolveMissingCover(node) {
    const artist = node.dataset.artist || "";
    const title = node.dataset.title || "";
    const parent = node.closest(".track-cover");
    if (!artist || !title || !parent || parent.dataset.coverResolved === "1") return;
    parent.dataset.coverResolved = "1";
    parent.classList.add("is-resolving");
    try {
      const url = "https://itunes.apple.com/search?media=music&entity=song&limit=8&term=" + encodeURIComponent(artist + " " + title);
      const response = await fetch(url, { cache:"force-cache" });
      if (!response.ok) return;
      const data = await response.json();
      const wantArtist = normalize(artist);
      const wantTitle = normalize(title);
      let best = null;
      let bestScore = -1;
      (Array.isArray(data.results) ? data.results : []).forEach((item) => {
        const a = normalize(item.artistName || "");
        const t = normalize(item.trackName || "");
        let score = 0;
        if (a === wantArtist) score += 100;
        else if (a.includes(wantArtist) || wantArtist.includes(a)) score += 35;
        if (t === wantTitle) score += 120;
        else if (t.includes(wantTitle) || wantTitle.includes(t)) score += 45;
        if (score > bestScore && item.artworkUrl100) { best = item; bestScore = score; }
      });
      if (!best || bestScore < 80) return;
      const img = document.createElement("img");
      img.alt = "";
      img.loading = "lazy";
      img.decoding = "async";
      img.src = String(best.artworkUrl100).replace("100x100bb", "300x300bb");
      parent.replaceChildren(img);
      const album = parent.closest("[data-track]")?.querySelector(".track-album");
      if (album && (!album.textContent.trim() || album.textContent.includes("identificado")) && best.collectionName) album.textContent = best.collectionName;
    } catch (_) {
    } finally {
      parent.classList.remove("is-resolving");
    }
  }

  const missingCovers = qa("[data-missing-cover]");
  if (missingCovers.length) {
    const queue = missingCovers.slice();
    let active = 0;
    const pump = () => {
      while (active < 3 && queue.length) {
        active++;
        resolveMissingCover(queue.shift()).finally(() => { active--; pump(); });
      }
    };
    pump();
  }

  const radio = {
    audio:q("[data-radio-audio]"),
    play:q("[data-radio-play]"),
    track:q("[data-radio-track]"),
    art:q("[data-radio-art]"),
    fallback:q("[data-radio-fallback]"),
    artistLink:q("[data-radio-artist-link]"),
    volume:q("[data-radio-volume]"),
    lastKey:""
  };

  if (radio.audio && radio.volume) {
    radio.audio.volume = Number(radio.volume.value || 0.8);
    radio.volume.addEventListener("input", () => { radio.audio.volume = Number(radio.volume.value || 0.8); });
  }

  function splitRadioMeta(source) {
    const artistField = String(source?.artist || "").trim();
    let raw = String(source?.title || source?.yp_currently_playing || source?.song || "").trim();
    if (artistField && raw) {
      const low = raw.toLowerCase();
      const a = artistField.toLowerCase();
      if (low.startsWith(a + " - ") || low.startsWith(a + " – ") || low.startsWith(a + " — ")) raw = raw.slice(artistField.length + 3).trim();
      return { artist:artistField, title:raw };
    }
    const match = raw.match(/^(.+?)\s+[\-–—]\s+(.+)$/u);
    return match ? { artist:match[1].trim(), title:match[2].trim() } : { artist:"", title:raw };
  }

  async function nowPlaying() {
    if (!radio.track) return;
    const urls = ["https://ec1.yesstreaming.net:2720/status-json.xsl","https://ec1.yesstreaming.net:2725/status-json.xsl"];
    let source = null;
    for (const url of urls) {
      try {
        const response = await fetch(url, { cache:"no-store" });
        if (!response.ok) continue;
        const data = await response.json();
        const src = data?.icestats?.source;
        source = Array.isArray(src) ? src.find((x) => /\/stream(?:$|\?)/i.test(String(x?.listenurl || ""))) || src[0] : src;
        if (source) break;
      } catch (_) {}
    }
    if (!source) return;
    const meta = splitRadioMeta(source);
    if (!meta.title) return;
    const key = normalize(meta.artist + " " + meta.title);
    if (key === radio.lastKey) return;
    radio.lastKey = key;
    radio.track.textContent = meta.artist ? meta.artist + " — " + meta.title : meta.title;

    if (radio.artistLink && meta.artist) {
      const index = await artistIndex();
      const slug = artistSlugFor(meta.artist, index);
      radio.artistLink.hidden = !slug;
      if (slug) radio.artistLink.href = ARTISTS_ORIGIN + "/artistas/" + encodeURIComponent(slug) + "/";
    }

    if (radio.art && radio.fallback) {
      try {
        const search = "https://itunes.apple.com/search?media=music&entity=song&limit=5&term=" + encodeURIComponent((meta.artist || "") + " " + meta.title);
        const response = await fetch(search, { cache:"force-cache" });
        const data = response.ok ? await response.json() : { results:[] };
        const wantArtist = normalize(meta.artist);
        const wantTitle = normalize(meta.title);
        const best = (data.results || []).find((x) => normalize(x.artistName) === wantArtist && normalize(x.trackName) === wantTitle) || (data.results || [])[0];
        if (best?.artworkUrl100) {
          radio.art.src = String(best.artworkUrl100).replace("100x100bb", "300x300bb");
          radio.art.hidden = false;
          radio.fallback.hidden = true;
        } else {
          radio.art.hidden = true;
          radio.fallback.hidden = false;
        }
      } catch (_) {
        radio.art.hidden = true;
        radio.fallback.hidden = false;
      }
    }
  }

  radio.play?.addEventListener("click", async () => {
    if (!radio.audio) return;
    try {
      if (radio.audio.paused) {
        await radio.audio.play();
        radio.play.classList.add("is-playing");
        radio.play.setAttribute("aria-label","Pausar Louder Radio");
      } else {
        radio.audio.pause();
        radio.play.classList.remove("is-playing");
        radio.play.setAttribute("aria-label","Reproducir Louder Radio");
      }
    } catch (_) {}
  });

  if (radio.track) {
    nowPlaying();
    window.setInterval(nowPlaying, 15000);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) nowPlaying(); });
  }
})();

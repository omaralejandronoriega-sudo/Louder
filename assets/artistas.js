(() => {
  "use strict";

  const q = (s, root = document) => root.querySelector(s);
  const qa = (s, root = document) => Array.from(root.querySelectorAll(s));

  function normalize(value) {
    return String(value || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, " ")
      .trim();
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
    const cards = qa("[data-artist-card]", grid);
    const search = q("[data-artist-search]");
    const sort = q("[data-artist-sort]");
    const count = q("[data-visible-count]");
    const empty = q("[data-empty]");
    const letters = qa("[data-letter]");
    let activeLetter = "";

    function apply() {
      const term = normalize(search?.value || "");
      let visible = cards.filter((card) => {
        const bySearch = !term || (card.dataset.name || "").includes(term);
        const byLetter = !activeLetter || (card.dataset.letter || "") === activeLetter;
        const show = bySearch && byLetter;
        card.hidden = !show;
        return show;
      });

      const key = sort?.value || "az";
      visible.sort((a, b) => {
        if (key === "plays") return Number(b.dataset.plays || 0) - Number(a.dataset.plays || 0);
        if (key === "first") return parseLouderDate(a.dataset.first) - parseLouderDate(b.dataset.first);
        if (key === "last") return parseLouderDate(b.dataset.last) - parseLouderDate(a.dataset.last);
        return (a.dataset.name || "").localeCompare(b.dataset.name || "", "es", { sensitivity:"base", numeric:true });
      });

      const frag = document.createDocumentFragment();
      visible.forEach((card) => frag.appendChild(card));
      cards.filter((card) => card.hidden).forEach((card) => frag.appendChild(card));
      grid.appendChild(frag);
      if (count) count.textContent = String(visible.length);
      if (empty) empty.hidden = visible.length !== 0;
    }

    search?.addEventListener("input", apply);
    sort?.addEventListener("change", apply);
    letters.forEach((button) => {
      button.addEventListener("click", () => {
        activeLetter = button.dataset.letter || "";
        letters.forEach((x) => x.classList.toggle("active", x === button));
        apply();
      });
    });

    q("[data-shuffle]")?.addEventListener("click", () => {
      const visible = cards.filter((card) => !card.hidden);
      if (!visible.length) return;
      window.location.href = visible[Math.floor(Math.random() * visible.length)].href;
    });

    apply();
  }

  const currentSlug = q("[data-shuffle-from]")?.dataset.shuffleFrom || "";
  q("[data-shuffle-from]")?.addEventListener("click", async () => {
    try {
      const base = new URL("../", window.location.href);
      const response = await fetch(base.href, { cache:"force-cache" });
      if (!response.ok) throw new Error("index");
      const source = await response.text();
      const doc = new DOMParser().parseFromString(source, "text/html");
      const links = qa("[data-artist-card]", doc).filter(
        (card) => !card.getAttribute("href")?.includes("/" + currentSlug + "/")
      );
      if (!links.length) return;
      const pick = links[Math.floor(Math.random() * links.length)];
      window.location.href = new URL(pick.getAttribute("href"), base).href;
    } catch (_) {
      window.location.href = "../";
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
    const rows = qa("[data-track]", trackList);
    const buttons = qa("[data-track-sort]");
    const collator = new Intl.Collator("es", { sensitivity:"base", numeric:true });
    const value = (row, key) => {
      if (key === "title") return row.dataset.title || "";
      if (key === "first") return parseLouderDate(row.dataset.first);
      if (key === "last") return parseLouderDate(row.dataset.last);
      return Number(row.dataset.plays || 0);
    };
    function sortTracks(key) {
      const sorted = rows.slice().sort((a, b) => {
        if (key === "title") return collator.compare(value(a, key), value(b, key));
        if (key === "first") return value(a, key) - value(b, key);
        return value(b, key) - value(a, key);
      });
      const frag = document.createDocumentFragment();
      sorted.forEach((row) => frag.appendChild(row));
      trackList.appendChild(frag);
      buttons.forEach((button) => button.classList.toggle("active", button.dataset.trackSort === key));
    }
    buttons.forEach((button) => button.addEventListener("click", () => sortTracks(button.dataset.trackSort || "plays")));
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
      const indexUrl = new URL("/artists-index.json", window.location.origin);
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
      if (slug) radio.artistLink.href = "/artistas/" + slug + "/";
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

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

      visible = visible.sort((a, b) => {
        if ((sort?.value || "az") === "plays") {
          return Number(b.dataset.plays || 0) - Number(a.dataset.plays || 0);
        }
        return (a.dataset.name || "").localeCompare(b.dataset.name || "", "es", {
          sensitivity: "base",
          numeric: true,
        });
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
      const pick = visible[Math.floor(Math.random() * visible.length)];
      window.location.href = pick.href;
    });

    apply();
  }

  const currentSlug = q("[data-shuffle-from]")?.dataset.shuffleFrom || "";
  q("[data-shuffle-from]")?.addEventListener("click", async () => {
    try {
      const base = new URL("../", window.location.href);
      const response = await fetch(base.href, { cache: "force-cache" });
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

  const trackList = q("[data-track-list]");
  if (trackList) {
    const rows = qa("[data-track]", trackList);
    const buttons = qa("[data-track-sort]");

    const collator = new Intl.Collator("es", { sensitivity: "base", numeric: true });
    const value = (row, key) => {
      if (key === "title") return row.dataset.title || "";
      if (key === "first") return Date.parse(row.dataset.first || "") || 0;
      if (key === "last") return Date.parse(row.dataset.last || "") || 0;
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

    buttons.forEach((button) =>
      button.addEventListener("click", () => sortTracks(button.dataset.trackSort || "plays"))
    );
  }
})();

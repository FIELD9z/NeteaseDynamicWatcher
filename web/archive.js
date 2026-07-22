(() => {
  "use strict";

  const root = document.documentElement;
  const body = document.body;
  const searchInput = document.getElementById("search");
  const monthSelect = document.getElementById("month-select");
  const densitySelect = document.getElementById("density-select");
  const themeButton = document.getElementById("theme-toggle");
  const visibleCount = document.getElementById("visible-count");
  const emptyState = document.getElementById("empty-state");
  const filterButtons = [...document.querySelectorAll("[data-filter]")];
  const cards = [...document.querySelectorAll(".event-card")];
  const sections = [...document.querySelectorAll(".month-section")];
  const dialog = document.getElementById("image-dialog");
  const dialogImage = document.getElementById("dialog-image");
  const dialogCaption = document.getElementById("dialog-caption");
  const dialogClose = document.getElementById("dialog-close");

  let activeFilter = "all";

  const normalize = (value) => String(value || "").trim().toLocaleLowerCase();

  function savePreference(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch (_) {
      // The archive remains usable when localStorage is unavailable.
    }
  }

  function readPreference(key, fallback) {
    try {
      return localStorage.getItem(key) || fallback;
    } catch (_) {
      return fallback;
    }
  }

  function applyTheme(theme) {
    root.dataset.theme = theme;
    const label = theme === "dark" ? "切换浅色" : "切换深色";
    if (themeButton) {
      themeButton.setAttribute("aria-label", label);
      themeButton.title = label;
      themeButton.textContent = theme === "dark" ? "☀" : "◐";
    }
    savePreference("archive-theme", theme);
  }

  function applyDensity(density) {
    body.classList.toggle("compact", density === "compact");
    if (densitySelect) densitySelect.value = density;
    savePreference("archive-density", density);
  }

  function cardMatches(card, query) {
    const kinds = new Set((card.dataset.kinds || "").split(/\s+/).filter(Boolean));
    const matchesFilter = activeFilter === "all" || kinds.has(activeFilter);
    const matchesSearch = !query || normalize(card.dataset.search).includes(query);
    return matchesFilter && matchesSearch;
  }

  function refresh() {
    const query = normalize(searchInput ? searchInput.value : "");
    let count = 0;

    cards.forEach((card) => {
      const visible = cardMatches(card, query);
      card.hidden = !visible;
      if (visible) count += 1;
    });

    sections.forEach((section) => {
      const sectionHasVisibleCard = [...section.querySelectorAll(".event-card")].some(
        (card) => !card.hidden
      );
      section.hidden = !sectionHasVisibleCard;
    });

    if (visibleCount) visibleCount.textContent = String(count);
    if (emptyState) emptyState.style.display = count === 0 ? "block" : "none";
  }

  if (searchInput) searchInput.addEventListener("input", refresh);

  filterButtons.forEach((button) => {
    button.addEventListener("click", () => {
      activeFilter = button.dataset.filter || "all";
      filterButtons.forEach((item) => {
        const active = item === button;
        item.classList.toggle("active", active);
        item.setAttribute("aria-pressed", active ? "true" : "false");
      });
      refresh();
    });
  });

  if (monthSelect) {
    monthSelect.addEventListener("change", () => {
      if (!monthSelect.value) return;
      const target = document.getElementById(monthSelect.value);
      if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  if (densitySelect) {
    densitySelect.addEventListener("change", () => applyDensity(densitySelect.value));
  }

  if (themeButton) {
    themeButton.addEventListener("click", () => {
      const next = root.dataset.theme === "dark" ? "light" : "dark";
      applyTheme(next);
    });
  }

  document.querySelectorAll(".media-item").forEach((button) => {
    button.addEventListener("click", () => {
      if (!dialog || !dialogImage) return;
      dialogImage.src = button.dataset.full || "";
      dialogImage.alt = button.dataset.caption || "动态图片";
      if (dialogCaption) dialogCaption.textContent = button.dataset.caption || "动态图片";
      if (typeof dialog.showModal === "function") dialog.showModal();
    });
  });

  if (dialogClose && dialog) dialogClose.addEventListener("click", () => dialog.close());
  if (dialog) {
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
  }

  const preferredTheme = readPreference(
    "archive-theme",
    window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light"
  );
  applyTheme(preferredTheme);
  applyDensity(readPreference("archive-density", "comfortable"));
  refresh();
})();

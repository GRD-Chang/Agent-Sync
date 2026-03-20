(function () {
  const FONT_STORAGE_KEY = "task-bridge.dashboard.font";
  const SCROLL_STORAGE_KEY = "task-bridge.dashboard.scroll";
  const FONT_PRESETS = new Set(["editorial", "sans", "mono"]);

  function normalizeFontPreset(value) {
    return FONT_PRESETS.has(value) ? value : "editorial";
  }

  function syncFontButtons(activePreset) {
    document.querySelectorAll("[data-font-option]").forEach((button) => {
      const isActive = button.getAttribute("data-font-option") === activePreset;
      button.classList.toggle("is-active", isActive);
      button.setAttribute("aria-pressed", String(isActive));
    });
  }

  function applyFontPreset(preset) {
    const normalized = normalizeFontPreset(preset);
    document.body.setAttribute("data-font-preset", normalized);
    syncFontButtons(normalized);
    try {
      window.localStorage.setItem(FONT_STORAGE_KEY, normalized);
    } catch (error) {
      void error;
    }
  }

  function initFontSwitcher() {
    let storedPreset = null;
    try {
      storedPreset = window.localStorage.getItem(FONT_STORAGE_KEY);
    } catch (error) {
      void error;
    }

    applyFontPreset(storedPreset || document.body.getAttribute("data-font-preset") || "editorial");

    document.querySelectorAll("[data-font-option]").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        applyFontPreset(button.getAttribute("data-font-option"));
      });
    });
  }

  function rememberScrollIntent(link) {
    const url = new URL(link.href, window.location.href);
    if (url.origin !== window.location.origin) {
      return;
    }

    const payload = {
      path: url.pathname,
      search: url.search,
      hash: url.hash,
      y: window.scrollY,
    };

    try {
      window.sessionStorage.setItem(SCROLL_STORAGE_KEY, JSON.stringify(payload));
    } catch (error) {
      void error;
    }
  }

  function restoreScrollIntent() {
    let raw = null;
    try {
      raw = window.sessionStorage.getItem(SCROLL_STORAGE_KEY);
    } catch (error) {
      void error;
    }
    if (!raw) {
      if (window.location.hash) {
        scrollToHash(window.location.hash);
      }
      return;
    }

    try {
      const saved = JSON.parse(raw);
      window.sessionStorage.removeItem(SCROLL_STORAGE_KEY);

      const samePath = saved.path === window.location.pathname;
      const sameQuery = saved.search === window.location.search;

      if (saved.hash && samePath && sameQuery) {
        scrollToHash(saved.hash);
        return;
      }

      if (!saved.hash && samePath) {
        window.requestAnimationFrame(() => {
          window.scrollTo({ top: Number(saved.y) || 0, left: 0, behavior: "auto" });
        });
        return;
      }
    } catch (error) {
      void error;
    }

    if (window.location.hash) {
      scrollToHash(window.location.hash);
    }
  }

  function scrollToHash(hash) {
    const target = document.querySelector(hash);
    if (!target) {
      return;
    }
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        target.scrollIntoView({ block: "start" });
      });
    });
  }

  document.addEventListener("click", (event) => {
    const link = event.target.closest("a[href]");
    if (!link) {
      return;
    }

    const href = link.getAttribute("href");
    if (!href || href.startsWith("#")) {
      return;
    }

    const url = new URL(link.href, window.location.href);
    if (url.origin !== window.location.origin) {
      return;
    }

    if (url.hash || url.pathname === window.location.pathname) {
      rememberScrollIntent(link);
    }
  });

  document.addEventListener("DOMContentLoaded", () => {
    initFontSwitcher();
    restoreScrollIntent();
  });
})();

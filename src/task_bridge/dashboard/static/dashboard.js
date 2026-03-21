(function () {
  const FONT_STORAGE_KEY = "task-bridge.dashboard.font";
  const SCROLL_STORAGE_KEY = "task-bridge.dashboard.scroll";
  const DEFAULT_FONT_PRESET = "sans";
  const FONT_PRESETS = new Set(["sans", "editorial", "precision", "mono"]);

  function normalizeFontPreset(value) {
    return FONT_PRESETS.has(value) ? value : DEFAULT_FONT_PRESET;
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
    document.documentElement.setAttribute("data-font-preset", normalized);
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

    applyFontPreset(
      storedPreset ||
        document.documentElement.getAttribute("data-font-preset") ||
        document.body.getAttribute("data-font-preset") ||
        DEFAULT_FONT_PRESET,
    );

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

  function initDispatchTimelines() {
    document.querySelectorAll("[data-dispatch-timeline]").forEach((timeline) => {
      const scrollport = timeline.querySelector("[data-dispatch-scrollport]");
      if (!scrollport) {
        return;
      }

      const olderButton = timeline.querySelector('[data-dispatch-scroll="older"]');
      const newerButton = timeline.querySelector('[data-dispatch-scroll="newer"]');
      const olderFade = timeline.querySelector('.dispatch-timeline-fade--older');
      const newerFade = timeline.querySelector('.dispatch-timeline-fade--newer');
      const newestNode = timeline.querySelector('.dispatch-node.is-newest');
      const scrollStep = () => Math.max(scrollport.clientWidth * 0.72, 220);
      const maxScrollLeft = () => Math.max(0, scrollport.scrollWidth - scrollport.clientWidth);

      const updateChrome = () => {
        const maxLeft = maxScrollLeft();
        const left = scrollport.scrollLeft;
        const nearStart = left <= 12;
        const nearEnd = left >= maxLeft - 12;

        if (olderButton) {
          olderButton.disabled = nearStart;
        }
        if (newerButton) {
          newerButton.disabled = nearEnd;
        }
        if (olderFade) {
          olderFade.classList.toggle('is-visible', !nearStart);
        }
        if (newerFade) {
          newerFade.classList.toggle('is-visible', !nearEnd);
        }
      };

      const scrollByDirection = (direction) => {
        scrollport.scrollBy({ left: scrollStep() * direction, behavior: 'smooth' });
      };

      olderButton?.addEventListener('click', () => scrollByDirection(-1));
      newerButton?.addEventListener('click', () => scrollByDirection(1));

      if (newestNode) {
        window.requestAnimationFrame(() => {
          const newestLeft = newestNode.offsetLeft + newestNode.offsetWidth - scrollport.clientWidth + 24;
          scrollport.scrollLeft = Math.max(0, newestLeft);
          updateChrome();
        });
      } else {
        updateChrome();
      }

      scrollport.addEventListener('scroll', updateChrome, { passive: true });
      window.addEventListener('resize', updateChrome);

      scrollport.addEventListener(
        'wheel',
        (event) => {
          if (Math.abs(event.deltaY) > Math.abs(event.deltaX) || event.shiftKey) {
            scrollport.scrollLeft += event.deltaY || event.deltaX;
            event.preventDefault();
          }
        },
        { passive: false },
      );

      let pointerId = null;
      let dragStartX = 0;
      let dragStartLeft = 0;

      scrollport.addEventListener('pointerdown', (event) => {
        if (event.pointerType === 'mouse' && event.button !== 0) {
          return;
        }
        pointerId = event.pointerId;
        dragStartX = event.clientX;
        dragStartLeft = scrollport.scrollLeft;
        scrollport.classList.add('is-dragging');
        scrollport.setPointerCapture?.(pointerId);
      });

      scrollport.addEventListener('pointermove', (event) => {
        if (pointerId !== event.pointerId) {
          return;
        }
        scrollport.scrollLeft = dragStartLeft - (event.clientX - dragStartX);
      });

      const endDrag = (event) => {
        if (pointerId !== event.pointerId) {
          return;
        }
        scrollport.classList.remove('is-dragging');
        if (scrollport.hasPointerCapture?.(pointerId)) {
          scrollport.releasePointerCapture(pointerId);
        }
        pointerId = null;
        updateChrome();
      };

      scrollport.addEventListener('pointerup', endDrag);
      scrollport.addEventListener('pointercancel', endDrag);
    });
  }



  function initJobScopePanels() {
    const root = document;
    root.querySelectorAll('[data-testid="dashboard-tasks-filter-job"]').forEach((panel) => {
      const toggle = panel.querySelector('[data-job-scope-toggle]');
      const list = panel.querySelector('[data-job-scope-panel]');
      const search = panel.querySelector('[data-job-scope-search]');
      const summary = panel.querySelector('[data-job-scope-summary]');
      const collapsedLabel = panel.querySelector('[data-collapsed-label]');
      const expandedLabel = panel.querySelector('[data-expanded-label]');
      const chips = Array.from(panel.querySelectorAll('[data-job-scope-chip]'));

      if (!toggle || !list || chips.length === 0) {
        return;
      }

      const DEFAULT_VISIBLE = 10;
      let expanded = false;
      let query = '';

      const activeChip = chips.find((chip) => chip.classList.contains('is-active'));
      const activeLabel = activeChip ? (activeChip.querySelector('span')?.textContent || '').trim() : '';

      function updateSummary() {
        const total = chips.length;
        const shown = expanded ? total : Math.min(DEFAULT_VISIBLE, total);
        const suffix = total > shown ? ` · showing ${shown}/${total}` : ` · ${total} jobs`;
        summary && (summary.textContent = activeLabel ? `Selected: ${activeLabel}${suffix}` : `Job scope${suffix}`);
      }

      function applyFilter() {
        const q = query.trim().toLowerCase();
        let visibleCount = 0;
        chips.forEach((chip, index) => {
          const label = (chip.querySelector('span')?.textContent || '').trim();
          const matches = !q || label.toLowerCase().includes(q);
          const inCollapsedWindow = expanded || index < DEFAULT_VISIBLE;
          const show = matches && inCollapsedWindow;
          chip.hidden = !show;
          if (show) {
            visibleCount += 1;
          }
        });
        if (summary) {
          const total = chips.length;
          const windowed = expanded ? total : Math.min(DEFAULT_VISIBLE, total);
          const filterSuffix = q ? ` · ${visibleCount} match${visibleCount === 1 ? '' : 'es'}` : '';
          const suffix = total > windowed ? ` · showing ${windowed}/${total}` : ` · ${total} jobs`;
          summary.textContent = activeLabel ? `Selected: ${activeLabel}${suffix}${filterSuffix}` : `Job scope${suffix}${filterSuffix}`;
        }
      }

      function setExpanded(next) {
        expanded = next;
        toggle.setAttribute('aria-expanded', String(expanded));
        list.classList.toggle('is-collapsed', !expanded);
        list.classList.toggle('is-expanded', expanded);
        if (collapsedLabel && expandedLabel) {
          collapsedLabel.hidden = expanded;
          expandedLabel.hidden = !expanded;
        }
        applyFilter();
      }

      updateSummary();
      setExpanded(false);

      toggle.addEventListener('click', () => {
        setExpanded(!expanded);
      });

      if (search) {
        search.addEventListener('input', () => {
          query = search.value || '';
          // Auto-expand when searching to avoid hiding matches.
          if (query.trim() && !expanded) {
            setExpanded(true);
          } else {
            applyFilter();
          }
        });
      }

      // Ensure keyboard users can reach the scrollport area.
      list.setAttribute('tabindex', '0');
      list.setAttribute('role', 'region');
      list.setAttribute('aria-label', 'Job scope options');
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
    initJobScopePanels();
    initDispatchTimelines();
  });
})();

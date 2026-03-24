(function () {
  const FONT_STORAGE_KEY = "task-bridge.dashboard.font";
  const SCROLL_STORAGE_KEY = "task-bridge.dashboard.scroll";
  const DEFAULT_FONT_PRESET = "sans";
  const FONT_PRESETS = new Set(["sans", "editorial", "precision", "mono"]);
  const UTC_TIME_ZONE = "UTC";

  function normalizeFontPreset(value) {
    return FONT_PRESETS.has(value) ? value : DEFAULT_FONT_PRESET;
  }

  function isValidTimeZone(value) {
    if (!value) {
      return false;
    }
    try {
      Intl.DateTimeFormat("en", { timeZone: value }).format(new Date());
      return true;
    } catch (error) {
      void error;
      return false;
    }
  }

  function resolveDashboardTimeZone() {
    const explicitTimeZone = document.body?.dataset.explicitTimezone || "";
    if (isValidTimeZone(explicitTimeZone)) {
      return explicitTimeZone;
    }

    try {
      const browserTimeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
      if (isValidTimeZone(browserTimeZone)) {
        return browserTimeZone;
      }
    } catch (error) {
      void error;
    }

    return UTC_TIME_ZONE;
  }

  function zonedDateParts(date, timeZone) {
    const formatter = new Intl.DateTimeFormat("en-CA", {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23",
    });
    const values = {};
    formatter.formatToParts(date).forEach((part) => {
      if (part.type !== "literal") {
        values[part.type] = part.value;
      }
    });
    return values;
  }

  function formatDashboardTimestamp(date, timeZone) {
    const parts = zonedDateParts(date, timeZone);
    return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}`;
  }

  function formatDashboardUtcOffset(date, timeZone) {
    const parts = zonedDateParts(date, timeZone);
    const zonedMillis = Date.UTC(
      Number(parts.year),
      Number(parts.month) - 1,
      Number(parts.day),
      Number(parts.hour),
      Number(parts.minute),
      Number(parts.second),
    );
    let offsetMinutes = Math.round((zonedMillis - date.getTime()) / 60000);
    const sign = offsetMinutes >= 0 ? "+" : "-";
    offsetMinutes = Math.abs(offsetMinutes);
    const hours = String(Math.floor(offsetMinutes / 60)).padStart(2, "0");
    const minutes = String(offsetMinutes % 60).padStart(2, "0");
    return `UTC${sign}${hours}:${minutes}`;
  }

  function initDashboardTimes() {
    const resolvedTimeZone = resolveDashboardTimeZone();
    document.documentElement.setAttribute("data-resolved-timezone", resolvedTimeZone);
    document.body?.setAttribute("data-resolved-timezone", resolvedTimeZone);

    document.querySelectorAll("[data-local-time]").forEach((node) => {
      const rawIso = node.getAttribute("datetime") || "";
      if (!rawIso) {
        return;
      }

      const date = new Date(rawIso);
      if (Number.isNaN(date.getTime())) {
        return;
      }

      const display = formatDashboardTimestamp(date, resolvedTimeZone);
      const offset = formatDashboardUtcOffset(date, resolvedTimeZone);
      node.textContent = display;
      node.title = `${display} · ${offset} · ${resolvedTimeZone}`;
      node.setAttribute("data-resolved-offset", offset);
      node.setAttribute("data-resolved-timezone", resolvedTimeZone);
    });
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

  function formatTemplate(template, values) {
    return String(template || "").replace(/\{(\w+)\}/g, (match, key) => {
      return Object.prototype.hasOwnProperty.call(values, key) ? String(values[key]) : match;
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
      const scrollStep = () => Math.max(scrollport.clientWidth * 0.72, 260);
      const maxScrollLeft = () => Math.max(0, scrollport.scrollWidth - scrollport.clientWidth);

      const updateChrome = () => {
        const maxLeft = maxScrollLeft();
        const left = scrollport.scrollLeft;
        const nearOlderEdge = left <= 12;
        const nearNewerEdge = left >= maxLeft - 12;

        if (olderButton) {
          olderButton.disabled = nearOlderEdge;
        }
        if (newerButton) {
          newerButton.disabled = nearNewerEdge;
        }
        if (olderFade) {
          olderFade.classList.toggle('is-visible', !nearOlderEdge);
        }
        if (newerFade) {
          newerFade.classList.toggle('is-visible', !nearNewerEdge);
        }
      };

      const scrollByDirection = (direction) => {
        scrollport.scrollBy({ left: scrollStep() * direction, behavior: 'smooth' });
      };

      olderButton?.addEventListener('click', () => scrollByDirection(-1));
      newerButton?.addEventListener('click', () => scrollByDirection(1));

      if (newestNode) {
        window.requestAnimationFrame(() => {
          const targetLeft = newestNode.offsetLeft + newestNode.offsetWidth - scrollport.clientWidth + 32;
          scrollport.scrollLeft = Math.max(0, targetLeft);
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
          const shouldTranslateY = Math.abs(event.deltaY) > Math.abs(event.deltaX) || event.shiftKey;
          if (!shouldTranslateY) {
            return;
          }
          scrollport.scrollLeft += event.deltaY || event.deltaX;
          event.preventDefault();
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
      const copy = {
        summaryDefault: panel.dataset.summaryDefault || 'Job filter',
        summarySelected: panel.dataset.summarySelected || 'Selected: {active}',
        summaryTotal: panel.dataset.summaryTotal || '{total} jobs',
        summaryWindow: panel.dataset.summaryWindow || 'Showing {shown} of {total}',
        summaryMatches: panel.dataset.summaryMatches || '{count} results',
        optionsLabel: panel.dataset.optionsLabel || 'Job filter options',
      };

      if (!toggle || !list || chips.length === 0) {
        return;
      }

      const DEFAULT_VISIBLE = 10;
      let expanded = false;
      let query = '';

      const activeChip = chips.find((chip) => chip.classList.contains('is-active'));
      const activeLabel = activeChip ? (activeChip.querySelector('span')?.textContent || '').trim() : '';

      function buildSummary(total, shown, visibleCount) {
        const parts = [
          activeLabel ? formatTemplate(copy.summarySelected, { active: activeLabel }) : copy.summaryDefault,
          formatTemplate(total > shown ? copy.summaryWindow : copy.summaryTotal, { shown, total }),
        ];
        if (query.trim()) {
          parts.push(formatTemplate(copy.summaryMatches, { count: visibleCount }));
        }
        return parts.join(' · ');
      }

      function updateSummary() {
        const total = chips.length;
        const shown = expanded ? total : Math.min(DEFAULT_VISIBLE, total);
        if (summary) {
          summary.textContent = buildSummary(total, shown, shown);
        }
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
          summary.textContent = buildSummary(total, windowed, visibleCount);
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
      list.setAttribute('aria-label', copy.optionsLabel);
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
    initDashboardTimes();
    initFontSwitcher();
    restoreScrollIntent();
    initJobScopePanels();
    initDispatchTimelines();
  });
})();

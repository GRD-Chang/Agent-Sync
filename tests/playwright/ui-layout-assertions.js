const { expect } = require("@playwright/test");

async function getBox(locator) {
  const rect = await locator.evaluate((node) => {
    const box = node.getBoundingClientRect();
    return {
      left: box.left,
      top: box.top,
      right: box.right,
      bottom: box.bottom,
      width: box.width,
      height: box.height,
    };
  });

  if (!rect || rect.width <= 0 || rect.height <= 0) {
    throw new Error("Expected locator to have a non-zero bounding box (element should be visible)");
  }

  return rect;
}

async function expectNoHorizontalOverflow(
  page,
  locator,
  { tolerancePx = 1, allowInternalScroll = false } = {},
) {
  const metrics = await locator.evaluate((node) => {
    const rect = node.getBoundingClientRect();
    return {
      clientWidth: node.clientWidth,
      scrollWidth: node.scrollWidth,
      left: rect.left,
      right: rect.right,
      viewport: window.innerWidth,
    };
  });

  expect(metrics.left).toBeGreaterThanOrEqual(-tolerancePx);
  expect(metrics.right).toBeLessThanOrEqual(metrics.viewport + tolerancePx);

  if (!allowInternalScroll) {
    expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.clientWidth + tolerancePx);
  }

  const pageMetrics = await page.evaluate(() => ({
    viewport: window.innerWidth,
    root: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
  }));
  expect(pageMetrics.root).toBeLessThanOrEqual(pageMetrics.viewport + tolerancePx);
  expect(pageMetrics.body).toBeLessThanOrEqual(pageMetrics.viewport + tolerancePx);
}

async function expectChipsContained(container, chips, { tolerancePx = 1 } = {}) {
  const containerBox = await getBox(container);

  const count = await chips.count();
  for (let i = 0; i < count; i += 1) {
    const chip = chips.nth(i);
    const visible = await chip.evaluate((node) => {
      const style = window.getComputedStyle(node);
      return !(node.hidden || style.display === "none" || style.visibility === "hidden");
    });
    if (!visible) continue;

    const chipBox = await getBox(chip);
    expect(chipBox.left).toBeGreaterThanOrEqual(containerBox.left - tolerancePx);
    expect(chipBox.right).toBeLessThanOrEqual(containerBox.right + tolerancePx);
    expect(chipBox.width).toBeGreaterThan(8);
    expect(chipBox.height).toBeGreaterThan(8);
  }
}

function parseCssColor(value) {
  if (!value) return null;
  const match = value.match(
    /rgba?\(\s*([0-9.]+)[,\s]+([0-9.]+)[,\s]+([0-9.]+)(?:[,\s/]+([0-9.]+))?\s*\)/i,
  );
  if (!match) return null;

  return {
    r: Number(match[1]),
    g: Number(match[2]),
    b: Number(match[3]),
    a: match[4] === undefined ? 1 : Number(match[4]),
  };
}

function compositeOnWhite(color) {
  if (!color) {
    return { r: 255, g: 255, b: 255 };
  }
  const alpha = Number.isFinite(color.a) ? color.a : 1;
  return {
    r: Math.round(color.r * alpha + 255 * (1 - alpha)),
    g: Math.round(color.g * alpha + 255 * (1 - alpha)),
    b: Math.round(color.b * alpha + 255 * (1 - alpha)),
  };
}

function srgbToLinear(channel) {
  const value = channel / 255;
  if (value <= 0.04045) return value / 12.92;
  return ((value + 0.055) / 1.055) ** 2.4;
}

function relativeLuminance(color) {
  return (
    0.2126 * srgbToLinear(color.r) +
    0.7152 * srgbToLinear(color.g) +
    0.0722 * srgbToLinear(color.b)
  );
}

function getContrastRatio(foreground, background) {
  if (!foreground || !background) return 1;
  const lighter = Math.max(relativeLuminance(foreground), relativeLuminance(background));
  const darker = Math.min(relativeLuminance(foreground), relativeLuminance(background));
  return (lighter + 0.05) / (darker + 0.05);
}

async function getTimelineWindowState(
  timeline,
  {
    scrollportSelector = "[data-dispatch-scrollport]",
    cardSelector = ".dispatch-node-link",
    fullyVisibleInsetPx = 4,
    mostlyVisibleRatio = 0.55,
  } = {},
) {
  await expect(timeline).toBeVisible();

  const state = await timeline.evaluate(
    (root, options) => {
      const scrollport = root.querySelector(options.scrollportSelector);
      if (!scrollport) return null;

      const scrollRect = scrollport.getBoundingClientRect();
      const cards = Array.from(root.querySelectorAll(options.cardSelector));

      const cardStates = cards.map((card, index) => {
        const rect = card.getBoundingClientRect();
        const visibleWidth = Math.max(
          0,
          Math.min(rect.right, scrollRect.right) - Math.max(rect.left, scrollRect.left),
        );
        const visibleRatio = rect.width > 0 ? visibleWidth / rect.width : 0;
        const style = window.getComputedStyle(card);
        const agent = card.querySelector(".dispatch-node-agent");
        const taskId = card.querySelector(".dispatch-node-id");
        const agentStyle = agent ? window.getComputedStyle(agent) : style;
        const taskIdStyle = taskId ? window.getComputedStyle(taskId) : style;

        return {
          index,
          testId: card.getAttribute("data-testid") || `card-${index}`,
          ariaCurrent: card.getAttribute("aria-current"),
          width: Number(rect.width) || 0,
          visibleWidth: Number(visibleWidth) || 0,
          visibleRatio: Number(visibleRatio) || 0,
          fullyVisible:
            rect.left >= scrollRect.left + options.fullyVisibleInsetPx &&
            rect.right <= scrollRect.right - options.fullyVisibleInsetPx,
          mostlyVisible: visibleRatio >= options.mostlyVisibleRatio,
          opacity: Number.parseFloat(style.opacity || "1"),
          filter: style.filter,
          backgroundColor: style.backgroundColor,
          agentColor: agentStyle.color,
          taskIdColor: taskIdStyle.color,
        };
      });

      return {
        clientWidth: Number(scrollport.clientWidth) || 0,
        scrollWidth: Number(scrollport.scrollWidth) || 0,
        clientHeight: Number(scrollport.clientHeight) || 0,
        scrollHeight: Number(scrollport.scrollHeight) || 0,
        scrollLeft: Number(scrollport.scrollLeft) || 0,
        maxScrollLeft: Math.max(
          0,
          (Number(scrollport.scrollWidth) || 0) - (Number(scrollport.clientWidth) || 0),
        ),
        overflowX: window.getComputedStyle(scrollport).overflowX,
        overflowY: window.getComputedStyle(scrollport).overflowY,
        cardIds: cardStates.map((card) => card.testId),
        fullyVisibleIds: cardStates.filter((card) => card.fullyVisible).map((card) => card.testId),
        mostlyVisibleIds: cardStates.filter((card) => card.mostlyVisible).map((card) => card.testId),
        cards: cardStates,
      };
    },
    {
      scrollportSelector,
      cardSelector,
      fullyVisibleInsetPx,
      mostlyVisibleRatio,
    },
  );

  if (!state) throw new Error("Expected dispatch timeline scrollport to exist");
  return state;
}

async function expectTimelineRailContinuous(
  timeline,
  {
    scrollportSelector = "[data-dispatch-scrollport]",
    railSelector = ".dispatch-timeline-rail",
    cardSelector = ".dispatch-node-link",
    tolerancePx = 6,
    minOverflowPx = 24,
    maxRailInsetPx = 72,
  } = {},
) {
  await expect(timeline).toBeVisible();

  const cards = timeline.locator(cardSelector);
  const count = await cards.count();
  expect(count).toBeGreaterThan(1);

  const firstBox = await getBox(cards.first());
  const lastBox = await getBox(cards.last());
  expect(firstBox.width).toBeGreaterThan(20);
  expect(firstBox.height).toBeGreaterThan(20);
  expect(lastBox.width).toBeGreaterThan(20);
  expect(lastBox.height).toBeGreaterThan(20);

  const rail = timeline.locator(railSelector);
  await expect(rail).toHaveCount(1);
  const railBox = await getBox(rail);
  expect(railBox.width).toBeGreaterThan(80);

  // Rail should begin near the first card and reach at least near the last card.
  // We compare via viewport boxes because offsetLeft/offsetParent can differ between rail and cards.
  expect(railBox.left).toBeGreaterThanOrEqual(firstBox.left - tolerancePx);
  expect(railBox.left).toBeLessThanOrEqual(firstBox.left + maxRailInsetPx);
  expect(railBox.right).toBeGreaterThanOrEqual(lastBox.right - maxRailInsetPx);

  const metrics = await getTimelineWindowState(timeline, {
    scrollportSelector,
    cardSelector,
  });
  expect(metrics.scrollWidth).toBeGreaterThan(metrics.clientWidth + minOverflowPx);
  expect(metrics.scrollHeight).toBeLessThanOrEqual(metrics.clientHeight + tolerancePx);
  expect(["auto", "scroll", "clip"]).toContain(metrics.overflowX);
  expect(["hidden", "clip", "auto"]).toContain(metrics.overflowY);
}

async function expectTimelineCardsReadable(
  timeline,
  {
    scrollportSelector = "[data-dispatch-scrollport]",
    cardSelector = ".dispatch-node-link",
    minVisibleCards = 1,
    minAgentContrast = 4.2,
    minTaskIdContrast = 3.6,
    minOpacity = 0.92,
  } = {},
) {
  const state = await getTimelineWindowState(timeline, {
    scrollportSelector,
    cardSelector,
  });
  const visibleCards = state.cards.filter((card) => card.fullyVisible || card.mostlyVisible);
  expect(visibleCards.length).toBeGreaterThanOrEqual(minVisibleCards);

  for (const card of visibleCards) {
    const background = compositeOnWhite(parseCssColor(card.backgroundColor));
    const agentColor = compositeOnWhite(parseCssColor(card.agentColor));
    const taskIdColor = compositeOnWhite(parseCssColor(card.taskIdColor));
    expect(card.opacity).toBeGreaterThanOrEqual(minOpacity);
    expect(card.filter).toBe("none");
    expect(getContrastRatio(agentColor, background)).toBeGreaterThanOrEqual(minAgentContrast);
    expect(getContrastRatio(taskIdColor, background)).toBeGreaterThanOrEqual(minTaskIdContrast);
  }

  return state;
}

module.exports = {
  expectNoHorizontalOverflow,
  expectChipsContained,
  getTimelineWindowState,
  expectTimelineRailContinuous,
  expectTimelineCardsReadable,
};

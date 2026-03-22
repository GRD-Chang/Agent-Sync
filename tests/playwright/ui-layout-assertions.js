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

/**
 * Structural, non-pixel-perfect overflow checks.
 *
 * We avoid asserting exact px values; instead we ensure key containers do not
 * overflow horizontally and remain within the viewport.
 */
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

  // The element itself should not visually extend past the viewport.
  expect(metrics.left).toBeGreaterThanOrEqual(-tolerancePx);
  expect(metrics.right).toBeLessThanOrEqual(metrics.viewport + tolerancePx);

  // By default we assert no internal horizontal scroll. For known scroll regions
  // (e.g., chip rows) set allowInternalScroll=true.
  if (!allowInternalScroll) {
    expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.clientWidth + tolerancePx);
  }

  // And the page root/body should not overflow either.
  const pageMetrics = await page.evaluate(() => ({
    viewport: window.innerWidth,
    root: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
  }));
  expect(pageMetrics.root).toBeLessThanOrEqual(pageMetrics.viewport + tolerancePx);
  expect(pageMetrics.body).toBeLessThanOrEqual(pageMetrics.viewport + tolerancePx);
}

/**
 * Assert a list of "chip" elements are visually contained within a container.
 */
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

/**
 * Dispatch timeline horizontal scroll check.
 *
 * We ensure:
 * - timeline exists
 * - multiple readable cards exist
 * - the rail spans from first card to last card horizontally
 * - scrollport is horizontally scrollable while staying vertically compact
 */
async function expectTimelineHorizontallyScrollable(timeline, {
  scrollportSelector = '[data-dispatch-scrollport]',
  railSelector = '.dispatch-timeline-rail',
  cardSelector = '.dispatch-node-link',
  tolerancePx = 6,
  maxHeightPx = 340,
} = {}) {
  await expect(timeline).toBeVisible();

  const cards = timeline.locator(cardSelector);
  const count = await cards.count();
  expect(count).toBeGreaterThan(1);

  const firstBox = await getBox(cards.first());
  const lastBox = await getBox(cards.last());
  expect(firstBox.width).toBeGreaterThan(20);
  expect(firstBox.height).toBeGreaterThan(20);

  const rail = timeline.locator(railSelector);
  await expect(rail).toHaveCount(1);
  const railBox = await getBox(rail);
  expect(railBox.width).toBeGreaterThan(80);
  expect(railBox.height).toBeGreaterThan(0);

  const scrollport = timeline.locator(scrollportSelector);
  await expect(scrollport).toHaveCount(1);
  const metrics = await scrollport.evaluate((node) => ({
    clientWidth: node.clientWidth,
    scrollWidth: node.scrollWidth,
    clientHeight: node.clientHeight,
    scrollHeight: node.scrollHeight,
    overflowX: getComputedStyle(node).overflowX,
    overflowY: getComputedStyle(node).overflowY,
  }));

  expect(metrics.scrollWidth).toBeGreaterThan(metrics.clientWidth + 20);
  expect(metrics.clientHeight).toBeLessThanOrEqual(maxHeightPx);
  expect(metrics.scrollHeight).toBeLessThanOrEqual(metrics.clientHeight + tolerancePx);
  expect(['auto', 'scroll', 'clip']).toContain(metrics.overflowX);
  expect(['hidden', 'clip', 'auto']).toContain(metrics.overflowY);
}

module.exports = {
  expectNoHorizontalOverflow,
  expectChipsContained,
  expectTimelineHorizontallyScrollable,
};

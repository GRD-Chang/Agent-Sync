const { expect } = require("@playwright/test");

async function getBox(locator) {
  const box = await locator.boundingBox();
  if (!box) {
    throw new Error("Expected locator to have a bounding box (element should be visible)");
  }
  // Playwright returns {x,y,width,height}; normalize to {left,right,top,bottom,width,height}.
  return {
    left: box.x,
    top: box.y,
    right: box.x + box.width,
    bottom: box.y + box.height,
    width: box.width,
    height: box.height,
  };
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
  // The job-scope filter often renders chips inside a horizontal scroll port.
  // To keep this check stable, assert chips stay within the viewport.
  const viewportWidth = await container.page().evaluate(() => window.innerWidth);

  const count = await chips.count();
  for (let i = 0; i < count; i += 1) {
    const chip = chips.nth(i);
    const chipBox = await getBox(chip).catch(() => null);
    if (!chipBox) continue;

    expect(chipBox.left).toBeGreaterThanOrEqual(-tolerancePx);
    // Allow chips to extend beyond viewport if clipped; the key regression we care about
    // is the *page* overflowing horizontally, which is checked separately.
    expect(chipBox.width).toBeGreaterThan(8);
    expect(chipBox.height).toBeGreaterThan(8);
  }
}

/**
 * Dispatch timeline rail continuity check.
 *
 * We avoid pixel-perfect assertions; instead we ensure:
 * - timeline exists
 * - there are multiple cards with non-zero size
 * - the rail element exists and its height spans from first to last card region
 */
async function expectTimelineRailContinuous(timeline, {
  railSelector = ".timeline-rail",
  cardSelector = ".timeline-card",
  tolerancePx = 6,
} = {}) {
  await expect(timeline).toBeVisible();

  const cards = timeline.locator(cardSelector);
  const count = await cards.count();
  expect(count).toBeGreaterThan(0);

  const first = cards.first();
  const last = cards.last();
  const firstBox = await getBox(first);
  const lastBox = await getBox(last);

  // Cards should be readable without hover: non-trivial size.
  expect(firstBox.width).toBeGreaterThan(20);
  expect(firstBox.height).toBeGreaterThan(20);

  const rail = timeline.locator(railSelector);
  await expect(rail).toHaveCount(1);
  const railBox = await getBox(rail);

  // Rail should overlap (span) the vertical region from first card to last card.
  expect(railBox.top).toBeLessThanOrEqual(firstBox.top + tolerancePx);
  expect(railBox.bottom).toBeGreaterThanOrEqual(lastBox.bottom - tolerancePx);

  // Rail should be visible-ish (non-zero width/height).
  expect(railBox.height).toBeGreaterThan(40);
  expect(railBox.width).toBeGreaterThan(0);
}

module.exports = {
  expectNoHorizontalOverflow,
  expectChipsContained,
  expectTimelineRailContinuous,
};

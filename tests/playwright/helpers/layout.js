const { expect } = require("@playwright/test");

async function getBoxMetrics(locator) {
  return locator.evaluate((node) => {
    const rect = node.getBoundingClientRect();
    return {
      left: rect.left,
      right: rect.right,
      top: rect.top,
      bottom: rect.bottom,
      width: rect.width,
      height: rect.height,
      clientWidth: node.clientWidth,
      clientHeight: node.clientHeight,
      scrollWidth: node.scrollWidth,
      scrollHeight: node.scrollHeight,
    };
  });
}

async function expectNoHorizontalOverflow(locator, { tolerancePx = 1 } = {}) {
  const metrics = await getBoxMetrics(locator);
  expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.clientWidth + tolerancePx);
}

async function expectBoxWithinBox(inner, outer, { tolerancePx = 1 } = {}) {
  const innerBox = await getBoxMetrics(inner);
  const outerBox = await getBoxMetrics(outer);
  expect(innerBox.left).toBeGreaterThanOrEqual(outerBox.left - tolerancePx);
  expect(innerBox.right).toBeLessThanOrEqual(outerBox.right + tolerancePx);
}

async function expectBoxWithinViewport(locator, { tolerancePx = 1 } = {}) {
  const metrics = await locator.evaluate((node) => {
    const rect = node.getBoundingClientRect();
    return {
      left: rect.left,
      right: rect.right,
      viewport: window.innerWidth,
    };
  });
  expect(metrics.left).toBeGreaterThanOrEqual(-tolerancePx);
  expect(metrics.right).toBeLessThanOrEqual(metrics.viewport + tolerancePx);
}

module.exports = {
  expectNoHorizontalOverflow,
  expectBoxWithinBox,
  expectBoxWithinViewport,
  getBoxMetrics,
};

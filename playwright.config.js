const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./tests/playwright",
  timeout: 30000,
  expect: {
    timeout: 5000,
  },
  fullyParallel: false,
  reporter: [["list"]],
  use: {
    headless: true,
    viewport: { width: 1440, height: 1100 },
    trace: "retain-on-failure",
  },
});

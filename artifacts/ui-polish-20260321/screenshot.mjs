import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const outDir = process.argv[2] || 'artifacts/ui-polish-20260321/before';
fs.mkdirSync(outDir, { recursive: true });

const urls = [
  { name: 'jobs-list-desktop', url: 'http://127.0.0.1:8123/jobs', viewport: { width: 1280, height: 720 } },
  { name: 'job-detail-desktop', url: 'http://127.0.0.1:8123/jobs?job=job-ui-polish-1774109720#job-detail', viewport: { width: 1280, height: 720 } },
  { name: 'jobs-list-mobile', url: 'http://127.0.0.1:8123/jobs', viewport: { width: 390, height: 844 } },
  { name: 'job-detail-mobile', url: 'http://127.0.0.1:8123/jobs?job=job-ui-polish-1774109720#job-detail', viewport: { width: 390, height: 844 } },
];

const browser = await chromium.launch();
const page = await browser.newPage();

for (const item of urls) {
  await page.setViewportSize(item.viewport);
  await page.goto(item.url, { waitUntil: 'networkidle' });
  await page.waitForTimeout(200);
  await page.screenshot({ path: path.join(outDir, `${item.name}.png`), fullPage: true });
  console.log('saved', item.name);
}

await browser.close();

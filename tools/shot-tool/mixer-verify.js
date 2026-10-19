// Behavioral verification for the mixer section's discoverability layer:
// CTA pill starts playback, grid wakes from idle, meters actually dance,
// sliders drive real gains, pause restores the dormant state.
const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const BASE = process.argv[2] || 'http://localhost:8765/';
const OUT = path.join(__dirname, 'out-mixer');
fs.mkdirSync(OUT, { recursive: true });

const sleep = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new',
    args: ['--autoplay-policy=no-user-gesture-required'],
  });
  const page = await browser.newPage();
  const errors = [];
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', e => errors.push('PAGEERROR: ' + e.message));
  await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1.25 });

  const report = {};
  const dbg = () => page.evaluate(() => window.__dmDebug());
  const uiState = () => page.evaluate(() => ({
    ctaVisible: !document.getElementById('dm-cta').classList.contains('hidden'),
    gridIdle: document.getElementById('dm-stems').classList.contains('idle'),
    playBtn: document.getElementById('dm-play').textContent,
    status: document.getElementById('dm-status').textContent,
  }));
  // Max --h across all meter spans — proves the meters are dancing.
  const meterPeak = () => page.evaluate(() =>
    Math.max(...[...document.querySelectorAll('.dm-bars span')]
      .map(s => parseFloat(s.style.getPropertyValue('--h') || '0'))));

  await page.goto(BASE, { waitUntil: 'networkidle0' });
  await page.evaluate(() => document.getElementById('demo-adaptive').scrollIntoView({ block: 'center' }));
  await sleep(1000);
  report.idle = await uiState();
  await page.screenshot({ path: path.join(OUT, '1-mixer-idle.png') });

  // ---- CTA click starts the mix ----
  await page.click('#dm-cta-btn');
  await page.waitForFunction(() => window.__dmDebug().playing, { timeout: 20000 });
  await sleep(1200);
  report.afterCta = await uiState();
  report.metersDancing = await meterPeak();
  report.gainsAtFull = (await dbg()).gains;
  await page.screenshot({ path: path.join(OUT, '2-mixer-playing.png') });

  // ---- Slider drives a real gain ----
  await page.evaluate(() => {
    const s = document.querySelector('.dm-vol[data-stem="drums"]');
    s.value = 20;
    s.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await sleep(400); // 0.08s ramp + margin
  report.drumsAfterSlider = +((await dbg()).gains.drums).toFixed(2);

  // ---- Mute kills it, solo isolates ----
  await page.click('.dm-mute[data-stem="vocals"]');
  await sleep(1300);
  report.vocalsAfterMute = +((await dbg()).gains.vocals).toFixed(2);

  // ---- Pause restores the dormant state ----
  await page.click('#dm-play');
  await sleep(400);
  report.afterPause = await uiState();
  await page.screenshot({ path: path.join(OUT, '3-mixer-paused.png') });

  // ---- Game section CTA still intact (shared styles) ----
  await page.evaluate(() => document.getElementById('demo-game').scrollIntoView({ block: 'center' }));
  await sleep(600);
  report.gameCtaStillThere = await page.$eval('#dg-cta', el => !el.classList.contains('hidden'));

  report.consoleErrors = errors.filter(e => !e.includes('_vercel') && !e.includes('favicon'));
  console.log(JSON.stringify(report, null, 2));
  await browser.close();
})().catch(e => { console.error('HARNESS FAIL:', e.message); process.exit(1); });

// Behavioral verification for the playable demo-game section on the landing
// page (localhost:8765). Checks the soft-integration contract: no keyboard
// hijacking, wave -> Combat -> win -> Exploration synced to buttons+meters,
// manual buttons still work, stage click starts playback.
const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const BASE = process.argv[2] || 'http://localhost:8765/';
const OUT = path.join(__dirname, 'out-landing-game');
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
  const dbg = () => page.evaluate(() => window.__dgDebug());
  const drumLevel = () => page.$eval('#dg-meter-drums', el => el.style.getPropertyValue('--level'));
  // Reads back the real canvas buffer — proves pixels were actually drawn.
  const canvasHasInk = () => page.evaluate(() => {
    const c = document.getElementById('dg-canvas');
    if (!c || !c.width || !c.height) return { w: c?.width, h: c?.height, ink: false };
    const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
    let ink = 0;
    for (let i = 3; i < d.length; i += 4) if (d[i] > 0) ink++;
    return { w: c.width, h: c.height, ink };
  });

  await page.goto(BASE, { waitUntil: 'networkidle0' });

  // ---- Soft check: arrows scroll the page when the stage isn't focused ----
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('ArrowDown');
  await sleep(400);
  report.pageScrollsWithArrows = await page.evaluate(() => window.scrollY > 0);

  // ---- Reach the section the way a visitor does: scroll, not a hash jump ----
  await page.evaluate(() => document.getElementById('demo-game').scrollIntoView({ block: 'center' }));
  await sleep(1000); // reveal animation settles
  await page.screenshot({ path: path.join(OUT, '1-section-idle.png') });
  report.idle = await dbg();
  report.canvasIdle = await canvasHasInk();
  report.ctaIdle = await page.$eval('#dg-cta', el => ({
    visible: !el.classList.contains('hidden'),
    text: el.textContent.trim(),
  }));
  report.hintHiddenBeforePlay = await page.$eval('#dg-hint', el => el.classList.contains('gone'));

  // ---- Play: waves auto-trigger Combat, buttons + meters follow ----
  await page.click('#dg-play');
  await page.waitForFunction(() => window.__dgDebug().playing, { timeout: 20000 });
  await sleep(300);
  report.playBtnAlone = {
    ctaHidden: await page.$eval('#dg-cta', el => el.classList.contains('hidden')),
    hintShown: await page.$eval('#dg-hint', el => !el.classList.contains('gone')),
  };
  report.drumLevelExplore = await drumLevel();
  await page.waitForFunction(
    () => document.querySelector('.dg-mode.active')?.dataset.mode === 'Combat',
    { timeout: 12000 });
  report.autoWave = await dbg();
  await sleep(1200);
  report.drumLevelCombat = await drumLevel();
  report.intensityMode = await page.$eval('#dg-intensity', el => el.dataset.mode);
  report.statusCombat = await page.$eval('#dg-status', el => el.textContent);
  report.canvasCombat = await canvasHasInk();
  await sleep(400);
  await page.screenshot({ path: path.join(OUT, '2-combat.png') });

  // ---- Hands-free win -> Exploration ----
  await page.waitForFunction(
    () => document.querySelector('.dg-mode.active')?.dataset.mode === 'Exploration',
    { timeout: 25000 });
  report.winReturns = await dbg();
  await sleep(1200);
  report.drumLevelBack = await drumLevel();
  await page.screenshot({ path: path.join(OUT, '3-back-to-explore.png') });

  // ---- Keyboard steering after clicking the stage ----
  const before = (await dbg()).player;
  await page.click('#dg-arena');
  await sleep(150);
  await page.keyboard.down('KeyD');
  await sleep(300);
  const mid = (await dbg()).player;
  await page.keyboard.up('KeyD');
  report.steering = {
    dx: Math.round(mid.x - before.x),
    lean: +mid.angle.toFixed(3),
    hintGone: await page.$eval('#dg-hint', el => el.classList.contains('gone')),
    stageFocused: await page.evaluate(() => document.activeElement?.id === 'dg-stage'),
  };

  // ---- Manual buttons still drive the fight ----
  await page.click('.dg-mode[data-mode="Combat"]');
  await sleep(300);
  report.manualCombat = await dbg();
  await page.click('.dg-mode[data-mode="Exploration"]');
  await sleep(2500); // enemies flee offscreen
  report.manualExplore = await dbg();

  // ---- Pause, then a stage click restarts playback ----
  await page.click('#dg-play');
  await sleep(400);
  report.pausedAfterToggle = !(await dbg()).playing;
  report.ctaBackOnPause = await page.$eval('#dg-cta', el => !el.classList.contains('hidden'));
  await page.click('#dg-arena');
  await sleep(400);
  report.stageClickRestarts = (await dbg()).playing;

  report.consoleErrors = errors.filter(e => !e.includes('_vercel') && !e.includes('favicon'));
  console.log(JSON.stringify(report, null, 2));
  await browser.close();
})().catch(e => { console.error('HARNESS FAIL:', e.message); process.exit(1); });

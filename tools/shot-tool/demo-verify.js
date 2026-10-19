// Behavioral verification for the StemForge adaptive demo (demo/index.html).
// v2: stems are embedded — verifies decode, shared loop lock, the auto wave
// cycle (explore -> combat -> win -> explore), forced waves via Space, keys.
const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const PAGE = 'file:///C:/dev/Projects/adaptive-music-slicer/demo/index.html';
const OUT = path.join(__dirname, 'out-demo');
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
  await page.setViewport({ width: 1600, height: 900, deviceScaleFactor: 1 });

  const report = {};
  const badge = () => page.$eval('#badge', el => el.textContent);
  const gains = () => page.evaluate(() =>
    Object.fromEntries(Object.entries(stems).map(([k, s]) => [k, +s.gainNode.gain.value.toFixed(3)])));

  await page.goto(PAGE, { waitUntil: 'load' });
  await sleep(300);
  await page.screenshot({ path: path.join(OUT, '1-setup.png') });

  await page.click('#start');
  await page.waitForFunction(() => document.getElementById('setup').classList.contains('gone'), { timeout: 15000 });
  await sleep(400);
  report.audio = await page.evaluate(() => ({
    ctxState: audioCtx.state,
    bufferSecs: Object.fromEntries(Object.entries(stems).map(([k, s]) => [k, +s.buffer.duration.toFixed(3)])),
    loopEnds: [...new Set(Object.values(stems).map(s => +s.source.loopEnd.toFixed(4)))],
    looping: Object.values(stems).every(s => s.source.loop),
    exploreGains: Object.fromEntries(Object.entries(stems).map(([k, s]) => [k, +s.gainNode.gain.value.toFixed(3)])),
  }));
  report.activeMeters = await page.$$eval('.meter:not(.inactive)', els => els.length);
  await page.screenshot({ path: path.join(OUT, '2-explore.png') });

  // ---- 2D keyboard control + lean ----
  const before = await page.evaluate(() => ({ x: player.x, y: player.y }));
  await page.keyboard.down('KeyD');
  await sleep(250);
  const midMove = await page.evaluate(() => ({ angle: +player.angle.toFixed(3), vx: Math.round(player.vx) }));
  await sleep(150);
  await page.keyboard.up('KeyD');
  await page.keyboard.down('KeyS');
  await sleep(350);
  await page.keyboard.up('KeyS');
  await sleep(200);
  const after = await page.evaluate(() => ({ x: player.x, y: player.y }));
  report.movement = {
    dx: Math.round(after.x - before.x),
    dy: Math.round(after.y - before.y),
    leanWhileMovingRight: midMove.angle,
    vxWhileMoving: midMove.vx,
  };

  // ---- Auto wave: no input, combat should start on its own (~4s in) ----
  await page.waitForFunction(() => document.getElementById('badge').textContent === 'Combat', { timeout: 8000 });
  report.autoWave = { badge: await badge(), enemies: await page.evaluate(() => enemies.length) };
  await sleep(1200); // let the crossfade finish
  report.combatGains = await gains();
  await sleep(600);
  await page.screenshot({ path: path.join(OUT, '3-fight.png') });

  // ---- Win: all enemies die, music returns to exploration on its own ----
  await page.waitForFunction(() => document.getElementById('badge').textContent === 'Exploration', { timeout: 20000 });
  report.winReturns = { badge: await badge(), enemies: await page.evaluate(() => enemies.length) };
  await sleep(1200);
  report.exploreGainsAfterWin = await gains();
  await page.screenshot({ path: path.join(OUT, '4-back-to-explore.png') });

  // ---- Space forces the next wave immediately ----
  await page.keyboard.press('Space');
  await sleep(250);
  report.forcedWave = { badge: await badge(), mode: await page.evaluate(() => mode) };
  // Space during combat must NOT restart or toggle anything
  await page.keyboard.press('Space');
  await sleep(150);
  report.spaceInCombatIgnored = (await page.evaluate(() => mode)) === 'combat' && (await badge()) === 'Combat';
  await sleep(1000);
  await page.screenshot({ path: path.join(OUT, '5-forced-fight.png') });

  // ---- H / E keys ----
  await page.keyboard.press('KeyH');
  await sleep(100);
  report.legendHidden = await page.$eval('#legend', el => el.classList.contains('gone'));
  await page.keyboard.press('KeyE');
  await sleep(150);
  report.endcardShown = await page.$eval('#endcard', el => el.classList.contains('show'));
  await page.screenshot({ path: path.join(OUT, '6-endcard.png') });
  await page.keyboard.press('KeyE');

  // ---- Second win cycle (bigger wave) also resolves ----
  await page.waitForFunction(() => document.getElementById('badge').textContent === 'Exploration', { timeout: 25000 });
  report.secondWinResolved = true;
  report.waveIndex = await page.evaluate(() => waveIndex);

  report.consoleErrors = errors;
  console.log(JSON.stringify(report, null, 2));
  await browser.close();
})().catch(e => { console.error('HARNESS FAIL:', e.message); process.exit(1); });

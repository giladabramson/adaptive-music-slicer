// Verifies: (1) the mixer discoverability layer is fully reverted,
// (2) the A/B bass tiles are loudness-matched — the louder file plays
// through a <1 trim gain so effective RMS is equal, position-sync intact.
const puppeteer = require('puppeteer-core');
const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const BASE = process.argv[2] || 'http://localhost:8765/';
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
  await page.setViewport({ width: 1440, height: 900 });

  const report = {};
  await page.goto(BASE, { waitUntil: 'networkidle0' });

  // ---- Revert check: no CTA/idle remnants, mixer still plays ----
  report.reverted = await page.evaluate(() => ({
    dmCta: !!document.getElementById('dm-cta'),
    dmDebug: typeof window.__dmDebug,
    idleClass: !!document.querySelector('.dm-stems.idle'),
  }));
  await page.click('#dm-play');
  await page.waitForFunction(() =>
    document.getElementById('dm-play').textContent === 'Pause', { timeout: 20000 });
  await sleep(500);
  report.mixerPlays = await page.$eval('#dm-play', el => el.classList.contains('playing'));
  report.mixerMetersMove = await page.evaluate(() =>
    Math.max(...[...document.querySelectorAll('.dm-bars span')]
      .map(s => parseFloat(s.style.getPropertyValue('--h') || '0'))) > 0);
  await page.click('#dm-play'); // pause again

  // ---- A/B loudness matching on the bass hero tiles ----
  await page.evaluate(() => document.getElementById('demo-stems').scrollIntoView({ block: 'center' }));
  await sleep(600);
  await page.click('.sc-play[data-method="raw"]');
  await page.waitForFunction(() => window.__dsDebug?.().url, { timeout: 20000 });
  await sleep(600);
  const rawState = await page.evaluate(() => window.__dsDebug());
  await page.click('.sc-play[data-method="demucs"]');
  await sleep(800);
  const demucsState = await page.evaluate(() => window.__dsDebug());

  const metrics = demucsState.metrics;
  const rawUrl = Object.keys(metrics).find(u => u.includes('raw'));
  const cleanUrl = Object.keys(metrics).find(u => u.includes('clean'));
  report.ab = {
    rawFinalGain: +rawState.finalGain.toFixed(3),
    demucsFinalGain: +demucsState.finalGain.toFixed(3),
    boost: +rawState.boost.toFixed(3),
    // Bass band identical after trim+boost; loudness target reached.
    effectiveBassRms: {
      raw: +(metrics[rawUrl].bassRms * rawState.finalGain).toFixed(4),
      demucs: +(metrics[cleanUrl].bassRms * demucsState.finalGain).toFixed(4),
    },
    loudestEffectiveRms: +Math.max(
      metrics[rawUrl].rms * rawState.finalGain,
      metrics[cleanUrl].rms * demucsState.finalGain).toFixed(3),
    switchedUrl: demucsState.url,
  };

  // ---- Prompt-edge pair: declared-dB matching (bass same dB in A/B) ----
  await page.evaluate(() => document.getElementById('demo-engineering').scrollIntoView({ block: 'center' }));
  await sleep(600);
  await page.click('.sc-play[data-method="naive"]');
  await page.waitForFunction(() => window.__dsDebug?.().url?.includes('naive'), { timeout: 20000 });
  const naiveState = await page.evaluate(() => window.__dsDebug());
  await page.click('.sc-play[data-method="engineered"]');
  await sleep(800);
  const engState = await page.evaluate(() => window.__dsDebug());
  const dbOf = g => +(20 * Math.log10(g)).toFixed(2);
  const naiveUrl = Object.keys(engState.metrics).find(u => u.includes('naive'));
  report.promptEdge = {
    matchGains: { naive: +naiveState.gain.toFixed(4), engineered: +engState.gain.toFixed(4) },
    boost: +engState.boost.toFixed(3),
    finalGains: { naive: +naiveState.finalGain.toFixed(3), engineered: +engState.finalGain.toFixed(3) },
    // Bass parity must survive the boost: declared -25.0 / -14.4 + final trims
    effectiveBassDb: {
      naive: +(-25.0 + dbOf(naiveState.finalGain)).toFixed(2),
      engineered: +(-14.4 + dbOf(engState.finalGain)).toFixed(2),
    },
    louderThanBefore: {
      naiveNow: +naiveState.finalGain.toFixed(3), naiveWas: 1.5,
      engineeredNow: +engState.finalGain.toFixed(3), engineeredWas: 0.443,
    },
    naiveEffectiveRms: +(engState.metrics[naiveUrl].rms * naiveState.finalGain).toFixed(3),
    switchedUrl: engState.url,
  };

  report.consoleErrors = errors.filter(e => !e.includes('_vercel') && !e.includes('favicon'));
  console.log(JSON.stringify(report, null, 2));
  await browser.close();
})().catch(e => { console.error('HARNESS FAIL:', e.message); process.exit(1); });

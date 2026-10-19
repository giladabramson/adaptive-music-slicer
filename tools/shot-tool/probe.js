const puppeteer = require('puppeteer-core');
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new',
    args: ['--autoplay-policy=no-user-gesture-required'] });
  const page = await browser.newPage();
  page.on('pageerror', e => console.log('PAGEERROR:', e.message));
  await page.setViewport({ width: 1600, height: 900 });
  await page.goto('file:///C:/dev/Projects/adaptive-music-slicer/demo/index.html', { waitUntil: 'load' });
  await page.click('#start');
  await page.waitForFunction(() => document.getElementById('setup').classList.contains('gone'), { timeout: 15000 });
  // skip wave 1 (auto), let it resolve
  await page.waitForFunction(() => document.getElementById('badge').textContent === 'Combat', { timeout: 8000 });
  await page.waitForFunction(() => document.getElementById('badge').textContent === 'Exploration', { timeout: 20000 });
  console.log('wave 1 resolved; forcing wave 2');
  await page.keyboard.press('Space');
  for (let i = 0; i < 14; i++) {
    await sleep(1000);
    console.log(JSON.stringify(await page.evaluate(() => ({
      mode, wave: waveIndex, W,
      player: Math.round(player.x), cd: +player.cooldown.toFixed(2),
      enemies: enemies.map(e => ({ x: Math.round(e.x), hp: e.hp, entered: lastMs / 1000 >= e.entryAt })),
    }))));
    if (await page.evaluate(() => mode) === 'explore') { console.log('RESOLVED'); break; }
  }
  await browser.close();
})().catch(e => { console.error('FAIL:', e.message); process.exit(1); });

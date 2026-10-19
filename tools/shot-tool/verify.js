// Behavioral verification: console errors, sticky bar, scrollspy,
// smooth-scroll offset, form wiring, demo controls present.
const puppeteer = require('puppeteer-core');
const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';

(async () => {
  const url = process.argv[2];
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new' });
  const page = await browser.newPage();
  const errors = [];
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', e => errors.push('PAGEERROR: ' + e.message));
  await page.setViewport({ width: 1440, height: 900 });
  await page.goto(url, { waitUntil: 'networkidle0' });
  await new Promise(r => setTimeout(r, 800));

  const staticChecks = await page.evaluate(() => ({
    formAction: document.getElementById('interest-form')?.action,
    emailInput: !!document.querySelector('#interest-form input[type="email"]'),
    hiddenFields: [...document.querySelectorAll('#interest-form input[type="hidden"]')].map(i => i.name),
    playButtons: document.querySelectorAll('.da-play').length,
    scPlayTiles: document.querySelectorAll('.sc-play').length,
    dmTabs: document.querySelectorAll('.dm-tab').length,
    statCards: getComputedStyle(document.querySelector('.stat-grid')).gridTemplateColumns.split(' ').length,
    scrollPaddingTop: getComputedStyle(document.documentElement).scrollPaddingTop,
    themeColor: document.querySelector('meta[name="theme-color"]')?.content,
    strategyLink: document.querySelector('.pricing-footnote a')?.href,
    inputFontSize: getComputedStyle(document.querySelector('#interest-form input[type="email"]')).fontSize,
  }));

  // scroll to pricing, let sticky bar + scrollspy react
  await page.evaluate(() => document.getElementById('pricing').scrollIntoView());
  await new Promise(r => setTimeout(r, 1000));
  const scrollChecks = await page.evaluate(() => ({
    stickyVisible: document.getElementById('sticky-bar').dataset.visible,
    activeLink: document.querySelector('.sticky-nav a.active')?.getAttribute('href'),
  }));

  console.log(JSON.stringify({ staticChecks, scrollChecks, consoleErrors: errors.filter(e => !e.includes('_vercel')) }, null, 2));
  await browser.close();
})();

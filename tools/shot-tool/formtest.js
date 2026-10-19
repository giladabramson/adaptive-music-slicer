// Submit one clearly-labeled test entry through the LIVE site's form,
// exactly the way a visitor would (real page, real JS handler).
const puppeteer = require('puppeteer-core');
const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';

(async () => {
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new' });
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });
  await page.goto('https://landing-tau-steel.vercel.app', { waitUntil: 'networkidle0' });
  await page.type('#interest-form input[type="email"]', 'stemforge.form.selftest@gmail.com');
  await page.click('#interest-form button[type="submit"]');
  // wait for the status line to change from "Sending…"
  await page.waitForFunction(() => {
    const s = document.getElementById('interest-status');
    return s && !s.hidden && s.textContent && !s.textContent.includes('Sending');
  }, { timeout: 20000 });
  const result = await page.evaluate(() => {
    const s = document.getElementById('interest-status');
    return { text: s.textContent, kind: s.dataset.kind };
  });
  console.log(JSON.stringify(result));
  await browser.close();
})();

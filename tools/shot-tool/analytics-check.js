// Visits the production landing like a real browser and reports every
// Vercel Analytics request: the script load and the pageview beacon.
const puppeteer = require('puppeteer-core');
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const sleep = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--disable-blink-features=AutomationControlled'] });
  const page = await browser.newPage();
  await page.evaluateOnNewDocument(() => Object.defineProperty(navigator, 'webdriver', { get: () => false }));
  const hits = [];
  page.on('response', r => {
    if (r.url().includes('/_vercel/insights')) {
      hits.push({ status: r.status(), method: r.request().method(), url: r.url().replace('https://landing-tau-steel.vercel.app', '') });
    }
  });
  await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36');
  await page.goto('https://landing-tau-steel.vercel.app/', { waitUntil: 'networkidle0' });
  await sleep(2500); // give the deferred script time to send the view beacon
  console.log(JSON.stringify({ insightsRequests: hits, vaDefined: await page.evaluate(() => typeof window.va) }, null, 2));
  await browser.close();
})().catch(e => { console.error('FAIL:', e.message); process.exit(1); });

// Screenshot harness for the StemForge landing page review.
// Usage: node shoot.js <url> <outdir> [prefix]
const puppeteer = require('puppeteer-core');

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';

async function fullPage(browser, opts) {
  const { name, viewport, mobile, outdir, url, prefix } = opts;
  const page = await browser.newPage();
  await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }]);
  await page.setViewport({ ...viewport, isMobile: !!mobile, hasTouch: !!mobile, deviceScaleFactor: 2 });
  await page.goto(url, { waitUntil: 'networkidle0', timeout: 30000 });
  await new Promise(r => setTimeout(r, 1200));
  // report layout + overflow diagnostics
  const diag = await page.evaluate(() => {
    const wide = [];
    const docW = document.documentElement.clientWidth;
    document.querySelectorAll('body *').forEach(el => {
      const r = el.getBoundingClientRect();
      if (r.width > docW + 1 || r.right > docW + 8) {
        const cs = getComputedStyle(el.parentElement || el);
        wide.push({ tag: el.tagName, cls: (el.className + '').slice(0, 60), w: Math.round(r.width), right: Math.round(r.right), parentOverflowX: cs.overflowX });
      }
    });
    return {
      clientWidth: docW,
      scrollWidth: document.documentElement.scrollWidth,
      bodyScrollWidth: document.body.scrollWidth,
      wide: wide.slice(0, 12),
    };
  });
  console.log(`[${name}] layout=${diag.clientWidth} scrollW=${diag.scrollWidth} bodyScrollW=${diag.bodyScrollWidth}`);
  if (diag.scrollWidth > diag.clientWidth) console.log(`[${name}] OVERFLOW offenders:`, JSON.stringify(diag.wide, null, 1));
  await page.screenshot({ path: `${outdir}\\${prefix}${name}.png`, fullPage: true });
  console.log(`[${name}] saved`);
  await page.close();
}

(async () => {
  const [url, outdir, prefix = ''] = process.argv.slice(2);
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new' });
  await fullPage(browser, { name: 'desktop', viewport: { width: 1440, height: 900 }, outdir, url, prefix });
  await fullPage(browser, { name: 'laptop', viewport: { width: 1280, height: 800 }, outdir, url, prefix });
  await fullPage(browser, { name: 'mobile', viewport: { width: 390, height: 844 }, mobile: true, outdir, url, prefix });
  await browser.close();
})();

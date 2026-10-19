const puppeteer = require('puppeteer-core');
(async () => {
  const b = await puppeteer.launch({ executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', headless: 'new' });
  const p = await b.newPage();
  await p.setViewport({ width: 1440, height: 900 });
  await p.goto('http://localhost:8765', { waitUntil: 'networkidle0' });
  console.log(await p.evaluate(() => ({
    h1s: document.querySelectorAll('h1').length,
    heroes: document.querySelectorAll('.hero').length,
    sections: document.querySelectorAll('section').length,
    footers: document.querySelectorAll('footer').length,
    scrollHeight: document.body.scrollHeight,
  })));
  await b.close();
})();

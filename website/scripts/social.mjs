/* Render the share plate using the same local typography, mark and layered chart as the page. */
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const browser = await chromium.launch({executablePath: process.env.CHROME_PATH, args: ['--no-sandbox']});
try {
  const page = await browser.newPage({viewport:{width:1200,height:630},deviceScaleFactor:1});
  await page.goto(process.env.WEATHER_QA_URL || 'http://127.0.0.1:8783/volparossa-weather/');
  await page.evaluate(() => {
    const chart = document.querySelector('.chart-composition').cloneNode(true);
    document.body.innerHTML = '<article class="cover"><div class="mast"><img src="assets/logo.png" alt="">VOLPAROSSA</div><div class="type"><p>THE ATLAS OF THE ATMOSPHERE</p><h1>VOLPAROSSA<br>Weather</h1><h2>One forecast.<br>More than one app.</h2></div></article>';
    document.querySelector('.cover').append(chart);
  });
  await page.addStyleTag({content:`
    .cover{position:relative;height:630px;overflow:hidden;color:#172e49;background:#f6efdf}
    .mast{position:relative;z-index:2;display:flex;align-items:center;gap:15px;height:75px;padding:0 39px;color:#e4c589;background:#18212b;font:26px var(--serif);letter-spacing:.12em}
    .mast img{width:49px}.cover .type{position:absolute;top:145px;left:48px;z-index:1}
    .type p{font:600 13px Georgia;letter-spacing:.22em;border-bottom:1px solid #a59780;padding-bottom:9px;margin-bottom:25px}
    .type h1{font:600 77px/.9 var(--serif);letter-spacing:-.042em}.type h2{font:400 40px/1.04 var(--serif);margin-top:29px}
    .cover .chart-composition{position:absolute;width:773px;height:555px;inset:75px 0 auto auto}.cover .art{display:block}`});
  await page.evaluate(async()=>{await document.fonts.ready;await Promise.all([...document.images].map(i=>i.decode()));});
  await page.screenshot({path:path.join(root,'assets/atlas/social.jpg'),type:'jpeg',quality:91});
} finally { await browser.close(); }

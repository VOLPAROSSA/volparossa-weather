import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {chromium, firefox, webkit} from 'playwright';
import AxeBuilder from '@axe-core/playwright';
import assert from 'node:assert/strict';

// Poll from the test runner so the native-player checks work with page scripting disabled.
async function waitForMovie(page, condition) {
  const film = page.locator('video');
  for (let i=0; i<100; i++) {
    if (await film.evaluate(condition)) return;
    await new Promise(resolve=>setTimeout(resolve, 150));
  }
  throw Error('Player condition timed out: ' + condition.toString());
}

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const url = process.env.WEATHER_QA_URL || 'http://127.0.0.1:8783/volparossa-weather/';
const out = path.resolve(root, process.env.QA_OUTPUT || 'qa/browser');
fs.mkdirSync(out, {recursive:true});
for (const engine of (process.env.QA_ENGINES || 'chromium,firefox').split(',')) {
  const records = [];
  const browser = await ({chromium,firefox,webkit})[engine].launch(engine==='chromium' ? {executablePath:process.env.CHROME_PATH, args:['--no-sandbox']} : {});
  try {
    const widths = engine==='chromium' ? [1440,390,320,768,1920] : [390,1440];
    const cases = widths.map(width=>({width,mode:'default'}));
    if (engine==='chromium') cases.push({width:1440,mode:'text-200'},{width:320,mode:'text-200'},{width:390,mode:'no-js'});
    for(const {width,mode} of cases) {
      const context = await browser.newContext({viewport:{width,height:width<700?844:900},reducedMotion:'reduce',javaScriptEnabled:mode!=='no-js'});
      const page = await context.newPage(), requests=[], errors=[];
      page.on('request', r=>requests.push(r.url()));
      page.on('pageerror', e=>errors.push(e.message));
      page.on('response', r=>{if(r.status()>=400)errors.push(r.status()+' '+r.url());});
      await page.goto(url,{waitUntil:'networkidle'});
      if(mode==='text-200') await page.locator('html').evaluate(e=>e.style.fontSize='200%');
      await page.evaluate(()=>document.fonts.ready);
      await page.keyboard.press('Tab');assert(await page.locator('.skip-link').evaluate(e=>e===document.activeElement));
      for(const section of await page.locator('main section').all()) {
        await section.scrollIntoViewIfNeeded();
        for(const image of await section.locator('img').all()) {
          if(await image.isVisible()) await image.evaluate(i=>i.decode());
        }
      }
      const dimensions = await page.evaluate(()=>{
        const svg=[...document.querySelectorAll('.peer-drawing svg')].find(s=>s.clientWidth);
        const origin=document.querySelector('.source-slip').getBoundingClientRect(), readers=document.querySelector('.readers').getBoundingClientRect();
        const cloud=document.querySelector('.margin-cloud img').getBoundingClientRect();
        const evidence=document.querySelector('#evidence').getBoundingClientRect();
        return {pageWidth:document.documentElement.scrollWidth, mesh:svg.getAttribute('class'), peers:svg.querySelectorAll('[data-peer]').length, edges:svg.querySelectorAll('[data-edge]').length, cloudWidth:Math.round(cloud.width), evidenceWidth:Math.round(evidence.width), stacked:readers.y>origin.bottom};
      });
      assert(dimensions.pageWidth<=width+1, JSON.stringify({width,mode,dimensions}));
      assert(dimensions.cloudWidth>=dimensions.evidenceWidth*.25,'Cloud illustration must remain legible across layouts');
      assert.equal(dimensions.peers,6);assert.equal(dimensions.edges,8);
      assert.equal(dimensions.mesh,width<=600?'mesh-mobile':'mesh-desktop');
      if(width<=600)assert(dimensions.stacked);
      assert(!requests.some(u=>u.includes('.mp4')),'Video has loaded before activation');
      assert(!requests.some(u=>new URL(u).origin!==new URL(url).origin),'Off-site asset');
      if(mode==='default' && [390,1440].includes(width)) {
        await page.evaluate(()=>{document.activeElement.blur();window.scrollTo(0,0);});
        await page.screenshot({fullPage:true,path:path.join(out,engine+'-'+width+'.png')});
      }
      let accessibility;
      if(mode==='default' && width===1440 && engine==='chromium') {
        const results=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21a','wcag21aa']).analyze();
        accessibility=results.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}));assert.deepEqual(accessibility,[]);
      }
      let playback;
      if(mode==='default' && [390,1440].includes(width) || mode==='no-js') {
        await page.locator('a[href="#demo"]').focus();await page.keyboard.press('Enter');await page.keyboard.press('Tab');
        assert(await page.locator('.film summary').evaluate(e=>e===document.activeElement),'Hero → film summary');
        await page.keyboard.press('Enter');assert(await page.locator('.film').evaluate(e=>e.open));
        const capable=await page.locator('video').evaluate(v=>v.canPlayType('video/mp4; codecs="avc1.42E01E"'));
        if(capable) {
          if(mode==='no-js') {
            await page.keyboard.press('Tab');
            assert(await page.locator('video').evaluate(v=>v===document.activeElement),'Native video focused');
            await page.keyboard.press('Space');
          }
          await waitForMovie(page,v=>v.currentTime>.1);
          await waitForMovie(page,v=>v.textTracks[0]?.cues?.length>0);
          playback=await page.locator('video').evaluate(v=>{v.pause();return {width:v.videoWidth,height:v.videoHeight,duration:v.duration,captions:v.textTracks[0].mode,cues:v.textTracks[0].cues.length};});
          assert.equal(playback.width,1280);assert.equal(playback.height,1440);assert.equal(playback.captions,'showing');
          await page.locator('video').evaluate(v=>{v.currentTime=35;});
          await waitForMovie(page,v=>!v.seeking && Math.abs(v.currentTime-35)<1);
          const box=await page.locator('video').boundingBox();assert(box.width<=width&&box.height<=844);
        }
        else playback={codec:capable,mode};
        const transcript=page.getByRole('link',{name:'Read transcript'});
        for(let i=0;i<20;i++){if(await transcript.evaluate(a=>a===document.activeElement)) break;await page.keyboard.press('Tab');}
        assert(await transcript.evaluate(a=>a===document.activeElement),'Transcript keyboard access');
        await page.keyboard.press('Enter');await page.waitForURL('**/transcript-final.txt');
        assert((await page.locator('body').innerText()).includes('Overmorrow'));
        const fallback=await context.request.get(new URL('assets/demo/weather-demo-0-final.mp4',url).href);
        assert.equal((await fallback.body()).length,3866091);
      }
      assert.deepEqual(errors,[]);
      records.push({engine,width,mode,...dimensions,initialVideoRequests:0,accessibility,playback});
      console.log(engine,width,mode,'OK');
      await context.close();
    }
  } finally { await browser.close(); }
  fs.writeFileSync(path.join(out,engine+'.json'), JSON.stringify(records,null,2)+'\n');
}

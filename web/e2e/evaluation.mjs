// Evaluation view in the real browser: the original lanes still render, and each additional evaluation shows its numbers and its limits.
import puppeteer from 'puppeteer-core'
const BROWSER = process.env.BROWSER_PATH || '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser'
const BASE = process.env.UI_URL || 'http://127.0.0.1:5173'
const out = []
const check = (n, ok, d = '') => { out.push({ name: n, ok: !!ok, detail: d }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${n}${d ? '  ' + d : ''}`) }
const sleep = ms => new Promise(r => setTimeout(r, ms))
const b = await puppeteer.launch({ executablePath: BROWSER, headless: 'new', args: ['--no-sandbox'] })
const p = await b.newPage()
await p.setViewport({ width: 1400, height: 1000 })
const errs = []
p.on('console', m => { if (m.type() === 'error') errs.push(m.text()) })
p.on('pageerror', e => errs.push(String(e)))
try {
  await p.goto(`${BASE}/#/evaluation`, { waitUntil: 'networkidle0' })
  await sleep(1500)
  const h3 = await p.$$eval('h3', h => h.map(x => x.textContent.trim()))
  check('original lanes still render', h3.includes('Algorithm fixtures') && h3.includes('Development footage') && h3.includes('Frozen test footage'), h3.slice(0, 4).join(' | '))
  check('semantic search results are shown with a comparison baseline', h3.includes('Semantic search') && (await p.$$eval('table', t => t.some(x => x.textContent.includes('Class filter only, in time order') && x.textContent.includes('Recall@1')))))
  check('description evaluation shows verdict counts', h3.includes('Video-language descriptions') && (await p.$eval('body', e => e.textContent.includes('MOSTLY SUPPORTED') && e.textContent.includes('INVENTED A DETAIL'))))
  check('cross-camera evaluation says true accuracy is not measured', h3.includes('Appearance-based association') && (await p.$eval('body', e => e.textContent.includes('true cross-camera accuracy is not measured'))))
  check('each additional card carries a limits section', (await p.$$eval('.eval-card details summary', s => s.filter(x => x.textContent.includes('Limits and how to read this')).length)) >= 3)
  const fine = h3.includes('Fine-tuned detector versus pretrained baseline')
  if (fine) check('fine-tuning shows the baseline as unable to detect helmet and head', await p.$eval('body', e => e.textContent.includes('cannot detect (not a COCO class)')))
  await p.setViewport({ width: 390, height: 800 })
  await sleep(500)
  check('no horizontal overflow at 390 px', (await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)) <= 1)
} catch (e) { check('flow aborted', false, e.message) }
check('no console errors', errs.length === 0, errs.slice(0, 2).join(' | '))
await b.close()
process.exit(out.every(x => x.ok) ? 0 : 1)

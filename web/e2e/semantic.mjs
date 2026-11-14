// Semantic search in the real browser against the live stack with the REAL embedding model; also the model-unavailable state.
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
p.on('console', m => { if (m.type() === 'error' && !m.text().includes('503')) errs.push(m.text()) })
p.on('pageerror', e => errs.push(String(e)))
const waitFor = async (fn, ms = 60000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (await fn()) return true; await sleep(250) } throw new Error('timeout') }
const setQuery = async s => {
  await p.evaluate(v => { const i = document.querySelector('#q'); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(i, v); i.dispatchEvent(new Event('input', { bubbles: true })) }, s)
  await p.focus('#q')
  await p.keyboard.press('Enter')
}
const switchMode = () => p.evaluate(() => document.querySelector('input[name=searchmode]:not(:checked)').click())
try {
  await p.goto(BASE, { waitUntil: 'networkidle0' })
  await waitFor(async () => (await p.$$('ul.events li')).length > 0, 30000)
  await switchMode()
  check('mode switch shows semantic mode', await p.$eval('#q', e => e.placeholder.includes('Describe')))
  await setQuery('person carrying a shopping bag')
  await waitFor(async () => (await p.$$('.pill.sem')).length > 0, 120000)
  const pills = await p.$$eval('.pill.sem', ps => ps.map(x => x.textContent))
  check('results carry rank and similarity, best first', pills.length > 1 && pills[0].startsWith('#1 ') && pills[1].startsWith('#2 '), pills.slice(0, 3).join(' | '))
  check('each hit names its best evidence item and timestamp', await p.$$eval('.ev-sem', s => s.length > 0 && s.every(x => /frame at \d+:\d\d/.test(x.textContent))))
  const notice = await p.$eval('.notice.info', e => e.textContent)
  check('score is explained as a ranking aid, not a confidence', notice.includes('not a probability') && notice.includes('not a confidence'))
  check('class words from the text filtered first', notice.includes('Structured filter applied first') && notice.includes('person'), notice.slice(0, 120))
  await p.click('ul.events li button')
  await sleep(500)
  check('a semantic hit opens its evidence like any event', (await p.$$('.frames img')).length > 0)
  await setQuery('unattended bag')
  await waitFor(async () => p.$$eval('.notice.warn', n => n.some(x => x.textContent.includes('Unattended'))), 20000)
  check('unsupported intent is refused with no events ranked', (await p.$$('ul.events li')).length === 0)
  await switchMode()
  await setQuery('person entering restricted zone')
  await sleep(900)
  check('keyword search still works after using semantic', (await p.$eval('.search ~ .notice', e => e.textContent)).includes('Understood'))
  await p.setRequestInterception(true)
  p.on('request', r => (r.url().includes('/search/semantic')
    ? r.respond({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'semantic_unavailable', message: 'The embedding model could not be loaded: offline. Structured search still works.' } }) })
    : r.continue()))
  await switchMode()
  await setQuery('red car')
  await waitFor(async () => p.$$eval('.notice.warn', n => n.some(x => x.textContent.includes('embedding model could not be loaded'))), 20000)
  check('model-unavailable state is explicit and non-blocking', (await p.$$eval('.notice.warn', n => n.some(x => x.textContent.includes('Keyword search and everything else still work')))))
} catch (e) { check('flow aborted', false, e.message) }
check('no console errors', errs.length === 0, errs.slice(0, 2).join(' | '))
await b.close()
process.exit(out.every(x => x.ok) ? 0 : 1)

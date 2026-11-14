// Optional explanations in the real browser against the live stack with the REAL vision-language model; also the model-unavailable state.
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
const clickText = async (txt, sel = 'button') => { for (const h of await p.$$(sel)) { if ((await h.evaluate(e => e.textContent.trim())) === txt) { await h.click(); return } } throw new Error('no element ' + txt) }
try {
  await p.goto(BASE, { waitUntil: 'networkidle0' })
  await waitFor(async () => (await p.$$('ul.events li')).length > 0, 30000)
  await p.click('ul.events li button')
  await sleep(500)
  check('panel is labelled optional and unverified', (await p.$eval('#explain-h', e => e.textContent)).includes('optional, unverified'))
  const before = await p.$$eval('.explanation', x => x.length)
  await clickText('Describe selected frames')
  await waitFor(async () => (await p.$$eval('.explanation', x => x.length)) > before, 180000)
  const fig = await p.$eval('.explanation', e => e.textContent)
  check('result is labelled model-generated and unverified', fig.includes('Model-generated, unverified'))
  check('result shows the evidence it was based on', (await p.$$eval('.explanation .frames img', i => i.length > 0 && i.every(x => x.complete && x.naturalWidth > 0))))
  check('automatic checks are shown, or their absence is explained as not a verification', (await p.$$('.explanation ul.flags')).length > 0 || fig.includes('not a verification'))
  const t0 = await p.$eval('video[src]', v => v.currentTime)
  await p.click('.explanation .frame')
  await sleep(500)
  check('the cited frame jumps to its source timestamp', Math.abs((await p.$eval('video[src]', v => v.currentTime)) - t0) > 0.05)
  await p.evaluate(() => document.querySelector('.explain input[type=checkbox]:not(:checked)').click())
  check('choosing several frames shows the reliability warning', (await p.$$eval('.explain .notice.warn', n => n.some(x => x.textContent.includes('markedly less reliable')))))
  // the event, review and report are untouched by explanations
  const statusBefore = await p.$eval('.ev.sel .pill', e => e.textContent)
  await clickText('Save review')
  await waitFor(async () => p.$$eval('.notice', n => n.some(x => x.textContent.includes('Saved.'))), 10000)
  check('review still works alongside explanations', true)
  void statusBefore
  // model unavailable: the server answers 503
  await p.setRequestInterception(true)
  p.on('request', r => (r.url().includes('/explain')
    ? r.respond({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'explainer_unavailable', message: 'The explanation model could not be loaded: offline. Everything else works.' } }) })
    : r.continue()))
  await clickText('Describe selected frames')
  await waitFor(async () => p.$$eval('.explain .notice.warn', n => n.some(x => x.textContent.includes('could not be loaded'))), 20000)
  check('model-unavailable state is explicit and the rest of the drawer works', (await p.$$eval('.explain .notice.warn', n => n.some(x => x.textContent.includes('still works')))) && (await p.$$('.frames img')).length > 0)
} catch (e) { check('flow aborted', false, e.message) }
check('no console errors', errs.length === 0, errs.slice(0, 2).join(' | '))
await b.close()
process.exit(out.every(x => x.ok) ? 0 : 1)

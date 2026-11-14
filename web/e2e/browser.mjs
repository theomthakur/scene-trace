// Real-browser acceptance flow (G5): upload -> draw zone -> process with the REAL detector -> inspect -> review -> reload -> export.
// Needs the stack running (scripts/dev.sh). Usage: node e2e/browser.mjs /path/to/clip.webm
import puppeteer from 'puppeteer-core'
import fs from 'node:fs'

const BROWSER = process.env.BROWSER_PATH || '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser'
const BASE = process.env.UI_URL || 'http://127.0.0.1:5173'
const clip = process.argv[2]
const results = []
const check = (name, ok, detail = '') => { results.push({ name, ok: !!ok, detail }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  ' + detail : ''}`) }
const sleep = ms => new Promise(r => setTimeout(r, ms))

const browser = await puppeteer.launch({ executablePath: BROWSER, headless: 'new', args: ['--no-sandbox', '--autoplay-policy=no-user-gesture-required'] })
const page = await browser.newPage()
await page.setViewport({ width: 1400, height: 1000 })
const consoleErrors = []
page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()) })
page.on('pageerror', e => consoleErrors.push(String(e)))
const text = async sel => page.$eval(sel, e => e.textContent)
const waitFor = async (fn, ms = 60000, label = 'condition') => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (await fn()) return true; await sleep(250) } throw new Error('timeout waiting for ' + label) }
const clickText = async (txt, sel = 'button') => { const hs = await page.$$(sel); for (const h of hs) { if ((await h.evaluate(e => e.textContent.trim())) === txt) { await h.click(); return true } } throw new Error('no element with text ' + txt) }
const canvasBox = () => page.$eval('canvas', e => { e.scrollIntoView({ block: 'center' }); const b = e.getBoundingClientRect(); return { x: b.x, y: b.y, w: b.width, h: b.height } })
const hasInfo = async s => page.$$eval('.notice.info', (ns, needle) => ns.some(n => n.textContent.includes(needle)), s).catch(() => false)
const painted = async () => page.evaluate(() => { const c = document.querySelector('canvas'); const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++; return n })

try {
  await page.goto(BASE, { waitUntil: 'networkidle0' })
  check('live backend badge', (await text('.badge')).includes('Live backend'))

  // upload
  const input = await page.$('input[type=file]'); await input.uploadFile(clip)
  const NAME = `E2E pedestrian clip ${Date.now()}`
  await page.type('input[name=name]', NAME)
  await clickText('Upload')
  // wait for THIS upload to be selected (earlier uploads may already be in the list) and for its playable version
  await waitFor(async () => (await page.$eval('#player-h', e => e.textContent).catch(() => '')) === NAME && !!(await page.$('video[src]')), 90000, 'this upload to be playable')
  await sleep(500)
  check('upload -> browser-playable derivative', true)

  // draw a zone with real pointer clicks on the canvas
  await clickText('Draw zone')
  let box = await canvasBox()
  for (const [nx, ny] of [[0.35, 0.60], [0.65, 0.60], [0.65, 0.95], [0.35, 0.95]]) { await page.mouse.click(box.x + nx * box.w, box.y + ny * box.h); await sleep(80) }
  check('drawing reports the point count', await page.$$eval('.notice.info', ns => ns.some(n => n.textContent.includes('4 so far'))))
  await clickText('Finish polygon')
  check('polygon added to the zone list', (await page.$$eval('.zlist li', l => l.length)) === 1)
  await clickText('Save zones'); await waitFor(async () => (await text('#zones-h')).includes('v1'), 10000, 'zones saved')
  check('zones saved as version 1', true)
  await clickText('Draw zone'); box = await canvasBox(); await page.mouse.click(box.x + 0.1 * box.w, box.y + 0.1 * box.h); await sleep(150)
  check('a clicked point is counted', await hasInfo('1 so far'))
  await page.mouse.click(box.x + 2, box.y + 2)   // far corner of the stage: inside the video content here (no bars), so it must count
  await sleep(150); check('a second point is counted', await hasInfo('2 so far'))
  await clickText('Undo'); await sleep(150)
  check('undo removes the last drawn point', await hasInfo('1 so far'))
  await clickText('Cancel drawing')
  check('the saved zone is untouched by drawing and cancelling', (await page.$$eval('.zlist li', l => l.length)) === 1 && !(await text('#zones-h')).includes('unsaved'))

  // process with the real detector
  await clickText('Process video')
  await waitFor(async () => (await page.$eval('.runinfo', e => e.textContent).catch(() => '')).includes('completed'), 240000, 'run completed')
  const runText = (await page.$eval('.runinfo', e => e.textContent)).replace(/\s+/g, ' ')
  check('run completed with the real COCO detector', /Detector: fasterrcnn_mobilenet_v3_large_320_fpn COCO_V1/.test(runText), runText.slice(0, 230))
  const nEvents = await page.$$eval('ul.events li', l => l.length)
  check('events are listed', nEvents > 0, `${nEvents} events`)

  // inspect
  await page.click('ul.events li button'); await sleep(700)
  const sel = await page.$eval('.ev.sel .ev-title', e => e.textContent)
  const cur = await page.$eval('video[src]', v => v.currentTime)
  check('selecting an event seeks the player', cur >= 0 && cur < 20, `currentTime=${cur.toFixed(2)} for ${sel}`)
  await waitFor(async () => page.$$eval('.frames img', imgs => imgs.length > 0 && imgs.every(i => i.complete && i.naturalWidth > 0)), 15000, 'evidence images')
  check('evidence frames load', true)
  await page.evaluate(() => document.querySelector('video[src]').pause()); await sleep(800)
  const withBoxes = await painted()
  check('overlay draws pixels (zones and boxes)', withBoxes > 500, `${withBoxes} painted pixels`)
  await page.evaluate(() => document.querySelector('.row input[type=checkbox]').click()); await sleep(300)
  const noBoxes = await painted()
  await page.evaluate(() => document.querySelector('.row input[type=checkbox]').click())
  check('original toggle removes boxes but keeps zones', noBoxes < withBoxes && noBoxes > 0, `${withBoxes} -> ${noBoxes}`)
  const before = await page.$eval('video[src]', v => v.currentTime)
  const thumbs = await page.$$('.frame'); await thumbs[thumbs.length - 1].click(); await sleep(600)
  const after = await page.$eval('video[src]', v => v.currentTime)
  check('evidence thumbnail jumps to the source timestamp', Math.abs(after - before) > 0.1, `${before.toFixed(2)} -> ${after.toFixed(2)}`)

  // review
  await clickText('Confirmed', 'label'); await page.type('textarea', 'Person clearly inside the strip.')
  await clickText('Save review'); await waitFor(async () => page.$$eval('.notice', n => n.some(x => x.textContent.includes('Saved.'))), 10000, 'review saved')
  check('review saved', true)

  // keyboard on the timeline
  await page.focus('.tl-axis'); const t0 = await page.$eval('video[src]', v => v.currentTime); await page.keyboard.press('ArrowRight'); await sleep(500)
  check('timeline responds to the keyboard', Math.abs((await page.$eval('video[src]', v => v.currentTime)) - t0) > 0.5)

  // reload and verify persistence
  await page.reload({ waitUntil: 'networkidle0' }); await waitFor(() => page.$('ul.events li'), 30000, 'events after reload')
  const statuses = await page.$$eval('ul.events .pill', p => p.map(x => x.textContent))
  check('review survives a reload', statuses.includes('Confirmed'), statuses.join(','))

  // search
  await page.type('#q', 'person entering restricted zone'); await page.keyboard.press('Enter'); await sleep(900)
  check('text search shows what was understood', (await page.$eval('.search + .notice', e => e.textContent)).includes('Understood'))
  await page.$eval('#q', e => { e.value = '' }); await page.focus('#q')
  await page.evaluate(() => { const i = document.querySelector('#q'); const s = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; s.call(i, 'unattended bag'); i.dispatchEvent(new Event('input', { bubbles: true })) })
  await page.keyboard.press('Enter'); await sleep(900)
  check('unsupported query shows a notice and no events', (await page.$eval('.search + .notice', e => e.textContent)).includes('Unattended') && (await page.$$eval('ul.events li', l => l.length)) === 0)

  // export
  const runId = await page.evaluate(async () => (await (await fetch('/api/runs')).json()).runs[0].id)
  const rep = await page.evaluate(async id => (await fetch(`/api/runs/${id}/report`)).json(), runId)
  check('export has source and run hashes, limitations and the review', !!rep.video.source_sha256 && !!rep.run.manifest_sha256 && rep.limitations.length >= 4 && rep.events.some(e => e.review_status === 'confirmed'))
  check('HTML report endpoint', (await page.evaluate(async id => (await fetch(`/api/runs/${id}/report?format=html`)).status, runId)) === 200)

  // other views
  for (const [h, title] of [['#/evaluation', 'Evaluation'], ['#/system-design', 'System design']]) { await page.goto(`${BASE}/${h}`, { waitUntil: 'networkidle0' }); await sleep(300); check(`view ${h}`, (await text('h1')).includes(title)) }

  // narrow viewport
  await page.setViewport({ width: 390, height: 800 }); await page.goto(`${BASE}/#/review`, { waitUntil: 'networkidle0' }); await sleep(900)
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  check('no horizontal overflow at 390 px', overflow <= 1, `overflow=${overflow}`)
} catch (e) {
  check('flow aborted', false, e.message)
  try { console.log('DEBUG notices:', JSON.stringify(await page.$$eval('.notice', n => n.map(x => x.textContent.trim().slice(0, 160))))); console.log('DEBUG buttons:', JSON.stringify(await page.$$eval('button', b => b.map(x => x.textContent.trim() + (x.disabled ? '[disabled]' : ''))))); console.log('DEBUG zones header:', await page.$eval('#zones-h', e => e.textContent)) } catch { /* ignore */ }
}
check('no console errors', consoleErrors.length === 0, consoleErrors.slice(0, 3).join(' | '))
try { await page.screenshot({ path: process.env.SHOT || 'e2e/last.png', fullPage: true }) } catch { /* ignore */ }
await browser.close()
fs.writeFileSync('e2e/last-results.json', JSON.stringify(results, null, 2))
process.exit(results.every(r => r.ok) ? 0 : 1)

// Static demo mode check: visibly distinct, read-only, shows precomputed evidence, no backend needed for data.
import puppeteer from 'puppeteer-core'
const BROWSER = process.env.BROWSER_PATH || '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser'
const BASE = process.env.UI_URL || 'http://127.0.0.1:5173'
const out = []; const check = (n, ok, d = '') => { out.push({ name: n, ok: !!ok, detail: d }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${n}${d ? '  ' + d : ''}`) }
const sleep = ms => new Promise(r => setTimeout(r, ms))
const b = await puppeteer.launch({ executablePath: BROWSER, headless: 'new', args: ['--no-sandbox'] })
const p = await b.newPage(); await p.setViewport({ width: 1400, height: 1000 })
const errs = []; p.on('console', m => { if (m.type() === 'error') errs.push(m.text()) }); p.on('pageerror', e => errs.push(String(e)))
const apiCalls = []; p.on('request', r => { if (r.url().includes('/api/')) apiCalls.push(r.url()) })
await p.goto(`${BASE}/?mode=demo`, { waitUntil: 'networkidle0' }); await sleep(1500)
check('demo badge is distinct', (await p.$eval('.badge', e => e.textContent)).includes('Static demo') && await p.$eval('.badge', e => e.className.includes('badge-demo')))
check('events from the precomputed bundle', (await p.$$eval('ul.events li', l => l.length)) > 0)
check('upload, zone and process controls are disabled', await p.$$eval('button', bs => ['Draw zone', 'Process video', 'Upload'].every(t => bs.filter(b => b.textContent.trim() === t).every(b => b.disabled))))
await p.click('ul.events li button'); await sleep(500)
check('evidence images load from /demo', await p.$$eval('.frames img', i => i.length > 0 && i.every(x => x.complete && x.naturalWidth > 0 && x.src.includes('/demo/evidence/'))))
check('review is read only', await p.$eval('fieldset:has(textarea)', f => f.disabled))
check('video plays from the static bundle', await p.$eval('video[src]', v => v.src.includes('/demo/video.mp4')))
check('no data requests to the backend API', apiCalls.length === 0, apiCalls.slice(0, 2).join(','))
await p.goto(`${BASE}/?mode=demo#/evaluation`, { waitUntil: 'networkidle0' }); await sleep(800)
check('evaluation view renders from the bundle', (await p.$eval('h1', e => e.textContent)).includes('Evaluation') && (await p.$$eval('table', t => t.length)) >= 2)
check('no console errors', errs.length === 0, errs.slice(0, 2).join(' | '))
// backend-offline state: every /api request fails
const q = await b.newPage(); await q.setRequestInterception(true); q.on('request', r => r.url().includes('/api/') ? r.abort() : r.continue())
await q.goto(BASE, { waitUntil: 'networkidle0' }); await sleep(1200)
check('backend-offline state is explicit and offers the demo', (await q.$eval('.badge', e => e.textContent)).includes('Backend offline') && (await q.$eval('[role=alert]', e => e.textContent)).includes('static demo'))
await b.close(); process.exit(out.every(x => x.ok) ? 0 : 1)

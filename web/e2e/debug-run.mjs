import puppeteer from 'puppeteer-core'
const b = await puppeteer.launch({ executablePath: '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser', headless: 'new', args: ['--no-sandbox'] })
const p = await b.newPage(); await p.setViewport({ width: 1400, height: 1000 })
const net = []; p.on('response', r => { if (r.url().includes('/api/runs') && r.request().method() !== 'GET') net.push(r.request().method() + ' ' + r.status() + ' ' + r.url()) })
await p.goto('http://127.0.0.1:5173/', { waitUntil: 'networkidle0' }); await new Promise(r => setTimeout(r, 1500))
console.log('zones header:', await p.$eval('#zones-h', e => e.textContent))
console.log('buttons:', await p.$$eval('button', bs => bs.map(x => x.textContent.trim() + (x.disabled ? '[disabled]' : ''))))
const hs = await p.$$('button'); for (const h of hs) if ((await h.evaluate(e => e.textContent.trim())) === 'Process video') { await h.click(); break }
await new Promise(r => setTimeout(r, 2500))
console.log('net:', net)
console.log('notices:', await p.$$eval('.notice', n => n.map(x => x.textContent.trim().slice(0, 200))))
console.log('runinfo:', await p.$$eval('.runinfo', n => n.map(x => x.textContent.slice(0, 200))))
await b.close()

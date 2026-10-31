/**
 * Home + hero interaction smoke (Playwright). Run from frontend/:
 *   npx playwright install chromium   # once
 *   node scripts/smoke_home_hero.mjs
 */
import { chromium } from 'playwright'

const BASE = process.env.XSTREAM_BASE || 'http://127.0.0.1:3000'

function todayPassword() {
  const d = new Date()
  const yy = String(d.getUTCFullYear()).slice(-2)
  const mm = String(d.getUTCMonth() + 1).padStart(2, '0')
  const dd = String(d.getUTCDate()).padStart(2, '0')
  const day = d.getUTCDate()
  return `rn${yy}${mm}${dd}${day % 2}`
}

const failures = []

function fail(msg) {
  failures.push(msg)
  console.error('FAIL:', msg)
}

async function main() {
  const browser = await chromium.launch({ headless: true })
  const context = await browser.newContext()
  const page = await context.newPage()

  const auth = await context.request.post(`${BASE}/api/auth`, {
    data: { password: todayPassword() },
  })
  if (!auth.ok()) fail(`auth HTTP ${auth.status()}`)
  else {
    const body = await auth.json()
    if (!body.ok) fail('auth password rejected')
  }

  const cookies = await context.cookies()
  if (!cookies.some((c) => c.name === 'xstream_auth' && c.value === 'ok')) {
    fail('xstream_auth cookie missing after login')
  }

  await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded', timeout: 60_000 })
  await page.waitForTimeout(1500)

  if (await page.locator('text=Sign in').count()) fail('still on login gate after auth cookie')

  const hero = page.locator('.hero-stage').first()
  await hero.waitFor({ state: 'visible', timeout: 30_000 })
  const frame = hero.locator('.hero-frame')
  const navNext = hero.locator('.hero-nav').last()
  const navPrev = hero.locator('.hero-nav').first()
  const countEl = hero.locator('.hero-count')

  if (!(await countEl.count())) {
    console.log('ok: home loaded (single-title hero, nav checks skipped)')
    await browser.close()
    return
  }

  const countBefore = (await countEl.textContent())?.trim() ?? ''
  const box = await frame.boundingBox()
  if (!box) fail('hero-frame has no bounding box')
  else {
    const fromX = box.width * 0.72
    const fromY = box.height * 0.5
    const toX = box.width * 0.18
    // dragTo emits a coherent pointer stream; raw mouse.move often skips pointermove.
    await frame.dragTo(frame, {
      sourcePosition: { x: fromX, y: fromY },
      targetPosition: { x: toX, y: fromY },
      force: true,
    })
    await page.waitForTimeout(600)
    const countAfterSwipe = (await countEl.textContent())?.trim() ?? ''
    const [i0, n0] = countBefore.split('/').map((s) => parseInt(s.trim(), 10))
    const [i1] = countAfterSwipe.split('/').map((s) => parseInt(s.trim(), 10))
    if (Number.isFinite(i0) && Number.isFinite(n0) && i0 < n0 && i1 === i0) {
      fail(`swipe did not advance hero (${countBefore} -> ${countAfterSwipe})`)
    }
  }

  const countMid = (await countEl.textContent())?.trim() ?? ''
  await navNext.click({ timeout: 5000, force: true })
  await page.waitForTimeout(400)
  const countAfterNav = (await countEl.textContent())?.trim() ?? ''
  const [im, nm] = countMid.split('/').map((s) => parseInt(s.trim(), 10))
  const [in2] = countAfterNav.split('/').map((s) => parseInt(s.trim(), 10))
  if (Number.isFinite(im) && Number.isFinite(nm) && im < nm && in2 === im) {
    fail(`hero-nav next dead after swipe (${countMid} -> ${countAfterNav})`)
  }

  if (await navPrev.isEnabled()) await navPrev.click({ timeout: 5000, force: true })

  const sortGroup = page.locator('[role="radiogroup"][aria-label="Sort stars"]')
  if (!(await sortGroup.count())) fail('StarSortToggle not found')
  const latestBtn = sortGroup.getByRole('radio', { name: 'Latest' })
  const addedBtn = sortGroup.getByRole('radio', { name: 'Added' })
  const latestSelected = (await latestBtn.getAttribute('aria-checked')) === 'true'
  if (latestSelected) await addedBtn.click()
  else await latestBtn.click()
  await page.waitForTimeout(300)
  const flipped = (await latestBtn.getAttribute('aria-checked')) !== (latestSelected ? 'true' : 'false')
  if (!flipped) fail('sort toggle did not change selection')

  if (!(await page.locator('.scroll-rail').count())) fail('PageScrollRail missing')

  await browser.close()
  if (failures.length) {
    console.error(`\n${failures.length} failure(s)`)
    process.exit(1)
  }
  console.log('ok: home hero swipe, nav after swipe, sort toggle, scroll rail')
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})

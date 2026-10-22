#!/usr/bin/env node
/*
 * browser_list.js — list a client-rendered supplier site's product pages for /image-fill.
 * READ ONLY: it loads public pages in headless Chromium and prints what they show.
 *
 *   node scripts/browser_list.js <listing url> <product link regex> [max pages]
 *
 * Prints one JSON object on stdout: {"pages": [{url, title, h1, images: [{url, alt,
 * width_hint, height_hint}]}]} in the page shape scripts/supplier_site_pull.py uses.
 *
 * Why (2026-10-22): Tosca's site is a single-page React app; its products exist only after
 * the browser runs the bundle, so a plain fetch sees an empty shell. This reads what any
 * visitor sees. It never fills a form, never logs in, and never tries to get past a bot
 * challenge: a page that answers with one is skipped and reported.
 *
 * Playwright comes from the environment (global install; PLAYWRIGHT_BROWSERS_PATH set),
 * not from this repo.
 */
const { chromium } = require('playwright');

const UA = 'TitanFlooringCatalogueBot/1.0 (dealer catalogue; contact info@titanfloors.ca)';

async function main() {
  const [listUrl, linkPattern, maxArg] = process.argv.slice(2);
  if (!listUrl || !linkPattern) {
    console.error('usage: browser_list.js <listing url> <product link regex> [max pages]');
    process.exit(2);
  }
  const max = parseInt(maxArg || '600', 10);
  const re = new RegExp(linkPattern);
  const browser = await chromium.launch();
  const page = await browser.newPage({ userAgent: UA });
  const out = { pages: [], skipped: [] };
  try {
    await page.goto(listUrl, { waitUntil: 'networkidle', timeout: 60000 });
    await page.waitForTimeout(1500);
    const links = [...new Set(await page.$$eval('a[href]', as => as.map(a => a.href)))]
      .filter(h => re.test(h)).slice(0, max);
    for (const url of links) {
      try {
        const resp = await page.goto(url, { waitUntil: 'networkidle', timeout: 60000 });
        const headers = resp ? resp.headers() : {};
        if (headers['cf-mitigated'] === 'challenge' || headers['sg-captcha']) {
          out.skipped.push({ url, reason: 'challenged' });
          continue;
        }
        await page.waitForTimeout(800);
        const title = await page.title();
        const h1 = await page.$eval('h1', h => h.innerText.trim()).catch(() => '');
        // The collection a page states in its body (`SUPERIOR COLLECTION`): Tosca reuses a
        // colour name across collections, and the title carries the colour alone.
        const body = await page.innerText('body').catch(() => '');
        const coll = (body.match(/^\s*([A-Z0-9][A-Z0-9 '&\/.-]{2,40} COLLECTION)\s*$/m) || [])[1] || '';
        const images = await page.$$eval('img', is => is
          .filter(i => (i.currentSrc || i.src || '').startsWith('http'))
          .map(i => ({ url: i.currentSrc || i.src, alt: i.alt || '',
                       width_hint: i.naturalWidth || null, height_hint: i.naturalHeight || null })));
        const seen = new Set();
        out.pages.push({ url, title, h1, og_title: '', product_name: '', is_product: true, codes: [],
                         collection: coll,
                         images: images.filter(i => !seen.has(i.url) && seen.add(i.url)) });
      } catch (e) {
        out.skipped.push({ url, reason: String(e).slice(0, 120) });
      }
    }
  } finally {
    await browser.close();
  }
  process.stdout.write(JSON.stringify(out));
}

main().catch(e => { console.error(String(e)); process.exit(1); });

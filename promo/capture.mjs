// Capture crisp 2x-DPI screenshots of the live Nessus client app for the promo.
// Output: public/shots/<name>.png  (3840x2160 each — 16:9, ready for Ken Burns)
import { chromium } from "playwright";
import { fileURLToPath } from "url";
import path from "path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(__dirname, "public", "shots");
const BASE = "http://localhost:3000";

const SHOTS = [
  { name: "dashboard", url: "/", wait: "text=Intelligence Dashboard" },
  { name: "sectors", url: "/sectors", wait: "text=/Sector|Telecommunications/i" },
  { name: "sector_telecom", url: "/sectors/telecommunications", wait: "text=Connected Entities" },
  { name: "entity_telus", url: "/entities/telus", wait: "text=Cross-source" },
  { name: "record_contract", url: "/records/contracts/670565", wait: "text=Data Transmission Service" },
  { name: "players", url: "/politicians", wait: "text=Political Players" },
  {
    name: "search",
    url: "/search?q=" + encodeURIComponent("Telecom lobbying ahead of the spectrum auction"),
    search: true,
  },
];

const HIDE_DEV_CSS = `
  nextjs-portal, #__next-build-watcher, [data-nextjs-toast],
  [data-nextjs-dev-tools-button], div[data-nextjs-dialog-overlay] { display:none !important; }
  ::-webkit-scrollbar { width:0 !important; height:0 !important; }
  * { scrollbar-width: none !important; }
`;

async function settle(page, ms = 1200) {
  try { await page.waitForLoadState("networkidle", { timeout: 15000 }); } catch {}
  await page.waitForTimeout(ms);
}

async function run() {
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 2,
  });
  const page = await context.newPage();

  for (const shot of SHOTS) {
    const url = BASE + shot.url;
    process.stdout.write(`-> ${shot.name}  ${url}\n`);
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 45000 });
    await page.addStyleTag({ content: HIDE_DEV_CSS }).catch(() => {});

    if (shot.wait) {
      try { await page.waitForSelector(shot.wait, { timeout: 20000 }); } catch (e) {
        process.stdout.write(`   (selector wait skipped: ${shot.name})\n`);
      }
    }

    if (shot.search) {
      // Ask Nessus auto-runs from ?q=; wait for the streamed, formatted answer.
      try {
        await page.waitForFunction(() => {
          const t = document.body.innerText || "";
          const matched = /Active Sources/i.test(t) && !/Run a query to see/i.test(t);
          const formatted = document.querySelectorAll("h3,h4,strong").length > 2;
          const notLoading = !/Searching every source/i.test(t);
          return matched && formatted && notLoading && t.length > 1600;
        }, { timeout: 60000 });
      } catch { process.stdout.write("   (search answer wait timed out)\n"); }
    }

    await settle(page);
    // re-hide dev overlay in case it re-mounted after hydration
    await page.addStyleTag({ content: HIDE_DEV_CSS }).catch(() => {});
    await page.evaluate(() => { document.querySelectorAll("nextjs-portal").forEach((e) => e.remove()); });

    const file = path.join(OUT, `${shot.name}.png`);
    await page.screenshot({ path: file }); // viewport only -> 3840x2160 at 2x DPR
    process.stdout.write(`   saved ${file}\n`);
  }

  await browser.close();
  process.stdout.write("CAPTURE_DONE\n");
}

run().catch((e) => { console.error(e); process.exit(1); });

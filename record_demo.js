const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

(async () => {
  console.log("Starting demo recording with Playwright...");
  const outputDir = path.join(__dirname, 'demo_recordings');
  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
  }

  const browser = await chromium.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });

  const context = await browser.newContext({
    viewport: { width: 1280, height: 720 },
    recordVideo: {
      dir: outputDir,
      size: { width: 1280, height: 720 }
    }
  });

  const page = await context.newPage();
  const targetUrl = 'https://nanny-match-ai-frontend-198992522104.us-east1.run.app';

  console.log(`Navigating to ${targetUrl}...`);
  await page.goto(targetUrl, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);

  // 1. First prompt: App core feature - candidate lookup in Firestore
  console.log("Sending Prompt 1 (Firestore Nanny Lookup)...");
  const prompt1 = "Find CPR certified nanny candidates in San Francisco under $35/hr";
  await page.fill('#input', prompt1);
  await page.waitForTimeout(1000);
  await page.click('form button');

  // Wait for reply bubble to finish loading (waiting for '…' to change)
  await page.waitForTimeout(8000);

  // 2. Second prompt: Richer prompt - Payroll calculation & cost breakdown in Sandbox / Tool call
  console.log("Sending Prompt 2 (Payroll & Employer Tax Calculation)...");
  const prompt2 = "Calculate weekly and monthly payroll for a nanny working 40 hours at $32/hr with 5 overtime hours";
  await page.fill('#input', prompt2);
  await page.waitForTimeout(1000);
  await page.click('form button');

  await page.waitForTimeout(10000);

  // 3. Third prompt: Image generation tool
  console.log("Sending Prompt 3 (Generate candidate profile illustration)...");
  const prompt3 = "Generate a warm profile illustration for Elena Rostova, a CPR certified nanny";
  await page.fill('#input', prompt3);
  await page.waitForTimeout(1000);
  await page.click('form button');

  await page.waitForTimeout(12000);

  console.log("Closing browser session...");
  await context.close();
  await browser.close();

  const videoFiles = fs.readdirSync(outputDir).filter(f => f.endsWith('.webm'));
  if (videoFiles.length > 0) {
    const latestVideo = path.join(outputDir, videoFiles[0]);
    console.log(`Demo video successfully recorded: ${latestVideo}`);
  } else {
    console.log("No video files found in output directory.");
  }
})();

import asyncio
import os
import sys
from playwright.async_api import async_playwright

# Append parent directory to sys.path to run the example directly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from resilience import click_if_visible, dump_failure, start_tracing, stop_tracing
from logger import setup_logger

# Define a mock html content to run locally
MOCK_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Test Page for Resilience Module</title>
</head>
<body>
    <h1>Resilience Module Test</h1>
    <button id="visible-btn">Click Me!</button>
    <button id="hidden-btn" style="display:none;">You can't see me</button>
    <div id="status">Waiting...</div>
    <script>
        document.getElementById('visible-btn').addEventListener('click', () => {
            document.getElementById('status').innerText = 'Button Clicked!';
        });
    </script>
</body>
</html>
"""

async def main():
    logger, _ = setup_logger("resilience_example.log")
    logger.info("Initializing Playwright...")

    # Write a temporary html file
    temp_html_path = os.path.abspath("temp_test.html")
    with open(temp_html_path, "w", encoding="utf-8") as f:
        f.write(MOCK_HTML)

    async with async_playwright() as p:
        # Launch browser in headless mode
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        
        # Start tracing
        await start_tracing(context, enable=True)
        
        page = await context.new_page()
        
        logger.info(f"Opening local test file: {temp_html_path}")
        await page.goto(f"file:///{temp_html_path}")

        # 1. Test clicking a visible button
        visible_locator = page.locator("#visible-btn")
        clicked = await click_if_visible(visible_locator, "TestUser", "Visible Button Click")
        status_text = await page.locator("#status").inner_text()
        logger.info(f"Visible button clicked? {clicked}. Page Status text: '{status_text}'")

        # 2. Test clicking a hidden button (should fail gracefully/omit without crash)
        hidden_locator = page.locator("#hidden-btn")
        clicked_hidden = await click_if_visible(hidden_locator, "TestUser", "Hidden Button Click", timeout=1000)
        logger.info(f"Hidden button clicked? {clicked_hidden} (Expected: False)")

        # 3. Simulate failure dump (screenshot + HTML)
        logger.info("Simulating failure dump generation...")
        await dump_failure(page, "TestUser", "simulated_error_action")

        # Stop tracing
        await stop_tracing(context, filepath="logs/example_trace.zip", enable=True)

        await browser.close()

    # Cleanup temporary HTML
    if os.path.exists(temp_html_path):
        os.remove(temp_html_path)
        
    print("\n--- Playwright Resilience test completed successfully!")
    print("Check 'logs/' directory for:")
    print(" - 'logs/failures/' containing simulated_error_action html + screenshot")
    print(" - 'logs/example_trace.zip' containing Playwright trace")

if __name__ == "__main__":
    asyncio.run(main())

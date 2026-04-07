from playwright.sync_api import sync_playwright

def run_cuj(page):
    # This project uses file:// protocol for frontend, as seen in previous explorations.
    # We will open index.html directly.
    page.goto("file:///app/frontend/index.html")
    page.wait_for_timeout(1000)

    # Since the inline JS onclick doesn't trigger automatically in file:// protocol because of missing dependencies or scripts loaded via the server,
    # let's trigger it directly via evaluating JS to show the modal
    page.evaluate("document.getElementById('create-project-modal').classList.remove('hidden');")
    page.wait_for_timeout(1000)

    # Take screenshot of the modal showing the required asterisks
    page.screenshot(path="/app/verification/screenshots/verification2.png")
    page.wait_for_timeout(1000)

if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            record_video_dir="/app/verification/videos"
        )
        page = context.new_page()
        try:
            run_cuj(page)
        finally:
            context.close()
            browser.close()

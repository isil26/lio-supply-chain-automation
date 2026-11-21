"""Verify the staged site with production smoke checks and a fresh Chromium session."""
import argparse
import importlib.util
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import BaseHandler, build_opener


ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy/vercel"
PROD = "https://soony-launch-control.vercel.app"
CANDIDATE = re.compile(r"https://soony-launch-control-[a-z0-9]+-muratcagangogebakans-projects\.vercel\.app")


def smoke(url, password, bypass):
    spec = importlib.util.spec_from_file_location("replay_smoke", DEPLOY / "verify.py")
    suite = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(suite)

    class CandidateAccess(BaseHandler):
        def https_request(self, request):
            if urlsplit(request.full_url).netloc != urlsplit(url).netloc:
                raise ValueError("Unexpected candidate origin")
            request.add_unredirected_header("x-vercel-protection-bypass", bypass)
            return request

    if bypass:
        suite.build_opener = lambda *handlers: build_opener(*handlers, CandidateAccess())
    for attempt in range(5):
        try:
            suite.verify(url, password, "summary_only")
            return
        except SystemExit as failure:
            if not bypass or attempt == 4 or "returned HTTP 302" not in str(failure):
                raise
            time.sleep(3)


def browser_test(url, password, bypass):
    from playwright.sync_api import expect, sync_playwright

    netloc = urlsplit(url).netloc
    replay_routes = {"/api/dashboard", "/api/sync", "/api/replay/reset"}
    unexpected = []

    def handle(route):
        target = urlsplit(route.request.url)
        if target.netloc != netloc or target.path.startswith("/api/") and target.path not in replay_routes:
            unexpected.append(target.path)
            route.abort()
        else:
            route.continue_()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(extra_http_headers={"x-vercel-protection-bypass": bypass})
        page = context.new_page()
        page.route("**/*", handle)
        page.goto(url)
        page.get_by_label("Team password").fill(password)
        page.get_by_role("button", name="Sign in", exact=True).click()
        offers = page.get_by_role("region", name="Supplier offers")
        expect(offers.get_by_text("Fictional offers for this example", exact=False)).to_be_visible()
        for material in ("Game cards", "Statues", "Art books", "Cover sleeves"):
            tab = offers.get_by_role("tab", name=re.compile(material))
            tab.click()
            expect(tab).to_have_attribute("aria-selected", "true")
        offers.get_by_role("tab", name=re.compile("Game cards")).click()
        expect(page.get_by_role("region", name="Best supplier").get_by_text("Fictional suppliers", exact=False)).to_be_visible()
        offers.get_by_role("row", name=re.compile("Sweden")).get_by_role("button", name="Approve").click()
        offers.get_by_role("row", name=re.compile("Italy")).get_by_role("button", name="Decline").click()
        expect(offers.get_by_text("Nothing was sent here", exact=False)).to_be_visible()
        page.get_by_role("button", name="Update", exact=True).click()
        expect(page.get_by_role("button", name="Reset", exact=True)).to_be_visible()
        page.reload()
        expect(page.get_by_role("button", name="Reset", exact=True)).to_be_visible()
        expect(page.get_by_text("€32 per Standard copy (unconfirmed)", exact=False)).to_be_visible()
        page.get_by_role("button", name="See what the agents do").click()
        page.get_by_role("tab", name="AI reasoning").click()
        panel = page.get_by_role("region", name="Reported live-run summary")
        for label in ("Detailed trace unavailable", "Unknown", "706e772"):
            expect(panel.get_by_text(label, exact=False).first).to_be_visible()
        expect(page.get_by_role("dialog").get_by_role("button", name=re.compile(r"^(Run|Stop|Approve|Send)\b"))).to_have_count(0)
        if unexpected:
            raise SystemExit("The hosted browser tried to reach a live or external endpoint.")
        browser.close()
    print("Verified browser-only supplier decisions and recorded reasoning after reload.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--browser", action="store_true")
    args = parser.parse_args()
    bypass = os.environ.get("SOONY_TEST_BYPASS")
    if args.browser and (not bypass or not CANDIDATE.fullmatch(args.url)):
        parser.error("Browser verification requires the protected candidate and its temporary credential")
    if not args.browser and (bypass or args.url != PROD):
        parser.error("Production verification uses the canonical URL without a candidate credential")
    password = (DEPLOY / "team-password.txt").read_text().strip()
    smoke(args.url, password, bypass)
    if args.browser:
        browser_test(args.url, password, bypass)


if __name__ == "__main__":
    main()

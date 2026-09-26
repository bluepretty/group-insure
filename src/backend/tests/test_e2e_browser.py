"""End-to-end browser test for the Group Insurance platform.

Boots the real FastAPI app on a loopback HTTP server (SQLite, in-memory-style
file), then drives a real headless Chromium instance through the underwriter and
broker journeys via Playwright, asserting the server-rendered HTMX UI renders and
that role separation still holds through the browser.

Run with:  src/backend/.venv/bin/python src/backend/tests/test_e2e_browser.py
"""
import os
import sys
import time
import random
import signal

from fastapi import FastAPI
from fastapi.testclient import TestClient

# Make the app importable from the repo root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.api import auth, audit, benefits, billing, claims, life_events, members, pages, parties, policies, premiums, products, reports, statements
from app.models import User, Product, Party, Policy, Member, Benefit, LifeEvent, AuditLog, Organization, Invoice, Payment, Claim


APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(APP_DIR, "static")


def create_app(database_url: str) -> FastAPI:
    """Construct the FastAPI app bound to a given database URL."""
    os.environ["GROUP_INSURE_DATABASE_URL"] = database_url
    from app.core.config import settings
    from app.core.database import engine, Base

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    app = FastAPI()
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    templates = Jinja2Templates(directory="app/templates")
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.include_router(auth.router, prefix="/api/auth")
    app.include_router(parties.router)
    app.include_router(products.router)
    app.include_router(policies.router)
    app.include_router(benefits.router)
    app.include_router(premiums.router)
    app.include_router(billing.router)
    app.include_router(claims.router)
    app.include_router(members.router)
    app.include_router(audit.router)
    app.include_router(life_events.router)
    app.include_router(pages.router)
    app.include_router(reports.router)
    app.include_router(statements.router)

    from app import models
    return app


def seed_data(app: FastAPI):
    """Seed users, a product, a policyholder, an active policy, and an active member."""
    from app.core.database import SessionLocal
    from app.core.security import hash_password
    from app.services.parties import add_party
    from app.services.products import add_product
    from app.services.policies import add_policy, change_policy_status
    from app.services.members import enroll_member

    db = SessionLocal()
    try:
        # underwriter (can manage), broker (view-only)
        add_user(db, "underwriter", "secret123", "underwriter")
        add_user(db, "broker", "secret123", "broker")

        # product, policyholder, policy, member (all wired up for the journey)
        product = add_product(db, name="Group Term Life", product_type="group-term-life", description="Base plan")
        party = add_party(db, name="Acme Corp", party_type="policyholder")
        policy = add_policy(db, policy_number="POL-001", product_id=product.id, party_id=party.id)
        change_policy_status(db, policy_id=policy.id, to_status="active")
        enroll_member(db, policy_id=policy.id, party_id=party.id, member_number="MEM-001", first_name="Alice", last_name="Sample")
    finally:
        db.close()


def add_user(db, username, password, roles):
    from app.models.user import User
    from app.core.security import hash_password
    existing = db.query(User).where(User.username == username).first()
    if existing:
        return existing
    u = User(username=username, password=hash_password(password), roles=roles, email=f"{username}@example.com")
    db.add(u)
    db.commit()
    return u


def run_e2e(browser, app_port: int):
    """Run the browser journey and return a list of (name, passed, detail)."""
    base = f"http://localhost:{app_port}"
    results = []

    def record(name, passed, detail=""):
        results.append({"name": name, "passed": passed, "detail": detail})
        print(f"[{'PASS' if passed else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))

    try:
        # ---- 1. Login via the actual HTML form (encoded data) ----
        page = browser.new_page()
        page.goto(f"{base}/login")
        page.fill('form input[name="username"]', "underwriter")
        page.fill('form input[name="password"]', "secret123")
        page.click('form button[type="submit"]')
        page.wait_for_url("**/dashboard**", timeout=5000)
        record("underwriter login (html form)", "/dashboard" in page.url, page.url)

        # ---- 2. View Products ----
        page.get_by_role("link", name="Products").click()
        page.wait_for_timeout(800)
        record("view Products", "Product catalog" in page.inner_text("body"), page.url)

        # ---- 3. View Policies ----
        page.get_by_role("link", name="Policies").click()
        page.wait_for_timeout(800)
        record("view Policies", "Policies" in page.inner_text("body"), page.url)

        # ---- 4. Create a product ----
        # Go back to dashboard, then navigate to Products partial which has the create form
        page.get_by_role("link", name="Products").click()
        page.wait_for_timeout(500)
        # Create a new product via the form
        page.fill('input[name="name"]', "Health Plus")
        page.fill('input[name="product_type"]', "group-health")
        page.click('button:has-text("Add")')
        page.wait_for_timeout(800)
        record("create product", "Health Plus" in page.inner_text("body") or "group-health" in page.inner_text("body"), page.url)

        # ---- 5. View Members ----
        page.get_by_role("link", name="Enrollment").click()
        page.wait_for_timeout(800)
        record("view Enrollment", "Enrolled Members" in page.inner_text("body") or "members" in page.inner_text("body").lower(), page.url)

        # ---- 6. Enroll a new member (census add) ----
        page.fill('input[name="first_name"]', "Bob")
        page.fill('input[name="last_name"]', "Member")
        page.fill('input[name="member_number"]', "MEM-002")
        page.fill('input[name="relationship"]', "spouse")
        # census add form posts to /api/members/{policy_id}/add
        page.click('button:has-text("Add")')
        page.wait_for_timeout(800)
        record("enroll member", "Bob" in page.inner_text("body") or "MEM-002" in page.inner_text("body"), page.url)

        # ---- 7. View Reports ----
        page.get_by_role("link", name="Reports").click()
        page.wait_for_timeout(1000)
        report_text = page.inner_text("body")
        record("view Reports", "reports" in report_text.lower() or "policyholders" in report_text.lower(), page.url[:200])

        # ---- 8. Broker login ----
        page.get_by_role("link", name="Logout").click()
        page.wait_for_url("**/login**", timeout=5000)
        page.fill('form input[name="username"]', "broker")
        page.fill('form input[name="password"]', "secret123")
        page.click('form button[type="submit"]')
        page.wait_for_url("**/dashboard**", timeout=5000)
        record("broker login", "/dashboard" in page.url, page.url)

        # ---- 9. Broker can view but not create products ----
        page.get_by_role("link", name="Products").click()
        page.wait_for_timeout(800)
        # Broker should not see the create product form (manage_products required)
        has_create_form = page.query_selector('input[name="name"]') is not None
        record("broker view-only (no create form)", not has_create_form, "saw create form" if has_create_form else "no create form")

        # ---- 10. Broker cannot create a product (expect 403) ----
        # Try to POST directly via browser's fetch through a small injection
        resp = page.evaluate("""
            async () => {
                const r = await fetch('/api/products/create', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: 'name=Hack&product_type=x'
                });
                return { status: r.status, text: (await r.text()).slice(0,200) };
            }
        """)
        record("broker blocked creating product (403)", resp["status"] == 403, f"status={resp['status']}")

        page.close()

    except Exception as e:
        record("E2E harness error", False, str(e))

    return results


def main():
    database_url = "sqlite:///./group_insure_e2e_test.db"
    app = create_app(database_url)
    seed_data(app)

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        app_port = random.randint(20000, 30000)

        import uvicorn
        import asyncio

        config = uvicorn.Config(app, host="127.0.0.1", port=app_port, log_level="warning")
        server = uvicorn.Server(config)

        import threading

        def run_server():
            asyncio.new_event_loop().run_until_complete(server.serve())

        t = threading.Thread(target=run_server, daemon=True)
        t.start()
        # Wait for the server to accept connections.
        import urllib.request
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{app_port}/health", timeout=0.5)
                break
            except Exception:
                time.sleep(0.2)

        try:
            results = run_e2e(browser, app_port)
        finally:
            browser.close()
            server.should_exit = True

    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    print(f"\n{'='*50}\nE2E RESULTS: {passed}/{total} passed\n{'='*50}")
    for r in results:
        print(f"  {'✓' if r['passed'] else '✗'} {r['name']}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())

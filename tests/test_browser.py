"""Header button behavior, whole-card click-through, keyboard focus and axe."""

from playwright.sync_api import expect

from conftest import FULL_PAGE_ONLY_DISABLED_RULES, format_violations, run_axe


def test_button_replaces_logo_and_marks_home_active(page, site_url):
    page.goto(site_url + "/")
    button = page.locator(".md-cheatsheet-button")
    expect(button).to_have_text("Cheatsheet")
    expect(button).to_have_attribute("aria-current", "page")
    expect(page.locator(".md-header__button.md-logo")).to_be_hidden()


def test_button_inactive_elsewhere_and_links_home(page, site_url):
    page.goto(site_url + "/mammals/cats/")
    button = page.locator(".md-cheatsheet-button")
    expect(button).not_to_have_attribute("aria-current", "page")
    button.click()
    expect(page).to_have_url(site_url + "/")


def test_clicking_card_body_opens_page(page, site_url):
    page.goto(site_url + "/")
    card = page.locator(".md-cheatsheet__card").filter(has_text="Whales")
    box = card.bounding_box()
    page.mouse.click(box["x"] + box["width"] - 5, box["y"] + box["height"] - 5)
    expect(page).to_have_url(site_url + "/mammals/whales/")


def test_term_link_stays_clickable_above_card_overlay(page, site_url):
    page.goto(site_url + "/")
    page.locator(".md-cheatsheet__term", has_text="Lion").click()
    expect(page).to_have_url(site_url + "/mammals/cats/#lion")


def test_card_title_link_has_visible_focus(page, site_url):
    page.goto(site_url + "/")
    link = page.locator(".md-cheatsheet__title-link").first
    link.focus()
    outline = link.evaluate("el => getComputedStyle(el).outlineStyle")
    assert outline != "none"


def test_axe_cheatsheet(page, site_url):
    page.goto(site_url + "/")
    violations = run_axe(page, context=".md-cheatsheet")
    assert not violations, format_violations(violations)


def test_axe_full_page(page, site_url):
    page.goto(site_url + "/")
    violations = run_axe(page, extra_disabled=FULL_PAGE_ONLY_DISABLED_RULES)
    assert not violations, format_violations(violations)

from conftest import csrf
from agrisense.services import kits as K
from agrisense.services.catalog import seed_catalog


def test_kits_page_shows_options_prices_and_ways_to_buy(client):
    html = client.get("/kits").get_data(as_text=True)
    for k in K.KITS:
        assert k["name"] in html and "{:,}".format(k["price"]) in html
    assert "purchase order" in html and "/pilot" in html and "Video3_Power_Up_Safety_Checks.mp4" in html
    assert "Kits &amp; pricing" in client.get("/").get_data(as_text=True)


def test_quote_form_offers_kit_options_and_saves_choice(client, db):
    html = client.get("/quote?plan=field").get_data(as_text=True)
    assert 'value="field" selected' in html and "Starter + Field" in html
    tok = csrf(client, "/quote")
    client.post("/quote", data={"_csrf": tok, "email": "a@school.org", "plan": "both", "kits": "2"})
    client.post("/quote", data={"_csrf": tok, "email": "b@school.org", "plan": "free-stuff"})
    assert db.val("SELECT plan FROM leads WHERE email = ?", "a@school.org") == "both"
    assert db.val("SELECT plan FROM leads WHERE email = ?", "b@school.org") == "starter"


def test_plan_prices_follow_the_catalog(db):
    db.run("UPDATE plans SET price_cents = 120000 WHERE code = 'school'")
    seed_catalog(db)
    assert db.val("SELECT price_cents FROM plans WHERE code = 'school'") == 30000
    assert db.val("SELECT price_cents FROM plans WHERE code = 'virtual'") == 30000

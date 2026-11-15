from conftest import login
from agrisense.services import catalog as C
from agrisense.services import lab_content as L
from agrisense.services import standards as S

ORDER = ["1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7", "1.8", "1.9", "1.10", "1.11", "2.1", "2.2", "2.3", "2.4", "2.5"]


def test_sixteen_lessons_in_starter_first_order(db):
    assert [r["code"] for r in db.q("SELECT code FROM lessons ORDER BY seq, code")] == ORDER
    assert [c for c, *_ in C.LESSONS] == ORDER and list(L.LABS) == ORDER and list(S.MAP) == ORDER
    assert db.val("SELECT title FROM lessons WHERE code = '1.6'") == "Build your own sensor node"
    assert db.val("SELECT title FROM lessons WHERE code = '1.10'") == "Code it yourself"
    assert "HS-ETS1-2" in db.val("SELECT standards FROM lessons WHERE code = '1.10'")


def test_old_numbering_moves_rows_with_their_content(db):
    # put the database back to the old order: drop the two new lessons, move rows back to their old codes
    db.run("DELETE FROM lessons WHERE code IN ('1.6', '1.10')")
    for old, new in C.RENUMBER_2026.items():
        db.run("UPDATE lessons SET code = ? WHERE code = ?", "x" + old, new)
    for old in C.RENUMBER_2026:
        db.run("UPDATE lessons SET code = ? WHERE code = ?", old, "x" + old)
    drying_id = db.val("SELECT id FROM lessons WHERE code = '1.3'")
    assert db.val("SELECT title FROM lessons WHERE code = '1.6'") == "Build the Trainer pump loop"
    C.seed_catalog(db)
    assert db.val("SELECT code FROM lessons WHERE id = ?", drying_id) == "1.7"
    assert db.val("SELECT title FROM lessons WHERE code = '1.3'") == "Build the Trainer pump loop"
    assert db.val("SELECT COUNT(*) AS n FROM lessons") == 16


def test_new_lab_pages_and_sheets(client, db):
    login(client, "teacher")
    for code in ("1.6", "1.10"):
        page = client.get(f"/labs/{code}").get_data(as_text=True)
        assert L.LABS[code]["goal"][:30] in page
        assert "Claim, evidence, reasoning" in client.get(f"/labs/{code}/sheet").get_data(as_text=True)
    home = client.get("/").get_data(as_text=True)
    assert "16 lessons" in home and "Build deck" in home and "Student Arduino" in home

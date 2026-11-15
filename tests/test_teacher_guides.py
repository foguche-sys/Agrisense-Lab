from conftest import login, login_student

from agrisense.services.lab_content import LABS
from agrisense.services.teacher_guides import GUIDES


def test_every_lesson_has_a_full_guide():
    assert set(GUIDES) == set(LABS)
    for code, g in GUIDES.items():
        assert len(g["answers"]) == len(LABS[code]["questions"]), code
        for k in ("big_idea", "before", "plan", "expect", "trouble", "assess", "support", "stretch", "backup"):
            assert g[k], (code, k)


def test_teacher_sees_guides(client, db):
    login(client, "teacher")
    for code in GUIDES:
        page = client.get(f"/labs/{code}/guide").get_data(as_text=True)
        assert GUIDES[code]["big_idea"].split(",")[0][:30] in page.replace("&#39;", "'"), code
        assert "Answers to" in page
    assert "Teacher guide" in client.get("/labs/1.1").get_data(as_text=True)


def test_students_never_see_guides(client, db):
    login_student(client, db)
    assert client.get("/labs/1.1/guide").status_code == 403
    assert client.get("/labs/3.1/guide").status_code == 403
    page = client.get("/labs/1.1").get_data(as_text=True)
    assert "Teacher guide" not in page and "Answers to" not in page
    assert client.get("/downloads/AgriSense_Teacher_Guides.pdf").status_code == 403


def test_signed_out_people_go_to_sign_in(client):
    assert client.get("/labs/1.1/guide").status_code == 302
    assert client.get("/downloads/AgriSense_Teacher_Guides.pdf").status_code == 302


def test_teacher_downloads_guides_pdf(client, db):
    login(client, "teacher")
    r = client.get("/downloads/AgriSense_Teacher_Guides.pdf")
    assert r.status_code == 200 and r.data[:4] == b"%PDF"
    r.close()

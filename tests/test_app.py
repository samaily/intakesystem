from app import app


def test_homepage():
    client = app.test_client()
    response = client.get("/")
    assert response.status_code == 200


def test_intake_page():
    client = app.test_client()
    response = client.get("/intake")
    assert response.status_code == 200


def test_dashboard_is_disabled():
    client = app.test_client()
    response = client.get("/dashboard")
    assert response.status_code == 403


def test_patient_details_are_disabled():
    client = app.test_client()
    response = client.get("/patient/1")
    assert response.status_code == 403

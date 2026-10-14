def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_login_page_renders(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert "ERP MIKO" in response.text

from fastapi.testclient import TestClient

from macrovision import __version__


def test_health_check_reports_database_reachable(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "reachable"}


def test_swagger_and_openapi_are_available(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
    schema = client.get("/openapi.json")
    assert schema.status_code == 200
    assert schema.json()["info"]["title"] == "MacroVision API"
    assert schema.json()["info"]["version"] == "0.7.0"
    assert __version__ == "0.7.0"

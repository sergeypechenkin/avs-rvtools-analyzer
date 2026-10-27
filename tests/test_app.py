"""Application startup and HTTP smoke tests."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from avs_rvtools_analyzer.config import AppConfig
from avs_rvtools_analyzer.core.exceptions import AnalysisError
from avs_rvtools_analyzer.main import create_app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("avs_rvtools_analyzer.main.load_dotenv", lambda: False)
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT_NAME", raising=False)
    with TestClient(create_app()) as test_client:
        yield test_client


def test_openapi_preserves_configured_tags(client):
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["tags"] == AppConfig().fastapi.tags_metadata


@pytest.mark.parametrize("path", ["/", "/health", "/docs", "/api/info"])
def test_application_routes_are_available(client, path):
    response = client.get(path)

    assert response.status_code == 200


def test_ai_status_reports_missing_configuration(client):
    response = client.get("/api/azure-openai-status")

    assert response.status_code == 200
    assert response.json() == {
        "is_configured": False,
        "deployment_name": None,
    }


@pytest.mark.parametrize(
    "path,template", [("/explore", "explore.html"), ("/analyze", "analyze.html")]
)
def test_synthetic_excel_upload_renders_results(client, path, template):
    test_data = Path(__file__).parent / "test-data" / "comprehensive_test_data.xlsx"
    response = client.post(
        path,
        files={
            "file": (
                "synthetic.xlsx",
                test_data.read_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 200
    assert response.template.name == template


def test_ai_endpoint_reports_upstream_errors(monkeypatch):
    service = Mock()
    service.is_configured = True
    service.get_risk_analysis_suggestion.side_effect = AnalysisError(
        "Azure OpenAI request failed: Unable to get resource information."
    )
    monkeypatch.setattr("avs_rvtools_analyzer.main.load_dotenv", lambda: False)
    monkeypatch.setattr(
        "avs_rvtools_analyzer.routes.api_routes.AzureOpenAIService",
        Mock(return_value=service),
    )
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/ai-suggestion",
            json={
                "risk_name": "detect_vusb_devices",
                "risk_description": "USB devices",
                "risk_data": [],
                "risk_level": "warning",
            },
        )

    assert response.status_code == 200
    assert response.json()["success"] is False
    assert "Unable to get resource information" in response.json()["error"]

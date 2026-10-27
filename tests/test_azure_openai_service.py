"""Tests for keyless Azure OpenAI authentication and Foundry inference."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict
from unittest.mock import Mock

import pytest
from azure.core.credentials import AccessToken
from azure.core.exceptions import ClientAuthenticationError

from avs_rvtools_analyzer.core.exceptions import AnalysisError
from avs_rvtools_analyzer.services import azure_openai_service


@pytest.fixture
def keyless_environment(monkeypatch):
    for name in (
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_DEPLOYMENT_NAME",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_AD_TOKEN",
        "AZURE_OPENAI_MAX_TOKENS",
        "OPENAI_API_KEY",
        "AZURE_TOKEN_CREDENTIALS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_NAME", "risk-analysis")
    credential = Mock(spec=["get_token"])
    credential.get_token.return_value = AccessToken(
        "test-entra-token", int(time.time()) + 3600
    )
    credential_factory = Mock(return_value=credential)
    monkeypatch.setattr(
        azure_openai_service, "DefaultAzureCredential", credential_factory
    )
    return credential_factory


@pytest.fixture
def completion_endpoint(monkeypatch, keyless_environment):
    state: Dict[str, Any] = {
        "requests": [],
        "status": 200,
        "content": "<p>Advice</p>",
        "finish_reason": "stop",
    }

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            state["requests"].append(
                {
                    "headers": {
                        key.lower(): value for key, value in self.headers.items()
                    },
                    "path": self.path,
                    "body": json.loads(
                        self.rfile.read(int(self.headers["Content-Length"]))
                    ),
                }
            )
            if state["status"] == 200:
                body = {
                    "id": "test-completion",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "risk-analysis",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": state["content"],
                            },
                            "finish_reason": state["finish_reason"],
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                    },
                }
            else:
                body = {
                    "error": {
                        "code": "InternalServerError",
                        "message": "Unable to get resource information.",
                    }
                }
            payload = json.dumps(body).encode()
            self.send_response(state["status"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        monkeypatch.setenv(
            "AZURE_OPENAI_ENDPOINT", f"http://127.0.0.1:{server.server_port}"
        )
        try:
            yield state
        finally:
            server.shutdown()
            thread.join(timeout=5)


@pytest.mark.parametrize(
    "missing_variable", ["AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT_NAME"]
)
def test_incomplete_configuration_disables_ai(
    monkeypatch, keyless_environment, missing_variable
):
    monkeypatch.delenv(missing_variable)
    service = azure_openai_service.AzureOpenAIService()

    assert service.client is None
    assert service.get_configuration_status()["is_configured"] is False
    assert service.get_configuration_status()["deployment_name"] is None
    keyless_environment.assert_not_called()


@pytest.mark.parametrize("host", ["openai.azure.com", "services.ai.azure.com"])
@pytest.mark.parametrize("path", ["", "/", "/openai/v1", "/openai/v1/"])
def test_endpoint_normalization(monkeypatch, keyless_environment, host, path):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", f"https://example.{host}{path}")
    service = azure_openai_service.AzureOpenAIService()
    try:
        assert service.is_configured is True
        assert service.client is not None
        assert str(service.client.base_url) == f"https://example.{host}/openai/v1/"
        assert service.max_tokens == 2000
        keyless_environment.assert_called_once_with()
        keyless_environment.return_value.get_token.assert_not_called()
    finally:
        if service.client:
            service.client.close()


@pytest.mark.parametrize("legacy_value", [None, "unused-legacy-credential", ""])
def test_requests_use_refreshable_bearer_tokens(
    monkeypatch, keyless_environment, completion_endpoint, legacy_value
):
    if legacy_value is not None:
        for name in ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_AD_TOKEN", "OPENAI_API_KEY"):
            monkeypatch.setenv(name, legacy_value)
    keyless_environment.return_value.get_token.side_effect = [
        AccessToken("first-token", int(time.time()) + 1),
        AccessToken("refreshed-token", int(time.time()) + 3600),
    ]
    service = azure_openai_service.AzureOpenAIService()
    try:
        results = [
            service.get_risk_analysis_suggestion(
                "detect_vusb_devices", "USB devices", [], "warning"
            )
            for _ in range(2)
        ]
        assert service.test_connection()["success"] is True
    finally:
        if service.client:
            service.client.close()

    requests = completion_endpoint["requests"]
    assert len(requests) == 3
    assert [request["headers"]["authorization"] for request in requests] == [
        "Bearer first-token",
        "Bearer refreshed-token",
        "Bearer refreshed-token",
    ]
    for request in requests:
        assert "api-key" not in request["headers"]
        assert request["path"] == "/openai/v1/chat/completions"
        assert request["body"]["model"] == "risk-analysis"
        assert request["body"]["max_completion_tokens"] == 2000
        assert "max_tokens" not in request["body"]
        assert "temperature" not in request["body"]
    for result in results:
        assert result is not None
        assert result["suggestion"] == "<p>Advice</p>"
        assert result["tokens_used"] == 15
    for call in keyless_environment.return_value.get_token.call_args_list:
        assert call.args == ("https://cognitiveservices.azure.com/.default",)


def test_authentication_failure_is_logged(keyless_environment, caplog):
    keyless_environment.return_value.get_token.side_effect = ClientAuthenticationError(
        message="No Azure login available"
    )
    service = azure_openai_service.AzureOpenAIService()
    try:
        with pytest.raises(AnalysisError, match="No Azure login available"):
            service.get_risk_analysis_suggestion(
                "detect_vusb_devices", "USB devices", [], "warning"
            )
        assert "No Azure login available" in caplog.text
    finally:
        if service.client:
            service.client.close()


def test_invalid_credential_configuration_is_logged(keyless_environment, caplog):
    keyless_environment.side_effect = ValueError("Invalid credential selection")
    service = azure_openai_service.AzureOpenAIService()

    assert service.is_configured is False
    assert service.client is None
    assert "Invalid credential selection" in caplog.text


@pytest.mark.parametrize("content", [None, "", "   "])
def test_empty_suggestion_is_an_explicit_failure(completion_endpoint, content):
    completion_endpoint["content"] = content
    completion_endpoint["finish_reason"] = "length"
    service = azure_openai_service.AzureOpenAIService()
    try:
        with pytest.raises(AnalysisError, match="AZURE_OPENAI_MAX_TOKENS"):
            service.get_risk_analysis_suggestion(
                "detect_vusb_devices", "USB devices", [], "warning"
            )
    finally:
        if service.client:
            service.client.close()


def test_azure_error_reaches_the_caller(completion_endpoint):
    completion_endpoint["status"] = 500
    service = azure_openai_service.AzureOpenAIService()
    try:
        with pytest.raises(AnalysisError, match="Unable to get resource information"):
            service.get_risk_analysis_suggestion(
                "detect_vusb_devices", "USB devices", [], "warning"
            )
    finally:
        if service.client:
            service.client.close()

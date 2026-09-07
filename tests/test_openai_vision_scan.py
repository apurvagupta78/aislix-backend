"""Tests for direct OpenAI vision scan provider."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.make_scan import use_openai_provider
from app.openai_vision_scan import (
    OpenAIVisionScanError,
    build_vision_user_message,
    call_openai_vision,
    load_shelf_audit_prompt,
    vision_model,
)
from app.user_errors import public_error_from_exception


@pytest.fixture
def tiny_image() -> np.ndarray:
    return np.zeros((120, 160, 3), dtype=np.uint8)


def test_use_openai_provider(monkeypatch):
    monkeypatch.delenv("SCAN_PROVIDER", raising=False)
    assert use_openai_provider() is False
    monkeypatch.setenv("SCAN_PROVIDER", "openai")
    assert use_openai_provider() is True
    monkeypatch.setenv("SCAN_PROVIDER", "make")
    assert use_openai_provider() is False


def test_load_shelf_audit_prompt_contains_metadata_placeholder():
    prompt = load_shelf_audit_prompt()
    assert "Act as a professional retail shelf auditor" in prompt
    assert "{{11.metadata}}" in prompt
    assert "Return ONLY valid JSON." in prompt


def test_build_vision_user_message_injects_metadata():
    message = build_vision_user_message({"category": "Snacks", "sub_category": "chips"})
    assert "{{11.metadata}}" not in message
    assert '"category": "Snacks"' in message
    assert "chips" in message


@patch("app.recognizer.get_client")
def test_call_openai_vision_success(mock_get_client, monkeypatch, tiny_image):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_VISION_MODEL", "gpt-6-astra")
    mock_response = MagicMock()
    mock_response.output_text = json.dumps(
        {
            "products": [
                {
                    "brand": "Lay's",
                    "product": "Potato Chips",
                    "variant": "Magic Masala",
                    "qty": 5,
                    "confidence": 0.92,
                    "product_category": "chips",
                    "bbox_2d": [100, 200, 300, 400],
                }
            ],
            "executive_summary": "Snack shelf audit complete.",
        }
    )
    mock_get_client.return_value.responses.create.return_value = mock_response

    parsed = call_openai_vision(scan_id="abc", image=tiny_image, metadata={"category": "Snacks"})
    assert parsed["inventory"][0]["brand"] == "Lay's"
    assert parsed["executive_summary"] == "Snack shelf audit complete."

    _, kwargs = mock_get_client.return_value.responses.create.call_args
    assert kwargs["model"] == "gpt-6-astra"
    assert kwargs["text"] == {"format": {"type": "json_object"}}
    assert kwargs["reasoning"] == {"effort": "medium"}
    content = kwargs["input"][0]["content"]
    assert content[0]["type"] == "input_text"
    assert content[1]["type"] == "input_image"
    assert content[1]["detail"] == "auto"


@patch("app.recognizer.get_client")
def test_call_openai_vision_missing_api_key(mock_get_client, monkeypatch, tiny_image):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(OpenAIVisionScanError, match="OPENAI_API_KEY"):
        call_openai_vision(scan_id="abc", image=tiny_image, metadata={})
    mock_get_client.assert_not_called()


@patch("app.recognizer.get_client")
def test_call_openai_vision_empty_response(mock_get_client, monkeypatch, tiny_image):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    mock_get_client.return_value.responses.create.return_value = MagicMock(output_text="")
    with pytest.raises(OpenAIVisionScanError, match="empty response"):
        call_openai_vision(scan_id="abc", image=tiny_image, metadata={})


@patch("app.openai_vision_scan.run_openai_vision_scan_from_image")
def test_pipeline_dispatches_to_openai_when_enabled(mock_openai, monkeypatch, tiny_image):
    monkeypatch.setenv("SCAN_PROVIDER", "openai")
    mock_openai.return_value = {"scan_id": "from-openai", "model_version": "openai+gpt-6-astra", "inventory": []}
    from app.pipeline import run_scan_from_image

    result = run_scan_from_image(tiny_image, scan_id="from-openai")
    assert result["model_version"] == "openai+gpt-6-astra"
    mock_openai.assert_called_once()


def test_openai_error_is_sanitized_for_users():
    assert public_error_from_exception(OpenAIVisionScanError("OPENAI_API_KEY is not configured.")) == (
        "Our analysis service is temporarily unavailable. Please try again later."
    )


def test_vision_model_default(monkeypatch):
    monkeypatch.delenv("OPENAI_VISION_MODEL", raising=False)
    assert vision_model() == "gpt-6-astra"

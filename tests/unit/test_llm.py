"""Unit tests for utils.llm module."""
import os
from unittest.mock import patch

import pytest
import requests

from utils.llm import (
    LLM_PROVIDER,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    _ask_ollama,
    _ask_openai,
    _ollama_available,
    _validate_model_name,
    ask_model,
)


class TestValidateModelName:
    """Tests for _validate_model_name function."""

    def test_valid_model(self):
        """Test valid model name passes validation."""
        assert _validate_model_name("llama3.1:8b") == "llama3.1:8b"

    def test_invalid_characters(self):
        """Test model name with invalid characters raises ValueError."""
        with pytest.raises(ValueError, match="Nombre de modelo inválido"):
            _validate_model_name("model; rm -rf /")

    def test_invalid_model_not_in_allowlist(self):
        """Test model not in allowlist raises ValueError."""
        with pytest.raises(ValueError, match="Modelo no permitido"):
            _validate_model_name("invalid-model:latest")


class TestOllamaAvailable:
    """Tests for _ollama_available function."""

    def test_ollama_available_success(self, mock_requests_get):
        """Test _ollama_available returns True when Ollama responds."""
        mock_requests_get.return_value.status_code = 200
        assert _ollama_available() is True

    def test_ollama_available_failure(self, mock_requests_get):
        """Test _ollama_available returns False on connection error."""
        mock_requests_get.side_effect = requests.ConnectionError()
        assert _ollama_available() is False

    def test_ollama_available_non_200(self, mock_requests_get):
        """Test _ollama_available returns False on non-200 status."""
        mock_requests_get.return_value.status_code = 500
        assert _ollama_available() is False


class TestAskOllama:
    """Tests for _ask_ollama function."""

    def test_ask_ollama_success(self, mock_ollama_response):
        """Test successful Ollama API call."""
        result = _ask_ollama("test prompt", "system prompt", 0.3, 100)
        assert result == "Test response from Ollama"
        mock_ollama_response.assert_called_once()

    def test_ask_ollama_timeout(self, mock_ollama_response):
        """Test Ollama timeout handling."""
        mock_ollama_response.side_effect = requests.exceptions.Timeout()
        with pytest.raises(Exception):
            _ask_ollama("test prompt", "system prompt", 0.3, 100)

    def test_ask_ollama_request_error(self, mock_ollama_response):
        """Test Ollama request error handling."""
        mock_ollama_response.side_effect = requests.exceptions.RequestException("Connection failed")
        with pytest.raises(Exception):
            _ask_ollama("test prompt", "system prompt", 0.3, 100)


class TestAskOpenAI:
    """Tests for _ask_openai function."""

    def test_ask_openai_success(self, mock_openai_response):
        """Test successful OpenAI API call."""
        result = _ask_openai("test prompt", "system prompt", 0.3, 100)
        assert result == "Test response from OpenAI"

    def test_ask_openai_no_api_key(self):
        """Test OpenAI without API key raises RuntimeError."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=True):
            with pytest.raises(Exception):
                _ask_openai("test prompt", "system prompt", 0.3, 100)


class TestAskModel:
    """Tests for ask_model function (main entry point)."""

    def test_ask_model_ollama_provider(self, mock_ollama_response):
        """Test ask_model with explicit ollama provider."""
        with patch("utils.llm.LLM_PROVIDER", "ollama"):
            with patch("utils.llm._ollama_available", return_value=True):
                result = ask_model("test prompt", 0.3, 100)
                assert result == "Test response from Ollama"

    def test_ask_model_openai_provider(self, mock_openai_response):
        """Test ask_model with explicit openai provider."""
        with patch("utils.llm.LLM_PROVIDER", "openai"):
            result = ask_model("test prompt", 0.3, 100)
            assert result == "Test response from OpenAI"

    def test_ask_model_auto_fallback(self, mock_openai_response):
        """Test ask_model auto mode falls back to OpenAI when Ollama unavailable."""
        with patch("utils.llm.LLM_PROVIDER", "auto"):
            with patch("utils.llm._ollama_available", return_value=False):
                result = ask_model("test prompt", 0.3, 100)
                assert result == "Test response from OpenAI"


class TestLLMConstants:
    """Tests for LLM module constants."""

    def test_llm_provider_default(self):
        """Test LLM_PROVIDER defaults to ollama."""
        assert LLM_PROVIDER == "ollama"

    def test_ollama_model_default(self):
        """Test OLLAMA_MODEL has expected default."""
        assert "gemma" in OLLAMA_MODEL.lower() or "deepseek" in OLLAMA_MODEL.lower()

    def test_ollama_base_url_default(self):
        """Test OLLAMA_BASE_URL defaults to localhost."""
        assert OLLAMA_BASE_URL == "http://localhost:11434"

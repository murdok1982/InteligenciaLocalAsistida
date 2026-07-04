"""Test configuration and shared fixtures."""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Set test environment variables before any imports
os.environ.setdefault("LLM_PROVIDER", "ollama")
os.environ.setdefault("OLLAMA_MODEL", "gemma3:4b")
os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWSAPI_KEY", "test-newsapi-key")


@pytest.fixture(autouse=True)
def reset_env(monkeypatch):
    """Reset environment variables for each test."""
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "gemma3:4b")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("NEWSAPI_KEY", "test-newsapi-key")


@pytest.fixture
def mock_ollama_response():
    """Mock successful Ollama API response."""
    with patch("requests.post") as mock_post:
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": "Test response from Ollama"}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response
        yield mock_post


@pytest.fixture
def mock_openai_response():
    """Mock successful OpenAI API response."""
    with patch("openai.OpenAI") as mock_client:
        mock_chat = MagicMock()
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock(message=MagicMock(content="Test response from OpenAI"))]
        mock_chat.completions.create.return_value = mock_completion
        mock_client.return_value.chat = mock_chat
        yield mock_client


@pytest.fixture
def mock_requests_get():
    """Mock requests.get for provider tests."""
    with patch("requests.get") as mock_get:
        yield mock_get


@pytest.fixture
def sample_config():
    """Sample configuration for testing."""
    return {
        "run": {
            "days_back": 7,
            "per_country_limit": 20,
            "providers": ["gdelt", "rss", "youtube"],
            "languages": ["es", "en"],
            "schedule": "weekly",
        },
        "llm": {
            "provider": "ollama",
            "ollama_model": "gemma3:4b",
            "ollama_base_url": "http://localhost:11434",
            "openai_model": "gpt-4o-mini",
            "temperature": 0.3,
            "max_tokens": 2000,
        },
        "report": {
            "output_dir": "outputs",
            "filename_prefix": "reporte_inteligencia_global",
            "include_tables": True,
            "classification": "ABIERTO",
        },
        "categories": [
            {"key": "economy", "label_es": "Economía", "prompt_key": "economic"},
            {"key": "security", "label_es": "Seguridad Interior", "prompt_key": "security"},
            {"key": "defense", "label_es": "Defensa", "prompt_key": "defense"},
            {"key": "intelligence", "label_es": "Inteligencia", "prompt_key": "intelligence"},
        ],
        "countries": [
            {"name": "United States", "code": "US"},
            {"name": "Spain", "code": "ES"},
        ],
    }


@pytest.fixture
def sample_articles():
    """Sample articles for testing."""
    return [
        {
            "title": "Test Article 1",
            "url": "https://example.com/article1",
            "source": "Test Source",
            "date": "2024-01-15",
            "summary": "This is a test summary about economy in Spain",
            "provider": "rss",
            "reliability": "A",
        },
        {
            "title": "Test Article 2",
            "url": "https://example.com/article2",
            "source": "Another Source",
            "date": "2024-01-14",
            "summary": "Security news about Spain",
            "provider": "gdelt",
            "reliability": "B",
        },
    ]


@pytest.fixture
def sample_countries():
    """Sample countries list for testing."""
    return [
        {"name": "United States", "code": "US"},
        {"name": "Spain", "code": "ES"},
        {"name": "France", "code": "FR"},
    ]

"""
Unit tests for configuration module.

Tests loading, validation, and error handling of Config class.
"""

import os
import pytest
from pathlib import Path
from unittest.mock import patch, mock_open
from src.config import Config


@pytest.fixture(autouse=True)
def clean_env():
    """Clean environment variables before each test."""
    # Save original values
    original_key = os.environ.get("BINANCE_API_KEY")
    original_secret = os.environ.get("BINANCE_API_SECRET")
    original_db = os.environ.get("DB_PATH")
    original_url = os.environ.get("BASE_URL")

    # Clear environment variables
    for key in ["BINANCE_API_KEY", "BINANCE_API_SECRET", "DB_PATH", "BASE_URL"]:
        os.environ.pop(key, None)

    yield

    # Restore original values
    if original_key:
        os.environ["BINANCE_API_KEY"] = original_key
    if original_secret:
        os.environ["BINANCE_API_SECRET"] = original_secret
    if original_db:
        os.environ["DB_PATH"] = original_db
    if original_url:
        os.environ["BASE_URL"] = original_url


class TestConfig:
    """Test suite for Config class."""

    def test_load_valid_env_file(self, tmp_path):
        """Test loading a valid .env file with all required fields."""
        # Create temporary .env file
        env_file = tmp_path / ".env"
        env_content = (
            "BINANCE_API_KEY=test_api_key_123\n"
            "BINANCE_API_SECRET=test_api_secret_456\n"
        )
        env_file.write_text(env_content)

        # Load config
        config = Config(env_file=str(env_file))

        # Verify credentials loaded
        assert config.api_key == "test_api_key_123"
        assert config.api_secret == "test_api_secret_456"

        # Verify defaults
        assert config.db_path == "crypto_data.db"
        assert config.base_url == "https://api.binance.com/api/v3"

        # Should not raise error
        config.validate()

    def test_load_env_with_custom_settings(self, tmp_path):
        """Test loading .env file with custom database path and base URL."""
        env_file = tmp_path / ".env"
        env_content = (
            "BINANCE_API_KEY=test_key\n"
            "BINANCE_API_SECRET=test_secret\n"
            "DB_PATH=custom_data.db\n"
            "BASE_URL=https://testnet.binance.vision/api/v3\n"
        )
        env_file.write_text(env_content)

        config = Config(env_file=str(env_file))

        assert config.api_key == "test_key"
        assert config.api_secret == "test_secret"
        assert config.db_path == "custom_data.db"
        assert config.base_url == "https://testnet.binance.vision/api/v3"

    def test_missing_env_file(self, tmp_path):
        """Test behavior when .env file doesn't exist."""
        # Use non-existent file path
        non_existent = tmp_path / "nonexistent.env"

        # Should not crash, but credentials will be None
        config = Config(env_file=str(non_existent))

        assert config.api_key is None
        assert config.api_secret is None

    def test_validate_missing_api_key(self, tmp_path):
        """Test validation fails when API key is missing."""
        env_file = tmp_path / ".env"
        env_content = "BINANCE_API_SECRET=test_secret\n"
        env_file.write_text(env_content)

        config = Config(env_file=str(env_file))

        with pytest.raises(ValueError) as exc_info:
            config.validate()

        assert "BINANCE_API_KEY" in str(exc_info.value)
        assert "Missing required API credentials" in str(exc_info.value)

    def test_validate_missing_api_secret(self, tmp_path):
        """Test validation fails when API secret is missing."""
        env_file = tmp_path / ".env"
        env_content = "BINANCE_API_KEY=test_key\n"
        env_file.write_text(env_content)

        config = Config(env_file=str(env_file))

        with pytest.raises(ValueError) as exc_info:
            config.validate()

        assert "BINANCE_API_SECRET" in str(exc_info.value)
        assert "Missing required API credentials" in str(exc_info.value)

    def test_validate_missing_both_credentials(self, tmp_path):
        """Test validation fails when both credentials are missing."""
        env_file = tmp_path / ".env"
        env_content = ""
        env_file.write_text(env_content)

        config = Config(env_file=str(env_file))

        with pytest.raises(ValueError) as exc_info:
            config.validate()

        error_message = str(exc_info.value)
        assert "BINANCE_API_KEY" in error_message
        assert "BINANCE_API_SECRET" in error_message
        assert "Missing required API credentials" in error_message

    def test_repr_hides_sensitive_data(self, tmp_path):
        """Test that __repr__ doesn't expose sensitive credentials."""
        env_file = tmp_path / ".env"
        env_content = (
            "BINANCE_API_KEY=super_secret_key\n"
            "BINANCE_API_SECRET=super_secret_secret\n"
        )
        env_file.write_text(env_content)

        config = Config(env_file=str(env_file))
        repr_str = repr(config)

        # Should not contain actual credentials
        assert "super_secret_key" not in repr_str
        assert "super_secret_secret" not in repr_str

        # Should contain masked values
        assert "***" in repr_str
        assert "crypto_data.db" in repr_str
        assert "https://api.binance.com/api/v3" in repr_str

    def test_repr_with_none_credentials(self, tmp_path):
        """Test __repr__ when credentials are None."""
        env_file = tmp_path / ".env"
        env_content = ""
        env_file.write_text(env_content)

        config = Config(env_file=str(env_file))
        repr_str = repr(config)

        # Should show None for missing credentials
        assert "api_key=None" in repr_str
        assert "api_secret=None" in repr_str

    def test_empty_string_credentials_treated_as_missing(self, tmp_path):
        """Test that empty string credentials are treated as missing."""
        env_file = tmp_path / ".env"
        env_content = (
            "BINANCE_API_KEY=\n"
            "BINANCE_API_SECRET=\n"
        )
        env_file.write_text(env_content)

        config = Config(env_file=str(env_file))

        # Empty strings should fail validation
        with pytest.raises(ValueError) as exc_info:
            config.validate()

        assert "Missing required API credentials" in str(exc_info.value)

    def test_whitespace_only_credentials(self, tmp_path):
        """Test that whitespace-only credentials are handled properly."""
        env_file = tmp_path / ".env"
        env_content = (
            "BINANCE_API_KEY=   \n"
            "BINANCE_API_SECRET=   \n"
        )
        env_file.write_text(env_content)

        config = Config(env_file=str(env_file))

        # Whitespace should be stripped by dotenv, resulting in empty/None
        # This should fail validation
        with pytest.raises(ValueError):
            config.validate()


# Pytest fixtures
@pytest.fixture
def valid_config(tmp_path):
    """Fixture providing a valid Config instance."""
    env_file = tmp_path / ".env"
    env_content = (
        "BINANCE_API_KEY=test_key\n"
        "BINANCE_API_SECRET=test_secret\n"
    )
    env_file.write_text(env_content)
    return Config(env_file=str(env_file))


def test_config_fixture(valid_config):
    """Test that the valid_config fixture works correctly."""
    assert valid_config.api_key == "test_key"
    assert valid_config.api_secret == "test_secret"
    valid_config.validate()  # Should not raise

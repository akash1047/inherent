"""Unit tests for Settings configuration, specifically Weaviate URL handling."""

from src.config.settings import Settings


class TestWeaviateUrlConfig:
    """Tests for Weaviate URL field and effective_weaviate_url property."""

    def test_weaviate_url_from_explicit_env(self):
        """WEAVIATE_URL env var should be used as effective_weaviate_url."""
        s = Settings(
            _env_file=None,
            weaviate_url="http://weaviate:8080",
        )
        assert s.effective_weaviate_url == "http://weaviate:8080"

    def test_weaviate_url_strips_trailing_slash(self):
        """WEAVIATE_URL with trailing slash should be stripped."""
        s = Settings(
            _env_file=None,
            weaviate_url="http://weaviate:8080/",
        )
        assert s.effective_weaviate_url == "http://weaviate:8080"

    def test_weaviate_url_fallback_to_host_port(self):
        """When WEAVIATE_URL is not set, fall back to weaviate_host + weaviate_port."""
        s = Settings(
            _env_file=None,
            weaviate_url=None,
            weaviate_host="my-weaviate-host",
            weaviate_port=9090,
        )
        assert s.effective_weaviate_url == "http://my-weaviate-host:9090"

    def test_weaviate_url_defaults(self):
        """With no env vars, effective_weaviate_url should default to http://localhost:8080."""
        s = Settings(
            _env_file=None,
            weaviate_url=None,
        )
        assert s.effective_weaviate_url == "http://localhost:8080"

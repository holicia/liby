import pytest
import config


@pytest.fixture(autouse=True)
def _ensure_token(monkeypatch):
    monkeypatch.setattr(config, "BRIDGE_TOKEN", "t-test")


def test_get_provider_claude_cli_returns_bridge_claude():
    from services.ai import get_provider
    from services.ai.bridge import BridgeProvider
    p = get_provider("claude-cli")
    assert isinstance(p, BridgeProvider)
    assert p.name() == "claude-cli"


def test_get_provider_codex_cli_returns_bridge_codex():
    from services.ai import get_provider
    from services.ai.bridge import BridgeProvider
    p = get_provider("codex-cli")
    assert isinstance(p, BridgeProvider)
    assert p.name() == "codex-cli"


def test_get_provider_claude_still_returns_api_provider():
    from services.ai import get_provider
    from services.ai.claude import ClaudeProvider
    assert isinstance(get_provider("claude"), ClaudeProvider)


def test_get_provider_gpt_still_returns_api_provider():
    from services.ai import get_provider
    from services.ai.openai_provider import OpenAIProvider
    assert isinstance(get_provider("gpt"), OpenAIProvider)


def test_get_provider_unknown_falls_back():
    from services.ai import get_provider
    from services.ai.fallback import FallbackProvider
    assert isinstance(get_provider("totally-unknown"), FallbackProvider)


def test_default_provider_module_default_is_claude_cli():
    """모듈 로드 시 환경변수 없으면 'claude-cli'가 default."""
    import config as c
    src = open(c.__file__, encoding='utf-8').read()
    assert 'os.getenv("DEFAULT_AI_PROVIDER", "claude-cli")' in src


def test_default_provider_routes_to_bridge_claude(monkeypatch):
    """get_provider() 인자 없으면 BridgeProvider('claude')."""
    monkeypatch.setattr(config, "DEFAULT_AI_PROVIDER", "claude-cli")
    from services.ai import get_provider
    from services.ai.bridge import BridgeProvider
    p = get_provider()
    assert isinstance(p, BridgeProvider)
    assert p.name() == "claude-cli"

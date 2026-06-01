import pytest
from models import init_db
import services.capture
import config


@pytest.fixture
async def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    await init_db(path)
    return path


@pytest.fixture(autouse=True)
def _reset_capture_warnings():
    """capture 모듈의 _no_ffmpeg_warned 플래그를 매 테스트 전 초기화."""
    services.capture._no_ffmpeg_warned = False
    yield


@pytest.fixture(autouse=True)
def _ensure_bridge_token(monkeypatch):
    """Default provider is now claude-cli, which needs BRIDGE_TOKEN. Provide a dummy
    so tests that don't explicitly construct a provider still pass."""
    monkeypatch.setattr(config, "BRIDGE_TOKEN", "test-token-conftest")

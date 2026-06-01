import json
import pytest
import httpx
from services.ai.bridge_client import (
    BridgeUsage, BridgeRunResult, BridgeError, run_agent,
)


def test_bridge_usage_defaults():
    u = BridgeUsage()
    assert u.input_tokens == 0
    assert u.output_tokens == 0
    assert u.total_cost_usd == 0.0


def test_bridge_run_result_holds_fields():
    r = BridgeRunResult(summary="ok", session_id="s1",
                        usage=BridgeUsage(input_tokens=10, output_tokens=20))
    assert r.summary == "ok"
    assert r.usage.input_tokens == 10


def test_bridge_error_carries_status_and_exit_code():
    e = BridgeError(status="failed", exit_code=1, summary="boom")
    assert e.status == "failed"
    assert e.exit_code == 1
    assert "boom" in str(e)


@pytest.mark.asyncio
async def test_run_agent_success_returns_result(monkeypatch):
    import config
    monkeypatch.setattr(config, "BRIDGE_TOKEN", "t-123")
    monkeypatch.setattr(config, "BRIDGE_BASE_URL", "http://bridge.test")

    seen_auth = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen_auth[req.url.path] = req.headers.get("authorization")
        if req.method == "POST" and req.url.path == "/v1/runs":
            return httpx.Response(202, json={"id": "run-1", "status": "queued"})
        if req.method == "GET" and req.url.path == "/v1/runs/run-1":
            return httpx.Response(200, json={
                "id": "run-1", "status": "succeeded",
                "summary": '{"title":"hi"}', "sessionId": "sess-1",
                "usage": {"inputTokens": 100, "outputTokens": 50, "totalCostUsd": 0.0},
            })
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    import services.ai.bridge_client as bc
    orig_client = bc.httpx.AsyncClient
    monkeypatch.setattr(bc, "_POLL_INTERVAL_SEC", 0.01, raising=False)
    monkeypatch.setattr(bc.httpx, "AsyncClient",
        lambda **kw: orig_client(transport=transport, **kw))

    result = await bc.run_agent("hi", adapter="claude")
    assert result.summary == '{"title":"hi"}'
    assert result.session_id == "sess-1"
    assert result.usage.input_tokens == 100
    assert result.usage.total_cost_usd == 0.0
    assert seen_auth["/v1/runs"] == "Bearer t-123"


@pytest.mark.asyncio
async def test_run_agent_failed_status_raises_bridge_error(monkeypatch):
    import config
    monkeypatch.setattr(config, "BRIDGE_TOKEN", "t")
    monkeypatch.setattr(config, "BRIDGE_BASE_URL", "http://bridge.test")

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            return httpx.Response(202, json={"id": "r", "status": "queued"})
        return httpx.Response(200, json={
            "id": "r", "status": "failed", "exitCode": 1,
            "summary": "boom", "usage": {},
        })

    import services.ai.bridge_client as bc
    monkeypatch.setattr(bc, "_POLL_INTERVAL_SEC", 0.01, raising=False)
    orig = bc.httpx.AsyncClient
    monkeypatch.setattr(bc.httpx, "AsyncClient",
        lambda **kw: orig(transport=httpx.MockTransport(handler), **kw))

    with pytest.raises(BridgeError) as exc:
        await bc.run_agent("hi", adapter="claude")
    assert exc.value.status == "failed"
    assert exc.value.exit_code == 1


@pytest.mark.asyncio
async def test_run_agent_budget_exceeded_402(monkeypatch):
    import config
    monkeypatch.setattr(config, "BRIDGE_TOKEN", "t")
    monkeypatch.setattr(config, "BRIDGE_BASE_URL", "http://bridge.test")
    def handler(req): return httpx.Response(402, text="budget exhausted")
    import services.ai.bridge_client as bc
    orig = bc.httpx.AsyncClient
    monkeypatch.setattr(bc.httpx, "AsyncClient",
        lambda **kw: orig(transport=httpx.MockTransport(handler), **kw))
    with pytest.raises(BridgeError) as exc:
        await bc.run_agent("hi", adapter="claude")
    assert exc.value.status == "budget_exceeded"


@pytest.mark.asyncio
async def test_run_agent_missing_token_raises():
    import config as c
    saved = c.BRIDGE_TOKEN
    c.BRIDGE_TOKEN = ""
    try:
        with pytest.raises(RuntimeError, match="BRIDGE_TOKEN"):
            await run_agent("hi", adapter="claude")
    finally:
        c.BRIDGE_TOKEN = saved


@pytest.mark.asyncio
async def test_run_agent_401_unauthorized(monkeypatch):
    import config
    monkeypatch.setattr(config, "BRIDGE_TOKEN", "wrong")
    monkeypatch.setattr(config, "BRIDGE_BASE_URL", "http://bridge.test")
    def handler(req): return httpx.Response(401, text="bad token")
    import services.ai.bridge_client as bc
    orig = bc.httpx.AsyncClient
    monkeypatch.setattr(bc.httpx, "AsyncClient",
        lambda **kw: orig(transport=httpx.MockTransport(handler), **kw))
    with pytest.raises(BridgeError) as exc:
        await bc.run_agent("hi", adapter="claude")
    assert exc.value.status == "unauthorized"


@pytest.mark.asyncio
async def test_run_agent_cancelled_status_raises(monkeypatch):
    import config
    monkeypatch.setattr(config, "BRIDGE_TOKEN", "t")
    monkeypatch.setattr(config, "BRIDGE_BASE_URL", "http://bridge.test")
    def handler(req):
        if req.method == "POST":
            return httpx.Response(202, json={"id": "r", "status": "queued"})
        return httpx.Response(200, json={"id": "r", "status": "cancelled",
                                          "exitCode": None, "summary": "user cancelled"})
    import services.ai.bridge_client as bc
    monkeypatch.setattr(bc, "_POLL_INTERVAL_SEC", 0.01, raising=False)
    orig = bc.httpx.AsyncClient
    monkeypatch.setattr(bc.httpx, "AsyncClient",
        lambda **kw: orig(transport=httpx.MockTransport(handler), **kw))
    with pytest.raises(BridgeError) as exc:
        await bc.run_agent("hi", adapter="claude")
    assert exc.value.status == "cancelled"


@pytest.mark.asyncio
async def test_run_agent_timed_out_status_raises(monkeypatch):
    import config
    monkeypatch.setattr(config, "BRIDGE_TOKEN", "t")
    monkeypatch.setattr(config, "BRIDGE_BASE_URL", "http://bridge.test")
    def handler(req):
        if req.method == "POST":
            return httpx.Response(202, json={"id": "r", "status": "queued"})
        return httpx.Response(200, json={"id": "r", "status": "timed_out",
                                          "exitCode": 124, "summary": "cli timeout"})
    import services.ai.bridge_client as bc
    monkeypatch.setattr(bc, "_POLL_INTERVAL_SEC", 0.01, raising=False)
    orig = bc.httpx.AsyncClient
    monkeypatch.setattr(bc.httpx, "AsyncClient",
        lambda **kw: orig(transport=httpx.MockTransport(handler), **kw))
    with pytest.raises(BridgeError) as exc:
        await bc.run_agent("hi", adapter="claude")
    assert exc.value.status == "timed_out"
    assert exc.value.exit_code == 124


@pytest.mark.asyncio
async def test_run_agent_polling_exhaustion_raises_timeout(monkeypatch):
    import config
    monkeypatch.setattr(config, "BRIDGE_TOKEN", "t")
    monkeypatch.setattr(config, "BRIDGE_BASE_URL", "http://bridge.test")
    def handler(req):
        if req.method == "POST":
            return httpx.Response(202, json={"id": "r", "status": "queued"})
        return httpx.Response(200, json={"id": "r", "status": "running"})  # never terminal
    import services.ai.bridge_client as bc
    monkeypatch.setattr(bc, "_POLL_INTERVAL_SEC", 0.001, raising=False)
    orig = bc.httpx.AsyncClient
    monkeypatch.setattr(bc.httpx, "AsyncClient",
        lambda **kw: orig(transport=httpx.MockTransport(handler), **kw))
    # timeout_sec=1 keeps the test fast (loops are 1/0.001 + 5 = ~1005 iterations of MockTransport)
    with pytest.raises(BridgeError) as exc:
        await bc.run_agent("hi", adapter="claude", timeout_sec=1)
    assert exc.value.status == "polling_timeout"


@pytest.mark.asyncio
async def test_run_agent_connect_error_wraps_to_bridge_error(monkeypatch):
    """bridge 컨테이너 down → ConnectError → BridgeError('connect_error') with Korean msg."""
    import config
    monkeypatch.setattr(config, "BRIDGE_TOKEN", "t")
    monkeypatch.setattr(config, "BRIDGE_BASE_URL", "http://bridge.test")

    def handler(req):
        raise httpx.ConnectError("Connection refused")

    import services.ai.bridge_client as bc
    orig = bc.httpx.AsyncClient
    monkeypatch.setattr(bc.httpx, "AsyncClient",
        lambda **kw: orig(transport=httpx.MockTransport(handler), **kw))
    with pytest.raises(BridgeError) as exc:
        await bc.run_agent("hi", adapter="claude")
    assert exc.value.status == "connect_error"
    assert "연결 실패" in exc.value.summary
    assert exc.value.__cause__ is not None  # raise...from으로 원본 보존


@pytest.mark.asyncio
async def test_run_agent_http_timeout_wraps_to_bridge_error(monkeypatch):
    """30s HTTP 타임아웃 → BridgeError('http_timeout')."""
    import config
    monkeypatch.setattr(config, "BRIDGE_TOKEN", "t")
    monkeypatch.setattr(config, "BRIDGE_BASE_URL", "http://bridge.test")

    def handler(req):
        raise httpx.ConnectTimeout("slow network")

    import services.ai.bridge_client as bc
    orig = bc.httpx.AsyncClient
    monkeypatch.setattr(bc.httpx, "AsyncClient",
        lambda **kw: orig(transport=httpx.MockTransport(handler), **kw))
    with pytest.raises(BridgeError) as exc:
        await bc.run_agent("hi", adapter="claude")
    assert exc.value.status == "http_timeout"
    assert "타임아웃" in exc.value.summary

"""agent-runner-bridge HTTP 클라이언트.

POST /v1/runs로 작업 생성 → status 폴링 → terminal 도달 시 결과/에러 반환.
구독 인증 사용 시 usage.total_cost_usd는 보통 0.
"""
import asyncio
from dataclasses import dataclass, field
import httpx
import config


@dataclass
class BridgeUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost_usd: float = 0.0


@dataclass
class BridgeRunResult:
    summary: str
    session_id: str | None
    usage: BridgeUsage = field(default_factory=BridgeUsage)


class BridgeError(RuntimeError):
    def __init__(self, status: str, exit_code: int | None, summary: str) -> None:
        self.status = status
        self.exit_code = exit_code
        self.summary = summary
        super().__init__(f"bridge {status} (exit {exit_code}): {summary[:200]}")


_POLL_INTERVAL_SEC = 1.5
_TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "timed_out"}


async def run_agent(
    prompt: str,
    *,
    adapter: str,
    cwd: str | None = None,
    model: str | None = None,
    timeout_sec: int = 900,
) -> BridgeRunResult:
    if not config.BRIDGE_TOKEN:
        raise RuntimeError("BRIDGE_TOKEN 미설정: .env에 BRIDGE_TOKEN을 설정하세요.")
    headers = {"Authorization": f"Bearer {config.BRIDGE_TOKEN}"}
    body: dict = {"adapter": adapter, "prompt": prompt, "timeoutSec": timeout_sec}
    if cwd:
        body["cwd"] = cwd
    if model:
        body["model"] = model
    async with httpx.AsyncClient(base_url=config.BRIDGE_BASE_URL, timeout=30.0) as c:
        create = await c.post("/v1/runs", json=body, headers=headers)
        if create.status_code == 402:
            raise BridgeError("budget_exceeded", None, create.text)
        if create.status_code == 401:
            raise BridgeError("unauthorized", None, "bridge 인증 실패: BRIDGE_TOKEN 확인")
        create.raise_for_status()
        run = create.json()
        run_id = run["id"]
        # 폴링
        deadline_loops = int(timeout_sec / _POLL_INTERVAL_SEC) + 5
        for _ in range(deadline_loops):
            await asyncio.sleep(_POLL_INTERVAL_SEC)
            poll = await c.get(f"/v1/runs/{run_id}", headers=headers)
            poll.raise_for_status()
            data = poll.json()
            status = data.get("status")
            if status in _TERMINAL_STATUSES:
                summary = data.get("summary") or ""
                if status != "succeeded":
                    raise BridgeError(status, data.get("exitCode"), summary)
                usage_raw = data.get("usage") or {}
                usage = BridgeUsage(
                    input_tokens=int(usage_raw.get("inputTokens", 0) or 0),
                    output_tokens=int(usage_raw.get("outputTokens", 0) or 0),
                    total_cost_usd=float(usage_raw.get("totalCostUsd", 0.0) or 0.0),
                )
                return BridgeRunResult(
                    summary=summary,
                    session_id=data.get("sessionId"),
                    usage=usage,
                )
        raise BridgeError("polling_timeout", None,
                          f"bridge가 {timeout_sec}s 안에 응답 안 함")

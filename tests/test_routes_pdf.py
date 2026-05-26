import pytest
import io
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport
from main import app


@pytest.mark.asyncio
async def test_analyze_pdf_returns_task_card_fragment():
    # POST는 즉시 큐 작업 카드(task_card)를 반환하고 분석은 워커가 비동기 처리.
    pdf_bytes = b"%PDF-1.4 fake content"
    async def fake_enqueue(task, fn):
        return None
    with patch("routers.pdf.enqueue", new=fake_enqueue), \
         patch("routers.pdf.get_provider"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/pdf",
                data={"provider": "claude", "mode": "quick"},
                files={"file": ("test.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
            )
    assert resp.status_code == 200
    assert "task-" in resp.text  # task_card 프래그먼트(id="task-...")

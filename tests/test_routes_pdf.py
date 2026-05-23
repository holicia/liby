import pytest
import io
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from main import app
from services.ai.base import SummaryResult

MOCK_RESULT = SummaryResult(
    title="테스트 PDF", language="ko", word_count=500,
    reading_time_min=3, sections=[],
    summary="PDF 요약입니다.", key_points=["핵심1"],
    tags=["논문"], suggested_topic="논문",
    summary_mode="quick", cost_usd=0.005,
    models_used=["claude-sonnet-4-6"],
)

@pytest.mark.asyncio
async def test_analyze_pdf_returns_note_card():
    pdf_bytes = b"%PDF-1.4 fake content"
    with patch("routers.pdf.extract_pdf", return_value="PDF 텍스트"), \
         patch("routers.pdf.get_provider") as mock_get, \
         patch("routers.pdf.save_note", return_value=2), \
         patch("routers.pdf.record_api_cost"):
        mock_provider = AsyncMock()
        mock_provider.name.return_value = "claude"
        mock_provider.summarize = AsyncMock(return_value=MOCK_RESULT)
        mock_get.return_value = mock_provider

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/pdf",
                data={"provider": "claude", "mode": "quick"},
                files={"file": ("test.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
            )
    assert resp.status_code == 200
    assert "테스트 PDF" in resp.text

import pytest
from httpx import AsyncClient, ASGITransport
from main import app


@pytest.mark.asyncio
async def test_pdf_input_partial_uses_label_wrapped_input():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/partials/input/pdf")
    assert resp.status_code == 200
    # input은 hidden, label이 전체 클릭 영역
    assert '<label' in resp.text
    assert 'class="hidden"' in resp.text
    assert 'pdf-filename' in resp.text
    assert 'hx-post="/api/pdf"' in resp.text

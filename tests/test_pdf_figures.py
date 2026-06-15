"""pdf_figures: 캡션 번호 파싱·그림 배치·갤러리 로직 (PDF 입출력 없는 순수 부분)."""
from services.pdf_figures import (
    _caption_number, figures_manifest,
    attach_figures_to_sections, build_gallery_section,
)


def test_caption_number_variants():
    assert _caption_number("Fig. 1. Stackup of C2W") == 1
    assert _caption_number("Figure 12 — results") == 12
    assert _caption_number("그림 3. 단면도") == 3
    assert _caption_number("Fig 7 total resistance") == 7
    assert _caption_number("본문 일반 문장입니다") is None
    assert _caption_number("Table 2. parameters") is None  # 표는 그림 아님


def test_figures_manifest():
    figs = [{"n": 1, "caption": "Fig. 1. A", "file": "s/fig1.png", "page": 1},
            {"n": 2, "caption": "Fig. 2. B", "file": "s/fig2.png", "page": 2}]
    m = figures_manifest(figs)
    assert "[그림1] Fig. 1. A" in m
    assert "[그림2] Fig. 2. B" in m
    assert figures_manifest([]) == ""


def test_attach_figures_replaces_number_with_image():
    figs = [{"n": 1, "caption": "Fig. 1", "file": "s/fig1.png", "page": 1},
            {"n": 2, "caption": "Fig. 2", "file": "s/fig2.png", "page": 1}]
    sections = [{"heading": "1. 결과", "subsections": [
        {"heading": "1.1", "items": [
            {"text": "그림1 설명", "refs": [], "figure": 1},
            {"text": "그림 없음", "refs": []},
            {"text": "알수없는 그림", "refs": [], "figure": 99},
        ]}
    ]}]
    placed = attach_figures_to_sections(sections, figs)
    assert placed == {1}
    items = sections[0]["subsections"][0]["items"]
    assert items[0]["image"]["file"] == "s/fig1.png"
    assert "figure" not in items[0]  # 번호 키 제거
    assert "image" not in items[1]
    assert "figure" not in items[2]  # 알 수 없는 번호도 키 제거
    assert "image" not in items[2]


def test_build_gallery_for_unplaced():
    figs = [{"n": 1, "caption": "Fig. 1", "file": "s/fig1.png", "page": 1},
            {"n": 2, "caption": "Fig. 2", "file": "s/fig2.png", "page": 1}]
    gallery = build_gallery_section(figs, placed={1})
    assert gallery is not None
    items = gallery["subsections"][0]["items"]
    assert len(items) == 1
    assert items[0]["image"]["n"] == 2


def test_no_gallery_when_all_placed():
    figs = [{"n": 1, "caption": "Fig. 1", "file": "s/fig1.png", "page": 1}]
    assert build_gallery_section(figs, placed={1}) is None

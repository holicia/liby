from services.discord_format import seconds_to_mmss, chapter_link, build_embed


def test_seconds_to_mmss_minutes_and_hours():
    assert seconds_to_mmss(0) == "0:00"
    assert seconds_to_mmss(75) == "1:15"
    assert seconds_to_mmss(3661) == "1:01:01"
    assert seconds_to_mmss(-5) == "0:00"


def test_chapter_link_uses_native_youtube_timestamp():
    link = chapter_link("abc12345678", 90, "도입")
    assert link == "[1:30 도입](https://youtu.be/abc12345678?t=90)"


def test_build_embed_youtube_full():
    note = {
        "title": "제목", "summary": "요약 본문", "type": "youtube",
        "insights": ["통찰1", "통찰2"], "tags": ["투자", "심리"],
        "video_id": "vid12345678",
        "timeline": [{"t": 0, "label": "시작"}, {"t": 120, "label": "본론"}],
        "read_url": "http://pc.ts.net:8000/api/items/5/read",
    }
    e = build_embed(note)
    assert e["title"] == "제목"
    assert e["description"] == "요약 본문"
    assert e["url"] == "http://pc.ts.net:8000/api/items/5/read"
    names = [f["name"] for f in e["fields"]]
    assert "💡 핵심" in names
    assert "⏱ 타임라인" in names
    assert "🏷 태그" in names
    tl = next(f["value"] for f in e["fields"] if f["name"] == "⏱ 타임라인")
    assert "https://youtu.be/vid12345678?t=120" in tl
    assert any("read" in f["value"] for f in e["fields"] if f["name"] == "📖 전체 노트")


def test_build_embed_text_note_without_video_has_no_timeline():
    note = {"title": "메모", "summary": "s", "type": "text",
            "insights": [], "tags": [], "read_url": "http://x/1/read"}
    e = build_embed(note)
    names = [f["name"] for f in e["fields"]]
    assert "⏱ 타임라인" not in names


def test_build_embed_truncates_long_summary():
    note = {"title": "t", "summary": "가" * 5000, "type": "text",
            "read_url": "http://x/1/read"}
    e = build_embed(note)
    assert len(e["description"]) <= 1500

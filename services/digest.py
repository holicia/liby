"""프로젝트 통합 정리(digest) 생성.

프로젝트에 속한 노트들의 title/summary/sections heading/tags만 묶어
BridgeProvider로 한 번에 분석. 풀 본문은 토큰 낭비라 보내지 않음.
결과는 {title, summary, insights, clusters} dict.
"""
import json

from services.ai import bridge_client, chunking

PROJECT_DIGEST_PROMPT = """다음은 같은 프로젝트에 속한 노트 {n}개의 요약·섹션 정보입니다.
이를 종합해 이 프로젝트의 통합 정리를 만들어 주세요.

요구사항:
1. 프로젝트 전체가 다루는 큰 주제(한 줄)
2. 2-3문장 종합 요약 — 노트들에 공통적으로 흐르는 메시지
3. 핵심 인사이트 5-7개 — 노트들에 반복적으로 등장하는 깨달음·교훈
4. 노트 클러스터 — 비슷한 주제를 다루는 노트들을 묶고 각 그룹의 설명

응답은 다른 텍스트 없이 아래 JSON 형식으로만 출력하세요.

{{
  "title": "프로젝트 전체 주제 한 줄",
  "summary": "2-3문장 종합 요약",
  "insights": ["인사이트1", "인사이트2", ...],
  "clusters": [
    {{"theme": "테마명", "note_ids": [정수id, ...], "description": "이 클러스터 설명 1-2문장"}}
  ]
}}

노트들:
{notes_block}
"""


def _note_to_block(note: dict) -> str:
    """노트 1개를 prompt에 들어갈 텍스트 블록으로."""
    headings = []
    for sec in (note.get("sections") or []):
        h = sec.get("heading", "").strip()
        if h:
            headings.append(h)
        for sub in (sec.get("subsections") or []):
            sh = sub.get("heading", "").strip()
            if sh:
                headings.append(f"  - {sh}")
    headings_text = "\n  ".join(headings[:30]) if headings else "(없음)"
    tags = ", ".join((note.get("tags") or [])[:8]) or "(없음)"
    return (
        f"[id={note['id']}] {note['title']}\n"
        f"  요약: {(note.get('summary') or '').strip()[:400]}\n"
        f"  섹션:\n  {headings_text}\n"
        f"  태그: {tags}"
    )


def _build_prompt(notes: list[dict]) -> str:
    blocks = "\n\n".join(_note_to_block(n) for n in notes)
    return PROJECT_DIGEST_PROMPT.format(n=len(notes), notes_block=blocks)


async def build_project_digest(
    notes: list[dict], *, adapter: str = "claude",
    cwd: str | None = None, timeout_sec: int = 600,
) -> tuple[dict, str]:
    """프로젝트 노트들을 한 번에 LLM으로 보내 통합 정리. 반환: (digest_dict, model).
    빈 노트 리스트면 ValueError.
    """
    if not notes:
        raise ValueError("정리할 노트가 없습니다")
    prompt = _build_prompt(notes)
    import config
    run = await bridge_client.run_agent(
        prompt, adapter=adapter,
        cwd=cwd or config.BRIDGE_CWD,
        timeout_sec=timeout_sec,
    )
    try:
        data = chunking.extract_json(run.summary)
    except (ValueError, json.JSONDecodeError) as e:
        raise ValueError(
            f"LLM digest 응답 JSON 파싱 실패: {run.summary[:200]}"
        ) from e
    # 정규화: 누락 필드 default
    digest = {
        "title": str(data.get("title", "")).strip(),
        "summary": str(data.get("summary", "")).strip(),
        "insights": [str(s).strip() for s in (data.get("insights") or []) if str(s).strip()],
        "clusters": [
            {
                "theme": str(c.get("theme", "")).strip(),
                "note_ids": [int(i) for i in (c.get("note_ids") or [])
                             if isinstance(i, (int, float)) or (isinstance(i, str) and i.isdigit())],
                "description": str(c.get("description", "")).strip(),
            }
            for c in (data.get("clusters") or [])
            if isinstance(c, dict)
        ],
    }
    return digest, adapter

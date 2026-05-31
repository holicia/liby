import json
import re
import anthropic
from services.ai.base import AIProvider, SummaryResult
import config


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    # Claude가 JSON을 ```json ... ``` 코드 블록으로 감쌀 때 제거
    if raw.startswith("```"):
        raw = re.sub(r'^```(?:json)?\n?', '', raw)
        raw = re.sub(r'\n?```\s*$', '', raw)
    return json.loads(raw.strip())


def _build_chapters(data: dict) -> list[dict]:
    """LLM 응답 dict → 정렬된 [{t:int, label:str}]. 비숫자/누락 t는 건너뜀."""
    chapters = []
    for c in data.get("chapters", []):
        try:
            t = int(float(c["t"]))  # "150", 150, 150.0 모두 허용; "0:00" 등은 건너뜀
        except (KeyError, ValueError, TypeError):
            continue
        chapters.append({"t": t, "label": str(c.get("label", "")).strip()})
    chapters.sort(key=lambda c: c["t"])
    return chapters


def _to_t(val) -> int | None:
    try:
        return int(float(val))  # 150, "150", 150.0 허용; "1:30" 등은 None
    except (TypeError, ValueError):
        return None


def _build_sections(data: dict) -> list[dict]:
    """LLM 응답 dict → 계층형 sections. 각 단계 가드, 잘못된 항목은 건너뜀."""
    out = []
    for sec in data.get("sections", []):
        if not isinstance(sec, dict):
            continue
        heading = str(sec.get("heading", "")).strip()
        if not heading:
            continue
        subs = []
        for sub in sec.get("subsections", []):
            if not isinstance(sub, dict):
                continue
            sub_heading = str(sub.get("heading", "")).strip()
            if not sub_heading:
                continue
            items = []
            for it in sub.get("items", []):
                if not isinstance(it, dict):
                    continue
                text = str(it.get("text", "")).strip()
                if not text:
                    continue
                items.append({"text": text, "refs": _build_refs(it.get("refs", []))})
            sub_obj = {"heading": sub_heading, "items": items}
            st = _to_t(sub.get("t"))
            if st is not None:
                sub_obj["t"] = st
            subs.append(sub_obj)
        sec_obj = {"heading": heading, "subsections": subs}
        sect = _to_t(sec.get("t"))
        if sect is not None:
            sec_obj["t"] = sect
        out.append(sec_obj)
    return out


def _build_paragraphs(data: dict) -> list[dict]:
    """LLM 응답 dict → [{text, refs}]. text 비면 skip; refs는 _build_refs 가드."""
    out = []
    for p in data.get("paragraphs", []):
        if not isinstance(p, dict):
            continue
        text = str(p.get("text", "")).strip()
        if not text:
            continue
        out.append({"text": text, "refs": _build_refs(p.get("refs", []))})
    return out


def _build_refs(refs_raw: list) -> list[dict]:
    """LLM 응답 ref list → [{t, snippet?}]. t 누락/비숫자 skip; snippet 비면 키 생략."""
    out = []
    for r in refs_raw:
        if not isinstance(r, dict):
            continue
        t = _to_t(r.get("t"))
        if t is None:
            continue
        ref = {"t": t}
        snippet = str(r.get("snippet", "")).strip()
        if snippet:
            ref["snippet"] = snippet
        out.append(ref)
    return out


def _renumber_sections(sections: list[dict]) -> list[dict]:
    """sections의 heading prefix 'N. ...'를 1부터 재부여하고
    subsection heading 'M.N ...'의 M도 parent의 새 번호로 갱신.
    items/refs 등 다른 필드는 그대로."""
    out = []
    for new_idx, sec in enumerate(sections, start=1):
        new_sec = dict(sec)
        new_sec["heading"] = re.sub(
            r'^\d+\.\s*', f'{new_idx}. ', sec.get("heading", ""))
        if "subsections" in sec:
            new_subs = []
            for sub in sec["subsections"]:
                new_sub = dict(sub)
                new_sub["heading"] = re.sub(
                    r'^\d+\.(\d+)\s*',
                    lambda m: f'{new_idx}.{m.group(1)} ',
                    sub.get("heading", ""),
                )
                new_subs.append(new_sub)
            new_sec["subsections"] = new_subs
        out.append(new_sec)
    return out


TIER2_PROMPT = """다음 내용을 분석하여 노트를 작성하세요.
기존 주제 목록: {existing_topics}

내용:
{text}

규칙:
- 본문을 4~6개의 짧은 한국어 문단(paragraphs)으로 구성합니다.
- 각 문단(text)을 뒷받침할 원문 1~3개를 refs 리스트에 넣습니다. 각 ref는 {{"t": 시작_시각_초, "snippet": "원문 한 문장(verbatim)"}}.
- 입력 줄에 [m:ss] 형태의 타임스탬프가 있을 때만 t를 채웁니다. 타임스탬프가 없으면 refs를 비웁니다(빈 list).

JSON으로 응답하세요:
{{"title": "제목", "language": "ko|en", "word_count": 숫자, "reading_time_min": 숫자,
  "sections": [],
  "summary": "전체를 아우르는 2~3문장 한 줄 요약",
  "paragraphs": [
    {{"text": "한국어 문단", "refs": [{{"t": 30, "snippet": "원문 한 문장"}}, {{"t": 65, "snippet": "다른 원문"}}]}},
    {{"text": "다른 문단", "refs": []}}
  ],
  "tags": ["태그1", "태그2"],
  "suggested_topic": "기존_주제_중_하나_또는_새_주제명"}}"""

TIER2_CODE_PROMPT = """다음 GitHub 레포지토리 정보를 분석하여 개발자 노트를 작성하세요.
기존 주제 목록: {existing_topics}

레포지토리 정보:
{text}

규칙:
- 본문을 4~6개의 짧은 한국어 문단(paragraphs)으로 구성합니다.
- 코드/문서 소스는 영상 타임스탬프가 없으므로 refs는 항상 빈 리스트로 둡니다.

JSON으로 응답하세요:
{{"title": "owner/repo — 한 줄 설명",
  "language": "ko",
  "word_count": 0, "reading_time_min": 0, "sections": [],
  "summary": "프로젝트 목적과 핵심 기능을 2~3문장으로 설명",
  "paragraphs": [
    {{"text": "한국어 문단", "refs": []}},
    {{"text": "다른 문단", "refs": []}}
  ],
  "tags": ["언어", "프레임워크", "도메인키워드"],
  "suggested_topic": "기존_주제_중_하나_또는_새_주제명"}}"""

DETAILED_PROMPT = """다음 내용을 분석하여 상세 노트를 계층 구조로 작성하세요.
기존 주제 목록: {existing_topics}

내용:
{text}

규칙:
- 본문을 5~12개의 의미 단위 대섹션(heading: "1. ...", "2. ...")으로 나눕니다.
- 각 대섹션은 1개 이상의 소섹션(heading: "1.1 ...")을 가지며, 각 소섹션은 2~4개의 문단형 항목(items)을 가집니다.
- 각 item은 한국어 문단 text와, 그 문단을 뒷받침할 원문 1~3개를 refs 리스트에 넣습니다 (각 ref: {{"t": 시작_시각_초, "snippet": "원문 한 문장(verbatim)"}}).
- 입력 줄에 [m:ss] 형태의 타임스탬프가 있을 때만 t를 채웁니다. 타임스탬프가 없으면 refs는 빈 list, 섹션/소섹션의 t도 생략합니다.

JSON으로만 응답하세요:
{{"title": "제목", "language": "ko|en",
  "summary": "전체를 아우르는 2~3문장 한 줄 요약",
  "tags": ["태그1", "태그2"],
  "suggested_topic": "기존_주제_중_하나_또는_새_주제명",
  "sections": [
    {{"heading": "1. 대주제", "t": 10, "subsections": [
      {{"heading": "1.1 소주제", "items": [
        {{"text": "한국어 문단(2~4문장)", "refs": [{{"t": 12, "snippet": "원문 한 문장"}}, {{"t": 25, "snippet": "다른 원문"}}]}},
        {{"text": "다른 문단", "refs": []}}
      ]}}
    ]}}
  ]}}
(t는 타임스탬프가 있을 때만 넣고, 없으면 키를 생략하세요.)"""

SUMMARY_MERGE_PROMPT = """다음은 한 영상을 여러 조각으로 나눠 분석한 부분 요약들입니다.
이를 합쳐 영상 전체를 자연스럽게 다루는 한국어 2~3문장 통합 요약을 작성하세요.

부분 요약:
{partials}

JSON으로만 응답하세요:
{{"summary": "2~3문장 한국어 통합 요약"}}"""

CHAPTERS_PROMPT = """다음은 타임스탬프가 붙은 영상 자막입니다. 영상을 5~12개의 의미 단위 챕터로 나누세요.
각 챕터는 시작 시각(초)과 짧은 제목(라벨)으로 표현합니다. 시간 오름차순, 첫 챕터는 t=0.

자막:
{transcript}

JSON으로만 응답하세요:
{{"chapters": [{{"t": 0, "label": "인트로"}}, {{"t": 150, "label": "핵심 개념"}}]}}"""

TRANSLATE_CHAPTERS_PROMPT = """다음 영상 챕터 목록의 각 label을 자연스러운 한국어로 번역하세요.
t(시작 시각, 초)는 그대로 두고 label만 번역합니다.

챕터: {chapters}

JSON으로만 응답하세요:
{{"chapters": [{{"t": 0, "label": "번역된 제목"}}]}}"""

TIER3_PROMPT = """다음 요약을 바탕으로 심화 분석을 수행하세요.

요약: {summary}

JSON으로 응답하세요:
{{"insights": ["인사이트1", "인사이트2"],
  "questions_raised": ["질문1", "질문2"]}}"""

CLAUDE_PRICING: dict[str, dict[str, float]] = {
    "claude-haiku-4-5":   {"input": 0.25,  "output": 1.25},
    "claude-sonnet-4-6":  {"input": 3.0,   "output": 15.0},
    "claude-opus-4-7":    {"input": 15.0,  "output": 75.0},
}

def _calc_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    p = CLAUDE_PRICING.get(model, {"input": 3.0, "output": 15.0})
    return (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000

class ClaudeProvider(AIProvider):
    def __init__(self, api_key: str = config.ANTHROPIC_API_KEY) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    def name(self) -> str:
        return "claude"

    async def summarize(
        self,
        text: str,
        source_type: str,
        mode: str,
        existing_topics: list[str],
    ) -> SummaryResult:
        return await self._summarize_single(text, source_type, mode, existing_topics)

    async def _summarize_single(
        self,
        text: str,
        source_type: str,
        mode: str,
        existing_topics: list[str],
    ) -> SummaryResult:
        total_cost = 0.0
        models_used: list[str] = []

        model = config.CLAUDE_MODELS["tier2"]
        if mode == "detailed":
            template = DETAILED_PROMPT
            max_tokens = 8192  # 계층형 sections 출력이 커서 4096이면 JSON이 잘림
        else:
            template = TIER2_CODE_PROMPT if source_type == "code" else TIER2_PROMPT
            max_tokens = 4096
        prompt = template.format(
            text=text[:12000],
            existing_topics=", ".join(existing_topics) or "없음",
        )
        resp = await self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text
        total_cost += _calc_cost(model, resp.usage.input_tokens, resp.usage.output_tokens)
        models_used.append(model)

        data = _parse_json(raw)
        result = SummaryResult(
            title=data.get("title", "제목 없음"),
            language=data.get("language", "ko"),
            word_count=data.get("word_count", 0),
            reading_time_min=data.get("reading_time_min", 0),
            sections=_build_sections(data),
            summary=data.get("summary", ""),
            key_points=data.get("key_points", []),
            paragraphs=_build_paragraphs(data),
            tags=data.get("tags", []),
            suggested_topic=data.get("suggested_topic", ""),
            summary_mode=mode,
            cost_usd=total_cost,
            models_used=models_used,
        )

        if mode == "detailed":
            result = await self._run_tier3(result, total_cost, models_used)

        return result

    async def _merge_partials(
        self,
        partials: list[SummaryResult],
        mode: str,
    ) -> SummaryResult:
        """여러 SummaryResult를 1개로 병합. summary는 LLM 통합 호출."""
        base = partials[0]

        all_paragraphs = [p for prt in partials for p in (prt.paragraphs or [])]
        all_sections = _renumber_sections(
            [s for prt in partials for s in (prt.sections or [])]
        )
        all_insights: list[str] = []
        for prt in partials:
            if prt.insights:
                all_insights.extend(prt.insights)
        all_questions: list[str] = []
        for prt in partials:
            if prt.questions_raised:
                all_questions.extend(prt.questions_raised)
        all_key_points = [k for prt in partials for k in (prt.key_points or [])]
        all_tags = list({t for prt in partials for t in (prt.tags or [])})
        total_cost = sum(prt.cost_usd for prt in partials)
        models_used: list[str] = []
        for prt in partials:
            models_used.extend(prt.models_used or [])

        merged_summary = base.summary
        try:
            partials_text = "\n\n".join(
                f"[조각 {i+1}] {prt.summary}" for i, prt in enumerate(partials) if prt.summary
            )
            if partials_text:
                model = config.CLAUDE_MODELS["tier2"]
                merge_resp = await self._client.messages.create(
                    model=model,
                    max_tokens=512,
                    messages=[{"role": "user", "content": SUMMARY_MERGE_PROMPT.format(partials=partials_text)}],
                )
                merge_raw = merge_resp.content[0].text
                merge_data = _parse_json(merge_raw)
                merged_summary = merge_data.get("summary", base.summary)
                total_cost += _calc_cost(model, merge_resp.usage.input_tokens, merge_resp.usage.output_tokens)
                models_used.append(model)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"summary merge failed, using first partial: {e}")

        return SummaryResult(
            title=base.title,
            language=base.language,
            word_count=sum(prt.word_count for prt in partials),
            reading_time_min=sum(prt.reading_time_min for prt in partials),
            sections=all_sections,
            summary=merged_summary,
            key_points=all_key_points,
            tags=all_tags,
            suggested_topic=base.suggested_topic,
            summary_mode=mode,
            insights=all_insights or None,
            questions_raised=all_questions or None,
            paragraphs=all_paragraphs,
            cost_usd=total_cost,
            models_used=models_used,
        )

    async def generate_chapters(self, transcript: str) -> tuple[list[dict], float, str]:
        model = config.CLAUDE_MODELS["tier2"]
        prompt = CHAPTERS_PROMPT.format(transcript=transcript[:14000])
        resp = await self._client.messages.create(
            model=model, max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        cost = _calc_cost(model, resp.usage.input_tokens, resp.usage.output_tokens)
        try:
            chapters = _build_chapters(_parse_json(resp.content[0].text))
        except (json.JSONDecodeError, ValueError, TypeError):
            chapters = []  # 비정상 응답이어도 챕터는 부가 기능이므로 빈 결과로 폴백
        return chapters, cost, model

    async def translate_chapters(self, chapters: list[dict]) -> tuple[list[dict], float, str]:
        if not chapters:
            return [], 0.0, ""
        model = config.CLAUDE_MODELS["tier2"]
        prompt = TRANSLATE_CHAPTERS_PROMPT.format(chapters=json.dumps(chapters, ensure_ascii=False))
        resp = await self._client.messages.create(
            model=model, max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        cost = _calc_cost(model, resp.usage.input_tokens, resp.usage.output_tokens)
        try:
            translated = _build_chapters(_parse_json(resp.content[0].text))
        except (json.JSONDecodeError, ValueError, TypeError):
            translated = []
        return (translated or chapters), cost, model  # 번역 실패 시 원본 유지

    async def run_tier3(self, summary: str) -> SummaryResult:
        empty = SummaryResult(
            title="", language="ko", word_count=0, reading_time_min=0,
            sections=[], summary=summary, key_points=[], tags=[],
            suggested_topic="", summary_mode="detailed",
        )
        return await self._run_tier3(empty, 0.0, [])

    async def _run_tier3(
        self,
        result: SummaryResult,
        total_cost: float,
        models_used: list[str],
    ) -> SummaryResult:
        model = config.CLAUDE_MODELS["tier3"]
        prompt = TIER3_PROMPT.format(summary=result.summary)
        resp = await self._client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        data = _parse_json(resp.content[0].text)
        total_cost += _calc_cost(model, resp.usage.input_tokens, resp.usage.output_tokens)
        models_used.append(model)

        result.insights = data.get("insights", [])
        result.questions_raised = data.get("questions_raised", [])
        result.cost_usd = total_cost
        result.models_used = models_used
        return result

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
                lead = str(it.get("lead", "")).strip()
                bullets = [str(b).strip() for b in it.get("bullets", []) if str(b).strip()]
                if not lead and not bullets:
                    continue
                item = {"lead": lead, "bullets": bullets}
                t = _to_t(it.get("t"))
                if t is not None:
                    item["t"] = t
                items.append(item)
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
    """LLM 응답 dict → [{text, quote?, t?}]. text 비면 skip; t는 _to_t 가드."""
    out = []
    for p in data.get("paragraphs", []):
        if not isinstance(p, dict):
            continue
        text = str(p.get("text", "")).strip()
        if not text:
            continue
        block = {"text": text}
        quote = str(p.get("quote", "")).strip()
        if quote:
            block["quote"] = quote
        t = _to_t(p.get("t"))
        if t is not None:
            block["t"] = t
        out.append(block)
    return out


TIER2_PROMPT = """다음 내용을 분석하여 노트를 작성하세요.
기존 주제 목록: {existing_topics}

내용:
{text}

JSON으로 응답하세요:
{{"title": "제목", "language": "ko|en", "word_count": 숫자,
  "reading_time_min": 숫자, "sections": [],
  "summary": "5~10문장 요약",
  "key_points": ["핵심1", "핵심2", "핵심3"],
  "tags": ["태그1", "태그2"],
  "suggested_topic": "기존_주제_중_하나_또는_새_주제명"}}"""

TIER2_CODE_PROMPT = """다음 GitHub 레포지토리 정보를 분석하여 개발자 노트를 작성하세요.
기존 주제 목록: {existing_topics}

레포지토리 정보:
{text}

JSON으로 응답하세요:
{{"title": "owner/repo — 한 줄 설명",
  "language": "ko",
  "word_count": 0,
  "reading_time_min": 0,
  "sections": [],
  "summary": "프로젝트 목적과 핵심 기능을 3~5문장으로 설명",
  "key_points": ["기술 스택: ...", "주요 기능: ...", "아키텍처 특징: ..."],
  "tags": ["언어", "프레임워크", "도메인키워드"],
  "suggested_topic": "기존_주제_중_하나_또는_새_주제명"}}"""

DETAILED_PROMPT = """다음 내용을 분석하여 상세 노트를 계층 구조로 작성하세요.
기존 주제 목록: {existing_topics}

내용:
{text}

규칙:
- 본문을 5~12개의 의미 단위 대섹션(heading: "1. ...", "2. ...")으로 나눕니다.
- 각 대섹션은 1개 이상의 소섹션(heading: "1.1 ...")을 가지며, 각 소섹션은 굵게 강조할 핵심 항목(lead)과 그 아래 2~5개의 세부 불릿(bullets)을 가집니다.
- 입력 줄에 [m:ss] 형태의 타임스탬프가 있으면, 해당 섹션/소섹션/항목이 시작되는 지점의 t를 "초 단위 정수"로 채웁니다. 타임스탬프가 없으면 t는 생략합니다.

JSON으로만 응답하세요:
{{"title": "제목", "language": "ko|en",
  "summary": "전체를 아우르는 2~3문장 한 줄 요약",
  "tags": ["태그1", "태그2"],
  "suggested_topic": "기존_주제_중_하나_또는_새_주제명",
  "sections": [
    {{"heading": "1. 대주제", "t": 10, "subsections": [
      {{"heading": "1.1 소주제", "items": [
        {{"lead": "굵은 소제목", "bullets": ["세부 1", "세부 2"]}}
      ]}}
    ]}}
  ]}}
(위 예시에서 보듯 t는 타임스탬프가 있을 때만 넣고, 없으면 키 자체를 생략하세요.)"""

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
            tags=data.get("tags", []),
            suggested_topic=data.get("suggested_topic", ""),
            summary_mode=mode,
            cost_usd=total_cost,
            models_used=models_used,
        )

        if mode == "detailed":
            result = await self._run_tier3(result, total_cost, models_used)

        return result

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

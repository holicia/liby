import json
from openai import AsyncOpenAI
from services.ai.base import AIProvider, SummaryResult
from services.ai.claude import TIER2_PROMPT, TIER2_CODE_PROMPT, TIER3_PROMPT, CHAPTERS_PROMPT, DETAILED_PROMPT, TRANSLATE_CHAPTERS_PROMPT, SUMMARY_MERGE_PROMPT, _build_chapters, _build_sections, _build_paragraphs, _renumber_sections
import config

GPT_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o-mini": {"input": 0.15,  "output": 0.60},
    "gpt-4o":      {"input": 2.50,  "output": 10.0},
    "o1-mini":     {"input": 3.0,   "output": 12.0},
}

def _calc_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    p = GPT_PRICING.get(model, {"input": 2.50, "output": 10.0})
    return (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000

class OpenAIProvider(AIProvider):
    def __init__(self, api_key: str = config.OPENAI_API_KEY) -> None:
        self._client = AsyncOpenAI(api_key=api_key)

    def name(self) -> str:
        return "gpt"

    async def summarize(
        self,
        text: str,
        source_type: str,
        mode: str,
        existing_topics: list[str],
    ) -> SummaryResult:
        from services.ai.claude import CHUNK_THRESHOLD
        if len(text) <= CHUNK_THRESHOLD:
            return await self._summarize_single(text, source_type, mode, existing_topics)
        from services.extractor import _chunk_for_llm
        chunks = _chunk_for_llm(text)
        partials: list[SummaryResult] = []
        for chunk in chunks:
            try:
                partial = await self._summarize_single(chunk, source_type, mode, existing_topics)
                partials.append(partial)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"chunk {len(partials)+1} failed: {e}")
        if not partials:
            raise ValueError("청킹 분석 실패: 모든 chunk 호출 실패")
        return await self._merge_partials(partials, mode)

    async def _summarize_single(
        self,
        text: str,
        source_type: str,
        mode: str,
        existing_topics: list[str],
    ) -> SummaryResult:
        total_cost = 0.0
        models_used: list[str] = []
        model = config.GPT_MODELS["tier2"]

        if mode == "detailed":
            template = DETAILED_PROMPT
        else:
            template = TIER2_CODE_PROMPT if source_type == "code" else TIER2_PROMPT
        prompt = template.format(
            text=text[:12000],
            existing_topics=", ".join(existing_topics) or "없음",
        )
        resp = await self._client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content
        total_cost += _calc_cost(model, resp.usage.prompt_tokens, resp.usage.completion_tokens)
        models_used.append(model)

        if raw is None:
            # 안전 필터/길이 초과 등으로 content가 비는 경우 finish_reason을 메시지에 노출
            raise ValueError(f"GPT가 빈 응답을 반환했습니다(model={model}, finish_reason={resp.choices[0].finish_reason})")
        data = json.loads(raw)
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
            result = await self._gpt_tier3(result, total_cost, models_used)

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
                model = config.GPT_MODELS["tier2"]
                merge_resp = await self._client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": SUMMARY_MERGE_PROMPT.format(partials=partials_text)}],
                    response_format={"type": "json_object"},
                )
                merge_raw = merge_resp.choices[0].message.content
                if merge_raw:
                    merge_data = json.loads(merge_raw)
                    merged_summary = merge_data.get("summary", base.summary)
                total_cost += _calc_cost(model, merge_resp.usage.prompt_tokens, merge_resp.usage.completion_tokens)
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

    async def _gpt_tier3(
        self,
        result: SummaryResult,
        total_cost: float,
        models_used: list[str],
    ) -> SummaryResult:
        tier3_model = config.GPT_MODELS["tier3"]
        t3_prompt = TIER3_PROMPT.format(summary=result.summary)
        t3_resp = await self._client.chat.completions.create(
            model=tier3_model,
            messages=[{"role": "user", "content": t3_prompt}],
            response_format={"type": "json_object"},
        )
        t3_raw = t3_resp.choices[0].message.content
        if t3_raw is None:
            raise ValueError(f"GPT tier3가 빈 응답을 반환했습니다(model={tier3_model}, finish_reason={t3_resp.choices[0].finish_reason})")
        t3_data = json.loads(t3_raw)
        total_cost += _calc_cost(tier3_model, t3_resp.usage.prompt_tokens, t3_resp.usage.completion_tokens)
        models_used.append(tier3_model)
        result.insights = t3_data.get("insights", [])
        result.questions_raised = t3_data.get("questions_raised", [])
        result.cost_usd = total_cost
        result.models_used = models_used
        return result

    async def generate_chapters(self, transcript: str) -> tuple[list[dict], float, str]:
        model = config.GPT_MODELS["tier2"]
        prompt = CHAPTERS_PROMPT.format(transcript=transcript[:14000])
        resp = await self._client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        cost = _calc_cost(model, resp.usage.prompt_tokens, resp.usage.completion_tokens)
        try:
            chapters = _build_chapters(json.loads(resp.choices[0].message.content))
        except (json.JSONDecodeError, ValueError, TypeError):
            chapters = []
        return chapters, cost, model

    async def translate_chapters(self, chapters: list[dict]) -> tuple[list[dict], float, str]:
        if not chapters:
            return [], 0.0, ""
        model = config.GPT_MODELS["tier2"]
        prompt = TRANSLATE_CHAPTERS_PROMPT.format(chapters=json.dumps(chapters, ensure_ascii=False))
        resp = await self._client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        cost = _calc_cost(model, resp.usage.prompt_tokens, resp.usage.completion_tokens)
        try:
            translated = _build_chapters(json.loads(resp.choices[0].message.content))
        except (json.JSONDecodeError, ValueError, TypeError):
            translated = []
        return (translated or chapters), cost, model

    async def run_tier3(self, summary: str) -> SummaryResult:
        empty = SummaryResult(
            title="", language="ko", word_count=0, reading_time_min=0,
            sections=[], summary=summary, key_points=[], tags=[],
            suggested_topic="", summary_mode="detailed",
        )
        return await self._gpt_tier3(empty, 0.0, [])

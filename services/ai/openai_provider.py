import json
from openai import AsyncOpenAI
from services.ai.base import AIProvider, SummaryResult
from services.ai.claude import TIER2_PROMPT, TIER2_CODE_PROMPT, TIER3_PROMPT
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
        total_cost = 0.0
        models_used: list[str] = []
        model = config.GPT_MODELS["tier2"]

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

        data = json.loads(raw)
        result = SummaryResult(
            title=data.get("title", "제목 없음"),
            language=data.get("language", "ko"),
            word_count=data.get("word_count", 0),
            reading_time_min=data.get("reading_time_min", 0),
            sections=data.get("sections", []),
            summary=data.get("summary", ""),
            key_points=data.get("key_points", []),
            tags=data.get("tags", []),
            suggested_topic=data.get("suggested_topic", ""),
            summary_mode=mode,
            cost_usd=total_cost,
            models_used=models_used,
        )

        if mode == "detailed":
            result = await self._gpt_tier3(result, total_cost, models_used)

        return result

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
        t3_data = json.loads(t3_resp.choices[0].message.content)
        total_cost += _calc_cost(tier3_model, t3_resp.usage.prompt_tokens, t3_resp.usage.completion_tokens)
        models_used.append(tier3_model)
        result.main_arguments = t3_data.get("main_arguments", [])
        result.insights = t3_data.get("insights", [])
        result.questions_raised = t3_data.get("questions_raised", [])
        result.related_concepts = t3_data.get("related_concepts", [])
        result.cost_usd = total_cost
        result.models_used = models_used
        return result

    async def run_tier3(self, summary: str) -> SummaryResult:
        empty = SummaryResult(
            title="", language="ko", word_count=0, reading_time_min=0,
            sections=[], summary=summary, key_points=[], tags=[],
            suggested_topic="", summary_mode="detailed",
        )
        return await self._gpt_tier3(empty, 0.0, [])

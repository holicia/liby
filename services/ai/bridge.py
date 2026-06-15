"""BridgeProvider: 모든 LLM 호출을 agent-runner-bridge로 위임.

구독 인증(Claude Pro / ChatGPT Plus)이 설정된 bridge에 연결되어 있으면
cost_usd=0으로 동일한 분석 결과를 받을 수 있다.
"""
import json
from services.ai.base import AIProvider, SummaryResult
from services.ai import chunking
from services.ai import bridge_client
from services.ai.claude import (
    TIER2_PROMPT, TIER2_CODE_PROMPT, DETAILED_PROMPT, PAPER_PROMPT,
    CHAPTERS_PROMPT, TRANSLATE_CHAPTERS_PROMPT,
)

# 논문 단일 분석 시 전송할 본문 최대 길이. 영상 청킹(12K)보다 크게 잡아
# 초록·방법·결과·결론을 한 번에 담는다.
_PAPER_TEXT_LIMIT = 45000
import config

_VALID_ADAPTERS = {"claude", "codex"}


class BridgeProvider(AIProvider):
    def __init__(self, adapter: str) -> None:
        if adapter not in _VALID_ADAPTERS:
            raise ValueError(
                f"adapter는 {sorted(_VALID_ADAPTERS)} 중 하나여야 합니다: {adapter}"
            )
        if not config.BRIDGE_TOKEN:
            raise RuntimeError("BRIDGE_TOKEN 미설정: .env에 BRIDGE_TOKEN을 설정하세요.")
        self._adapter = adapter

    def name(self) -> str:
        return f"{self._adapter}-cli"

    async def summarize(
        self, text: str, source_type: str, mode: str,
        existing_topics: list[str],
    ) -> SummaryResult:
        if len(text) <= chunking.CHUNK_THRESHOLD:
            return await self._summarize_single(text, source_type, mode, existing_topics)
        chunks = chunking.chunk_for_llm(text)
        partials: list[SummaryResult] = []
        for chunk in chunks:
            try:
                hint = chunking.chunk_range_hint(chunk)
                partial = await self._summarize_single(
                    chunk, source_type, mode, existing_topics, chunk_info=hint)
                partials.append(partial)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(
                    f"chunk {len(partials)+1} failed: {e}")
        if not partials:
            raise ValueError("청킹 분석 실패: 모든 chunk 호출 실패")
        return await self._merge_partials(partials, mode)

    async def _summarize_single(
        self, text: str, source_type: str, mode: str,
        existing_topics: list[str], chunk_info: str | None = None,
    ) -> SummaryResult:
        if mode == "detailed":
            template = DETAILED_PROMPT
        else:
            template = TIER2_CODE_PROMPT if source_type == "code" else TIER2_PROMPT
        text_prefix = (
            f"[조각 정보] 이 입력은 영상의 일부입니다: {chunk_info}. "
            f"모든 sections/items/refs의 t는 반드시 이 범위 안의 [m:ss] 값을 그대로 사용하세요.\n\n"
            if chunk_info else ""
        )
        prompt = template.format(
            text=text_prefix + text[:12000],
            existing_topics=", ".join(existing_topics) or "없음",
        )
        run = await bridge_client.run_agent(
            prompt, adapter=self._adapter, cwd=config.BRIDGE_CWD,
            timeout_sec=config.BRIDGE_TIMEOUT_SEC,
        )
        try:
            data = chunking.extract_json(run.summary)
        except (ValueError, json.JSONDecodeError) as e:
            raise ValueError(
                f"LLM 응답 JSON 파싱 실패: {run.summary[:200]}"
            ) from e
        return SummaryResult(
            title=data.get("title", "제목 없음"),
            language=data.get("language", "ko"),
            word_count=data.get("word_count", 0),
            reading_time_min=data.get("reading_time_min", 0),
            sections=chunking.build_sections(data),
            summary=data.get("summary", ""),
            key_points=data.get("key_points", []),
            tags=data.get("tags", []),
            suggested_topic=data.get("suggested_topic", ""),
            summary_mode=mode,
            insights=data.get("insights"),
            questions_raised=data.get("questions_raised"),
            paragraphs=chunking.build_paragraphs(data),
            cost_usd=run.usage.total_cost_usd,
            models_used=[self._adapter],
        )

    async def _merge_partials(
        self, partials: list[SummaryResult], mode: str,
    ) -> SummaryResult:
        base = partials[0]
        all_paragraphs = [p for prt in partials for p in (prt.paragraphs or [])]
        merged_sections = [s for prt in partials for s in (prt.sections or [])]
        merged_sections.sort(key=lambda s: s.get("t", float("inf")))
        all_sections = chunking.renumber_sections(merged_sections)
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
                run = await bridge_client.run_agent(
                    chunking.SUMMARY_MERGE_PROMPT.format(partials=partials_text),
                    adapter=self._adapter, cwd=config.BRIDGE_CWD,
                    timeout_sec=config.BRIDGE_TIMEOUT_SEC,
                )
                merge_data = chunking.extract_json(run.summary)
                merged_summary = merge_data.get("summary", base.summary)
                total_cost += run.usage.total_cost_usd
                models_used.append(self._adapter)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                f"summary merge failed, using first partial: {e}")

        return SummaryResult(
            title=base.title, language=base.language,
            word_count=sum(prt.word_count for prt in partials),
            reading_time_min=sum(prt.reading_time_min for prt in partials),
            sections=all_sections, summary=merged_summary,
            key_points=all_key_points, tags=all_tags,
            suggested_topic=base.suggested_topic, summary_mode=mode,
            insights=all_insights or None,
            questions_raised=all_questions or None,
            paragraphs=all_paragraphs, cost_usd=total_cost,
            models_used=models_used,
        )

    async def summarize_paper(
        self, text: str, figures_manifest: str, existing_topics: list[str],
    ) -> SummaryResult:
        figures_block = (
            f"사용 가능한 그림(번호와 캡션):\n{figures_manifest}\n"
            if figures_manifest else "사용 가능한 그림: 없음\n"
        )
        prompt = PAPER_PROMPT.format(
            text=text[:_PAPER_TEXT_LIMIT],
            existing_topics=", ".join(existing_topics) or "없음",
            figures=figures_block,
        )
        # PDF task는 워커 자동 재시도 대상이 아니므로(비영구화), 비결정적 빈/깨진
        # 응답을 여기서 직접 1회 더 시도한다.
        last_err = "알 수 없음"
        for attempt in range(2):
            run = await bridge_client.run_agent(
                prompt, adapter=self._adapter, cwd=config.BRIDGE_CWD,
                timeout_sec=config.BRIDGE_TIMEOUT_SEC,
            )
            try:
                data = chunking.extract_json(run.summary)
            except (ValueError, json.JSONDecodeError):
                last_err = f"JSON 파싱 실패: {run.summary[:150]}"
                continue
            sections = chunking.build_sections(data)
            if not sections and not data.get("summary"):
                last_err = f"빈 응답: {run.summary[:150]}"
                continue
            break
        else:
            raise ValueError(f"논문 분석 실패(2회 시도): {last_err}")
        return SummaryResult(
            title=data.get("title", "제목 없음"),
            language=data.get("language", "ko"),
            word_count=data.get("word_count", 0),
            reading_time_min=data.get("reading_time_min", 0),
            sections=sections,
            summary=data.get("summary", ""),
            key_points=data.get("key_points", []),
            tags=data.get("tags", []),
            suggested_topic=data.get("suggested_topic", ""),
            summary_mode="detailed",
            insights=data.get("insights"),
            questions_raised=data.get("questions_raised"),
            paragraphs=chunking.build_paragraphs(data),
            cost_usd=run.usage.total_cost_usd,
            models_used=[self._adapter],
        )

    async def run_tier3(self, summary: str) -> SummaryResult:
        return await self.summarize(summary, "fallback", "detailed", [])

    async def generate_chapters(self, transcript: str) -> tuple[list[dict], float, str]:
        prompt = CHAPTERS_PROMPT.format(transcript=transcript[:14000])
        try:
            run = await bridge_client.run_agent(
                prompt, adapter=self._adapter, cwd=config.BRIDGE_CWD,
                timeout_sec=config.BRIDGE_TIMEOUT_SEC,
            )
        except bridge_client.BridgeError as e:
            import logging
            logging.getLogger(__name__).warning(f"generate_chapters bridge call failed: {e}")
            return [], 0.0, self._adapter
        try:
            chapters = chunking.build_chapters(chunking.extract_json(run.summary))
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            return [], run.usage.total_cost_usd, self._adapter
        return chapters, run.usage.total_cost_usd, self._adapter

    async def translate_chapters(self, chapters: list[dict]) -> tuple[list[dict], float, str]:
        if not chapters:
            return [], 0.0, ""
        prompt = TRANSLATE_CHAPTERS_PROMPT.format(
            chapters=json.dumps(chapters, ensure_ascii=False))
        try:
            run = await bridge_client.run_agent(
                prompt, adapter=self._adapter, cwd=config.BRIDGE_CWD,
                timeout_sec=config.BRIDGE_TIMEOUT_SEC,
            )
        except bridge_client.BridgeError as e:
            import logging
            logging.getLogger(__name__).warning(f"translate_chapters bridge call failed: {e}")
            return chapters, 0.0, self._adapter
        try:
            translated = chunking.build_chapters(chunking.extract_json(run.summary))
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            return chapters, run.usage.total_cost_usd, self._adapter
        return (translated or chapters), run.usage.total_cost_usd, self._adapter

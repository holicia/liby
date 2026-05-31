import subprocess
import shutil
import json
from services.ai.base import AIProvider, SummaryResult
from services.ai.claude import _build_paragraphs

FALLBACK_PROMPT = """다음 내용을 분석하여 JSON으로 응답하세요.

내용:
{text}

JSON 형식:
{{"title": "제목", "language": "ko", "word_count": 숫자,
  "reading_time_min": 숫자, "sections": [],
  "summary": "전체를 아우르는 2~3문장 한 줄 요약",
  "paragraphs": [
    {{"text": "한국어 문단", "refs": []}},
    {{"text": "다른 문단", "refs": []}}
  ],
  "tags": ["태그1"],
  "suggested_topic": "주제명"}}"""

def _detect_cli() -> tuple[str, str] | tuple[None, None]:
    if shutil.which("claude"):
        return "claude", "claude"
    if shutil.which("codex"):
        return "codex", "codex"
    return None, None

def _run_cli(cli: str, prompt: str) -> str:
    result = subprocess.run(
        [cli, prompt],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        raise RuntimeError(f"{cli} CLI 오류: {result.stderr}")
    return result.stdout.strip()

class FallbackProvider(AIProvider):
    def __init__(self) -> None:
        self._cli_name, self._cli_cmd = _detect_cli()

    def is_available(self) -> bool:
        return self._cli_name is not None

    def name(self) -> str:
        return self._cli_name or "fallback"

    async def summarize(
        self,
        text: str,
        source_type: str,
        mode: str,
        existing_topics: list[str],
    ) -> SummaryResult:
        if not self.is_available():
            raise RuntimeError("CLI 폴백 없음: claude, codex 중 하나를 설치하세요.")
        prompt = FALLBACK_PROMPT.format(text=text[:8000])
        raw = _run_cli(self._cli_cmd, prompt)
        start = raw.find("{")
        end = raw.rfind("}") + 1
        data = json.loads(raw[start:end])
        return SummaryResult(
            title=data.get("title", "제목 없음"),
            language=data.get("language", "ko"),
            word_count=data.get("word_count", 0),
            reading_time_min=data.get("reading_time_min", 0),
            sections=data.get("sections", []),
            summary=data.get("summary", ""),
            key_points=data.get("key_points", []),
            paragraphs=_build_paragraphs(data),
            tags=data.get("tags", []),
            suggested_topic=data.get("suggested_topic", ""),
            summary_mode=mode,
            cost_usd=0.0,
            models_used=[self._cli_name],
        )

    async def run_tier3(self, summary: str) -> SummaryResult:
        return await self.summarize(summary, "fallback", "detailed", [])

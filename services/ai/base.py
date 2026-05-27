from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SummaryResult:
    title: str
    language: str
    word_count: int
    reading_time_min: int
    sections: list[dict]  # detailed: 계층 섹션 [{heading, t?, subsections:[...]}]; quick: []
    summary: str
    key_points: list[str]
    tags: list[str]
    suggested_topic: str
    summary_mode: str  # "quick" | "detailed"
    main_arguments: Optional[list[str]] = None
    insights: Optional[list[str]] = None
    questions_raised: Optional[list[str]] = None
    zettel_links: Optional[list[int]] = None
    related_concepts: Optional[list[str]] = None
    cost_usd: float = 0.0
    models_used: list[str] = field(default_factory=list)


class AIProvider(ABC):
    @abstractmethod
    async def summarize(
        self,
        text: str,
        source_type: str,
        mode: str,
        existing_topics: list[str],
    ) -> SummaryResult:
        ...

    @abstractmethod
    async def run_tier3(self, summary: str) -> SummaryResult:
        ...

    @abstractmethod
    def name(self) -> str:
        ...

    async def generate_chapters(self, transcript: str) -> tuple[list[dict], float, str]:
        """타임스탬프 자막 → [{t,label}] 챕터. 기본은 빈 결과(프로바이더가 오버라이드)."""
        return [], 0.0, ""

    async def translate_chapters(self, chapters: list[dict]) -> tuple[list[dict], float, str]:
        """챕터 라벨을 한국어로 번역. 기본은 원본 그대로(프로바이더가 오버라이드)."""
        return chapters, 0.0, ""

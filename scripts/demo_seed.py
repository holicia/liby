"""데모용 노트를 빈 DB에 삽입한다 (스크린샷·체험용 — 실 데이터 불필요).

사용: DB_PATH=./demo.db VAULT_PATH=./demo-vault python scripts/demo_seed.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from models import init_db
from services.ai.base import SummaryResult
from services.storage import save_note

NOTES = [
    SummaryResult(
        title="트랜스포머 아키텍처 한 시간 정리",
        language="ko", word_count=8400, reading_time_min=6,
        sections=[], summary="어텐션 메커니즘이 RNN의 순차 처리 한계를 어떻게 극복하는지를 셀프 어텐션, 멀티헤드, 포지셔널 인코딩 순으로 설명한다.",
        key_points=["셀프 어텐션은 시퀀스 전체를 한 번에 본다", "멀티헤드는 서로 다른 관계를 병렬로 학습", "인코더-디코더 구조의 분업"],
        tags=["AI", "딥러닝", "트랜스포머"], suggested_topic="머신러닝",
        summary_mode="quick",
        paragraphs=[{"text": "어텐션은 쿼리·키·밸류의 가중합으로 문맥을 만든다.", "t": 312}],
    ),
    SummaryResult(
        title="SQLite는 어떻게 단일 파일로 ACID를 보장하는가",
        language="ko", word_count=5200, reading_time_min=4,
        sections=[], summary="WAL 모드와 저널링이 어떻게 동시성과 내구성을 동시에 제공하는지 내부 구조 중심으로 다룬다.",
        key_points=["WAL은 읽기와 쓰기를 분리한다", "체크포인트 주기가 성능을 좌우", "단일 작성자 모델의 트레이드오프"],
        tags=["데이터베이스", "SQLite"], suggested_topic="데이터베이스",
        summary_mode="quick",
        paragraphs=[{"text": "WAL 파일은 커밋 로그이자 읽기 스냅샷의 원천이다."}],
    ),
    SummaryResult(
        title="개인 지식 관리, 수집보다 연결이 중요하다",
        language="ko", word_count=3100, reading_time_min=3,
        sections=[], summary="제텔카스텐의 핵심은 노트의 양이 아니라 노트 사이의 연결 밀도라는 주장. 수집 단계에서 연결 후보를 만드는 습관을 제안한다.",
        key_points=["연결 없는 수집은 디지털 창고", "요약 시점에 태그·토픽을 강제하는 이유", "재방문 트리거 설계"],
        tags=["PKM", "제텔카스텐"], suggested_topic="지식관리",
        summary_mode="quick",
        paragraphs=[{"text": "노트는 쓰는 순간이 아니라 다시 만나는 순간 가치가 생긴다."}],
    ),
]

async def main() -> None:
    assert "demo" in config.DB_PATH, f"실 DB 보호: DB_PATH에 'demo'가 포함돼야 함 ({config.DB_PATH})"
    await init_db()
    types_urls = [
        ("youtube", "https://youtu.be/dQw4w9WgXcQ"),
        ("text", ""),
        ("markdown", ""),
    ]
    for result, (src_type, url) in zip(NOTES, types_urls):
        nid = await save_note(config.DB_PATH, config.VAULT_PATH, src_type, url, result, "claude-cli")
        print(f"seeded note #{nid}: {result.title}")

if __name__ == "__main__":
    asyncio.run(main())

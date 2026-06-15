"""PDF 본문에서 그림(figure)을 캡션과 함께 추출한다.

논문 요약 노트에 주요 그림을 흐름에 맞게 끼워 넣기 위해 사용한다.
각 그림은 'Fig N'/'Figure N'/'그림 N' 캡션과 위치(bbox) 근접도로 짝지어진다.
"""
import os
import re
import fitz

# 캡션으로 인정할 패턴 — 그림 번호를 캡처한다.
_CAP_RE = re.compile(
    r'^\s*(?:fig(?:ure)?\.?|그림|圖)\s*[\.\:]?\s*(\d{1,3})\b',
    re.IGNORECASE,
)
# 너무 작은 이미지(로고·아이콘·수식 조각)는 제외.
_MIN_W = 120
_MIN_H = 90
_MIN_BYTES = 3000


def _caption_number(text: str) -> int | None:
    m = _CAP_RE.match(text.strip())
    return int(m.group(1)) if m else None


def _clean_caption(text: str) -> str:
    one = " ".join(text.split())
    return one[:300]


def extract_figures(pdf_path: str, out_dir: str, slug: str) -> list[dict]:
    """PDF에서 그림을 추출해 out_dir/slug/figN.<ext>로 저장.

    반환: [{"n": 1, "file": "slug/fig1.png", "caption": "Fig. 1. ...", "page": 1}]
    그림 번호 오름차순, 중복 번호는 첫 번째만.
    """
    save_root = os.path.join(out_dir, slug)
    figures: dict[int, dict] = {}

    with fitz.open(pdf_path) as doc:
        for pno in range(len(doc)):
            page = doc[pno]
            # 이 페이지의 캡션들: (figure_number, caption_text, bbox)
            captions = []
            for b in page.get_text("blocks"):
                btext = b[4]
                n = _caption_number(btext)
                if n is not None:
                    captions.append((n, _clean_caption(btext), fitz.Rect(b[:4])))
            if not captions:
                continue

            # 이 페이지의 이미지들: (xref, bbox)
            img_rects = []
            for img in page.get_images(full=True):
                xref = img[0]
                try:
                    rects = page.get_image_rects(xref)
                except Exception:
                    rects = []
                for r in rects:
                    img_rects.append((xref, r))

            # 각 캡션을 '바로 위에 있는 가장 가까운 이미지'와 짝짓는다.
            for n, cap_text, cap_rect in captions:
                if n in figures:
                    continue
                best = None
                best_gap = None
                for xref, r in img_rects:
                    # 이미지가 캡션 위에 있고(아래 경계가 캡션 위 경계보다 위),
                    # 수평으로 겹치는지 확인.
                    gap = cap_rect.y0 - r.y1
                    horizontal_overlap = min(r.x1, cap_rect.x1) - max(r.x0, cap_rect.x0)
                    if gap >= -5 and horizontal_overlap > 0:
                        if best_gap is None or gap < best_gap:
                            best_gap = gap
                            best = (xref, r)
                if best is None:
                    continue
                xref, r = best
                if r.width < _MIN_W or r.height < _MIN_H:
                    continue
                try:
                    extracted = doc.extract_image(xref)
                except Exception:
                    continue
                data = extracted.get("image")
                ext = extracted.get("ext", "png")
                if not data or len(data) < _MIN_BYTES:
                    continue
                os.makedirs(save_root, exist_ok=True)
                fname = f"fig{n}.{ext}"
                with open(os.path.join(save_root, fname), "wb") as f:
                    f.write(data)
                figures[n] = {
                    "n": n,
                    "file": f"{slug}/{fname}",
                    "caption": cap_text,
                    "page": pno + 1,
                }

    return [figures[k] for k in sorted(figures)]


def figures_manifest(figures: list[dict]) -> str:
    """LLM 프롬프트에 넣을 그림 목록 문자열. 비어 있으면 빈 문자열."""
    if not figures:
        return ""
    lines = [f"[그림{f['n']}] {f['caption']}" for f in figures]
    return "\n".join(lines)


def attach_figures_to_sections(sections: list[dict], figures: list[dict]) -> set[int]:
    """sections.items의 'figure' 번호를 실제 그림 {file, caption}로 치환.
    배치된 그림 번호 집합을 반환. 알 수 없는 번호의 figure 키는 제거."""
    by_n = {f["n"]: f for f in figures}
    placed: set[int] = set()
    for sec in sections:
        for sub in sec.get("subsections", []):
            for it in sub.get("items", []):
                n = it.pop("figure", None)
                if n in by_n:
                    it["image"] = {
                        "file": by_n[n]["file"],
                        "caption": by_n[n]["caption"],
                        "n": n,
                    }
                    placed.add(n)
    return placed


def build_gallery_section(figures: list[dict], placed: set[int]) -> dict | None:
    """LLM이 본문에 배치하지 못한 그림들을 모아 마지막 '주요 그림' 섹션으로 만든다.
    모두 배치됐으면 None."""
    leftover = [f for f in figures if f["n"] not in placed]
    if not leftover:
        return None
    items = [
        {"text": f["caption"], "refs": [],
         "image": {"file": f["file"], "caption": f["caption"], "n": f["n"]}}
        for f in leftover
    ]
    return {"heading": "주요 그림", "subsections": [{"heading": "본문에서 다루지 못한 그림", "items": items}]}

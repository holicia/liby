def parse_project_id(raw: str) -> int | None:
    """폼에서 받은 project_id 문자열을 int 또는 None으로 변환.

    빈 값/공백은 미분류(None), 숫자가 아니면(잘못된 입력) 안전하게 None으로 처리한다.
    """
    try:
        return int(raw) if raw and raw.strip() else None
    except ValueError:
        return None

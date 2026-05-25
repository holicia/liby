from routers._utils import parse_project_id


def test_parse_project_id_numeric():
    assert parse_project_id("7") == 7


def test_parse_project_id_empty_is_none():
    assert parse_project_id("") is None
    assert parse_project_id("   ") is None


def test_parse_project_id_invalid_is_none():
    assert parse_project_id("abc") is None
    assert parse_project_id("7x") is None

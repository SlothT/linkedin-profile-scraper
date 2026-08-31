from app.linkedin.session import csrf_token_for_li_at, normalize_li_at


def test_normalize_strips_prefix_quotes_and_whitespace() -> None:
    assert normalize_li_at('  li_at="AQEDAtestcookievalue" \n') == "AQEDAtestcookievalue"
    assert normalize_li_at("AQEDAplain") == "AQEDAplain"
    assert normalize_li_at("") == ""


def test_csrf_is_stable_for_same_cookie() -> None:
    first = csrf_token_for_li_at("AQEDAsame")
    second = csrf_token_for_li_at("AQEDAsame")
    assert first == second
    assert first.startswith("ajax:")
    assert first[5:].isdigit()
    assert len(first[5:]) == 19
    assert csrf_token_for_li_at("AQEDAother") != first

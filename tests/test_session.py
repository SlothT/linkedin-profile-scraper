import pytest

from app.linkedin.session import csrf_token_for_li_at, normalize_li_at, parse_session_material


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


def test_parse_bare_li_at() -> None:
    material = parse_session_material("AQEDAbarevalue")
    assert material.li_at == "AQEDAbarevalue"
    assert material.csrf_token == csrf_token_for_li_at("AQEDAbarevalue")
    assert 'li_at=AQEDAbarevalue' in material.cookie_header
    assert f'JSESSIONID="{material.csrf_token}"' in material.cookie_header


def test_parse_full_cookie_header_keeps_companions_and_browser_csrf() -> None:
    raw = (
        'li_at=AQEDAfull; JSESSIONID="ajax:1234567890123456789"; '
        "bcookie=v=2&abc; li_a=AQc; liap=true"
    )
    material = parse_session_material(raw)
    assert material.li_at == "AQEDAfull"
    assert material.csrf_token == "ajax:1234567890123456789"
    assert "bcookie=v=2&abc" in material.cookie_header
    assert "li_a=AQc" in material.cookie_header
    assert "liap=true" in material.cookie_header


def test_parse_requires_li_at() -> None:
    with pytest.raises(ValueError, match="li_at"):
        parse_session_material("bcookie=only")

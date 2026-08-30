import pytest

from app.errors import InvalidProfileURLError
from app.linkedin.urls import extract_vanity_name


@pytest.mark.parametrize(
    "profile_url,expected",
    [
        ("https://www.linkedin.com/in/alex-rivera-demo", "alex-rivera-demo"),
        ("https://www.linkedin.com/in/alex-rivera-demo/", "alex-rivera-demo"),
        ("https://www.linkedin.com/in/alex-rivera-demo?trk=share", "alex-rivera-demo"),
        ("https://www.linkedin.com/in/alex-rivera-demo#about", "alex-rivera-demo"),
        ("http://www.linkedin.com/in/alex-rivera-demo", "alex-rivera-demo"),
        ("linkedin.com/in/foo", "foo"),
        ("https://in.linkedin.com/in/alex-rivera-demo", "alex-rivera-demo"),
        ("https://uk.linkedin.com/in/alex-rivera-demo", "alex-rivera-demo"),
        ("https://WWW.LINKEDIN.COM/in/alex-rivera-demo", "alex-rivera-demo"),
        ("https://www.linkedin.com/in/foo/detail/skills", "foo"),
        ("https://www.linkedin.com/in/%E6%9D%8E%E6%98%8E", "李明"),
    ],
)
def test_accepts_person_profile_urls(profile_url: str, expected: str) -> None:
    assert extract_vanity_name(profile_url) == expected


@pytest.mark.parametrize(
    "profile_url",
    [
        "https://www.linkedin.com/company/northwind",
        "https://www.linkedin.com/school/contoso",
        "https://www.linkedin.com/pub/alex-rivera-demo",
        "https://www.linkedin.com/feed/",
        "alex-rivera-demo",
        "",
        "https://example.com/in/alex-rivera-demo",
        "https://www.linkedin.com/in/",
        "https://www.linkedin.com/in",
    ],
)
def test_rejects_non_person_profile_urls(profile_url: str) -> None:
    with pytest.raises(InvalidProfileURLError):
        extract_vanity_name(profile_url)

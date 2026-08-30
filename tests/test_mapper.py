import pytest

from app.errors import ProfileNotFoundError
from app.linkedin.mapper import UNVERIFIED_SECTIONS, build_profile_data
from app.schemas import TruncationInfo


def test_sample_payload_mapping(sample_payload: dict) -> None:
    data, truncated = build_profile_data(sample_payload)
    assert data.profile.full_name == "Alex Rivera"
    assert data.profile.public_identifier == "alex-rivera-demo"
    assert isinstance(data.profile.headline, str) and data.profile.headline
    assert isinstance(data.profile.about, str) and data.profile.about
    assert data.profile.location is not None
    assert data.profile.location.full == "Springfield, Example State, Exampleland"
    assert data.profile.location.country_code == "IN"
    assert data.profile.industry == "Information Technology & Services"
    assert len(data.experience) == 5
    assert data.experience[0].company_name == "Northwind"
    assert all(item.title is not None for item in data.experience)
    assert sum(1 for item in data.experience if item.date_range and item.date_range.is_current) == 1
    # this member wrote no descriptions, which is a property of this fixture, not of the API
    assert all(item.description is None for item in data.experience)
    assert len(data.education) == 1
    assert data.education[0].field_of_study is not None
    assert not data.education[0].field_of_study.endswith(" ")
    assert data.education[0].grade == "8.09"
    assert data.education[0].date_range is not None
    assert data.education[0].date_range.start is not None
    assert data.education[0].date_range.start.year == 2018
    assert data.education[0].date_range.start.month is None
    assert len(data.skills) == 20
    assert all(isinstance(skill, str) and skill for skill in data.skills)
    assert len(data.certifications) == 7
    assert data.certifications[0].authority == "OpenCourse"
    assert data.certifications[0].issued_on is not None
    assert data.certifications[0].issued_on.year is not None
    assert len(data.languages) == 2
    assert any(language.proficiency == "FULL_PROFESSIONAL" for language in data.languages)
    assert len(data.profile.profile_picture) == 4
    widths = [variant.width for variant in data.profile.profile_picture]
    assert widths == sorted(widths, reverse=True)
    assert len(data.projects) == 0
    assert len(data.featured_media) == 1
    featured = data.featured_media[0]
    assert featured.media_type == "document"
    assert isinstance(featured.url, str) and featured.url
    assert featured.provider_name is None
    assert truncated == {"skills": TruncationInfo(returned=20, total=26)}


def test_rich_payload_mapping(rich_payload: dict) -> None:
    data, truncated = build_profile_data(rich_payload)
    assert data.profile.full_name == "Taylor Quinn"
    assert data.profile.public_identifier == "taylor-quinn-demo"
    assert data.profile.industry == "Computer Software"
    assert data.profile.location is not None
    assert data.profile.location.country_code == "IN"
    assert data.profile.location.full == "Exampleland"
    assert data.profile.location.country == "Exampleland"
    assert len(data.experience) == 3
    assert all(isinstance(item.description, str) and len(item.description) > 100 for item in data.experience)
    none_count = sum(1 for item in data.experience if item.employment_type is None)
    present_count = sum(1 for item in data.experience if item.employment_type is not None)
    assert none_count == 1
    assert present_count == 2
    assert data.profile.profile_picture
    assert data.profile.background_image
    assert len(data.projects) == 2
    assert all(isinstance(project.description, str) and project.description for project in data.projects)
    assert any(project.title and project.title.startswith("ATLAS") for project in data.projects)
    assert all(project.date_range is None for project in data.projects)
    assert len(data.featured_media) == 2
    for entry in data.featured_media:
        assert entry.media_type == "link"
        assert entry.url is not None and entry.url.startswith("https://")
        assert entry.provider_name is not None
        assert entry.preview_image
    assert len(data.education) == 1
    assert data.education[0].grade == "CGPA: 8.4 / 10"
    assert len(data.languages) == 3
    assert len(data.certifications) == 4
    assert len(data.skills) == 20
    assert truncated == {"skills": TruncationInfo(returned=20, total=36)}
    assert UNVERIFIED_SECTIONS == (
        "volunteering",
        "honors",
        "publications",
        "patents",
        "courses",
        "organizations",
        "test_scores",
    )
    assert len(UNVERIFIED_SECTIONS) == 7
    assert data.volunteering == []
    assert data.honors == []
    assert data.publications == []
    assert data.patents == []
    assert data.courses == []
    assert data.organizations == []
    assert data.test_scores == []


def test_empty_elements_raises() -> None:
    with pytest.raises(ProfileNotFoundError):
        build_profile_data({"data": {"*elements": []}, "included": []})


def test_sparse_profile_does_not_raise() -> None:
    payload = {
        "data": {"*elements": ["urn:li:fsd_profile:sparse"]},
        "included": [
            {
                "entityUrn": "urn:li:fsd_profile:sparse",
                "$type": "com.linkedin.voyager.dash.identity.profile.Profile",
            }
        ],
    }
    data, truncated = build_profile_data(payload)
    assert data.profile.full_name is None
    assert data.experience == []
    assert data.skills == []
    assert truncated == {}

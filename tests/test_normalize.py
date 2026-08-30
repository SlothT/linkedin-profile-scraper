import pytest

from app.errors import ProfileNotFoundError
from app.linkedin.mapper import UNVERIFIED_SECTIONS
from app.linkedin.normalize import EntityGraph

_UNVERIFIED_COLLECTION_KEYS = (
    "*profileVolunteerExperiences",
    "*profileHonors",
    "*profilePublications",
    "*profilePatents",
    "*profileCourses",
    "*profileOrganizations",
    "*profileTestScores",
)


def test_sample_root_and_collections(sample_payload: dict) -> None:
    graph = EntityGraph(sample_payload)
    profile = graph.root_profile()
    assert profile["publicIdentifier"] == "alex-rivera-demo"
    assert len(graph.follow(profile, "*profileSkills")) == 20
    assert graph.collection_paging(profile, "*profileSkills") == (20, 26)
    assert len(graph.follow(profile, "*profileEducations")) == 1
    assert len(graph.follow(profile, "*profilePositionGroups")) == 3
    position_count = 0
    for group in graph.follow(profile, "*profilePositionGroups"):
        position_count += len(graph.follow(group, "*profilePositionInPositionGroup"))
    assert position_count == 5
    assert graph.resolve(None) is None
    assert graph.resolve("urn:li:nonexistent:1") is None
    assert graph.follow(profile, "*noSuchKey") == []
    assert len(graph.entities_of_type("profile.Position")) == 5


def test_root_profile_missing_elements() -> None:
    graph = EntityGraph({"data": {}, "included": []})
    with pytest.raises(ProfileNotFoundError):
        graph.root_profile()


def test_rich_root_paging_projects_and_stubs(rich_payload: dict) -> None:
    graph = EntityGraph(rich_payload)
    profile = graph.root_profile()
    assert profile["publicIdentifier"] == "taylor-quinn-demo"
    assert graph.collection_paging(profile, "*profileSkills") == (20, 36)
    assert len(graph.follow(profile, "*profileProjects")) == 2
    assert len(graph.follow(profile, "*profileTreasuryMediaProfile")) == 2
    assert len(UNVERIFIED_SECTIONS) == 7
    for star_key in _UNVERIFIED_COLLECTION_KEYS:
        assert graph.follow(profile, star_key) == []
        assert graph.collection_paging(profile, star_key) == (0, 0)
    educations = graph.follow(profile, "*profileEducations")
    degree = graph.resolve(educations[0].get("*degree"))
    assert degree is not None
    non_dollar_keys = [key for key in degree if not key.startswith("$")]
    assert non_dollar_keys == ["entityUrn"]

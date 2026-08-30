from app.linkedin.images import image_variants, picture_variants
from app.linkedin.normalize import EntityGraph


def test_sample_picture_background_and_logo(sample_payload: dict) -> None:
    graph = EntityGraph(sample_payload)
    profile = graph.root_profile()
    picture = picture_variants(profile["profilePicture"])
    assert [variant.width for variant in picture] == [800, 400, 200, 100]
    display = profile["profilePicture"]["displayImageReference"]["vectorImage"]
    root_url = display["rootUrl"]
    for variant in picture:
        assert variant.url is not None
        assert variant.url.startswith(root_url)
    background = picture_variants(profile["backgroundPicture"])
    assert len(background) == 2
    groups = graph.follow(profile, "*profilePositionGroups")
    positions = graph.follow(groups[0], "*profilePositionInPositionGroup")
    company = graph.resolve(positions[0]["*company"])
    logo = image_variants(company["logo"])
    assert len(logo) == 3


def test_rich_prefers_display_reference(rich_payload: dict) -> None:
    graph = EntityGraph(rich_payload)
    profile = graph.root_profile()
    assert "originalImageReference" not in profile["profilePicture"]
    assert "originalImageReference" not in profile["backgroundPicture"]
    assert picture_variants(profile["profilePicture"])
    assert picture_variants(profile["backgroundPicture"])
    media = graph.follow(profile, "*profileTreasuryMediaProfile")[0]
    preview = image_variants(media["previewImage"])
    assert preview


def test_image_variants_empty_inputs() -> None:
    assert image_variants(None) == []
    assert image_variants({"vectorImage": {"rootUrl": "x", "artifacts": []}}) == []
    assert image_variants({"attributes": []}) == []

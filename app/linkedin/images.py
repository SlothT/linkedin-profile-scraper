from app.schemas import ImageVariant


def _vector_image(image_reference: dict) -> dict | None:
    direct = image_reference.get("vectorImage")
    if isinstance(direct, dict):
        return direct
    attributes = image_reference.get("attributes")
    if not isinstance(attributes, list):
        return None
    for attribute in attributes:
        if not isinstance(attribute, dict):
            continue
        detail = attribute.get("detailDataUnion") or {}
        if not isinstance(detail, dict):
            continue
        nested = detail.get("vectorImage")
        if isinstance(nested, dict):
            return nested
    return None


def image_variants(image_reference: dict | None) -> list[ImageVariant]:
    """Expand a Voyager image reference into concrete URLs, largest first."""
    if not isinstance(image_reference, dict):
        return []
    vector = _vector_image(image_reference)
    if not isinstance(vector, dict):
        return []
    root_url = vector.get("rootUrl") or ""
    artifacts = vector.get("artifacts") or []
    if not artifacts:
        return []
    variants: list[ImageVariant] = []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        segment = artifact.get("fileIdentifyingUrlPathSegment") or ""
        variants.append(
            ImageVariant(
                width=artifact.get("width"),
                height=artifact.get("height"),
                url=f"{root_url}{segment}",
            )
        )
    variants.sort(key=lambda variant: variant.width or 0, reverse=True)
    return variants


def picture_variants(picture_node: dict | None) -> list[ImageVariant]:
    """Expand a profilePicture / backgroundPicture node, preferring the display reference."""
    if not isinstance(picture_node, dict):
        return []
    display = image_variants(picture_node.get("displayImageReference"))
    if display:
        return display
    return image_variants(picture_node.get("originalImageReference"))


def pick_image(image_reference: dict | None) -> str | None:
    variants = image_variants(image_reference)
    if not variants:
        return None
    return variants[0].url

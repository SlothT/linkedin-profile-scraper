from app.errors import ProfileNotFoundError


class EntityGraph:
    """Index of a Voyager normalized-JSON payload."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self._by_urn: dict[str, dict] = {}
        for entity in payload.get("included") or []:
            urn = entity.get("entityUrn")
            if isinstance(urn, str) and urn:
                self._by_urn[urn] = entity

    def resolve(self, urn: str | None) -> dict | None:
        if not urn:
            return None
        return self._by_urn.get(urn)

    def root_profile(self) -> dict:
        data = self._payload.get("data") or {}
        elements = data.get("*elements") or []
        if not elements:
            raise ProfileNotFoundError()
        profile = self.resolve(elements[0] if isinstance(elements[0], str) else None)
        type_name = str((profile or {}).get("$type") or "")
        if profile is None or "profile.Profile" not in type_name:
            raise ProfileNotFoundError()
        return profile

    def follow(self, owner: dict, star_key: str) -> list[dict]:
        reference = owner.get(star_key)
        if reference is None:
            return []
        if isinstance(reference, list):
            resolved: list[dict] = []
            for urn in reference:
                entity = self.resolve(urn if isinstance(urn, str) else None)
                if entity is not None:
                    resolved.append(entity)
            return resolved
        if not isinstance(reference, str):
            return []
        collection = self.resolve(reference)
        if collection is None:
            return []
        resolved_elements: list[dict] = []
        for urn in collection.get("*elements") or []:
            entity = self.resolve(urn if isinstance(urn, str) else None)
            if entity is not None:
                resolved_elements.append(entity)
        return resolved_elements

    def collection_paging(self, owner: dict, star_key: str) -> tuple[int, int | None]:
        returned_count = len(self.follow(owner, star_key))
        reference = owner.get(star_key)
        if not isinstance(reference, str):
            if isinstance(reference, list):
                return (returned_count, None)
            return (returned_count, None)
        collection = self.resolve(reference)
        if collection is None:
            return (returned_count, None)
        paging = collection.get("paging") or {}
        total = paging.get("total")
        return (returned_count, total if isinstance(total, int) else None)

    def entities_of_type(self, type_suffix: str) -> list[dict]:
        matches: list[dict] = []
        for entity in self._by_urn.values():
            type_name = str(entity.get("$type") or "")
            if type_name == type_suffix or type_name.endswith(type_suffix):
                matches.append(entity)
        return matches

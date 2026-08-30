from app.linkedin.images import image_variants, picture_variants
from app.linkedin.normalize import EntityGraph
from app.schemas import (
    Certification,
    Course,
    DatePart,
    DateRange,
    Education,
    Experience,
    FeaturedMedia,
    Honor,
    Language,
    Location,
    Organization,
    Patent,
    ProfileCore,
    ProfileData,
    Project,
    Publication,
    TestScore,
    TruncationInfo,
    VolunteerExperience,
)

UNVERIFIED_SECTIONS: tuple[str, ...] = (
    "volunteering",
    "honors",
    "publications",
    "patents",
    "courses",
    "organizations",
    "test_scores",
)

_COLLECTION_TRUNCATION: tuple[tuple[str, str], ...] = (
    ("*profileSkills", "skills"),
    ("*profileCertifications", "certifications"),
    ("*profileEducations", "educations"),
    ("*profileLanguages", "languages"),
    ("*profilePositionGroups", "positionGroups"),
    ("*profileProjects", "projects"),
    ("*profileTreasuryMediaProfile", "featuredMedia"),
    ("*profileVolunteerExperiences", "volunteering"),
    ("*profileHonors", "honors"),
    ("*profilePublications", "publications"),
    ("*profilePatents", "patents"),
    ("*profileCourses", "courses"),
    ("*profileOrganizations", "organizations"),
    ("*profileTestScores", "test_scores"),
)


def _first_key(entity: dict, *candidate_keys: str) -> object | None:
    """Return the first present, non-empty value among candidate_keys."""
    for key in candidate_keys:
        if key not in entity:
            continue
        value = entity[key]
        if value is None or value == "":
            continue
        return value
    return None


def _to_date_part(raw: object | None) -> DatePart | None:
    if not isinstance(raw, dict):
        return None
    month = raw.get("month")
    year = raw.get("year")
    if month is None and year is None:
        return None
    return DatePart(
        month=month if isinstance(month, int) else None,
        year=year if isinstance(year, int) else None,
    )


def _to_date_range(raw: dict | None) -> DateRange | None:
    if not isinstance(raw, dict):
        return None
    start = _to_date_part(raw.get("start"))
    end = _to_date_part(raw.get("end"))
    if start is None and end is None:
        return None
    return DateRange(start=start, end=end, is_current=start is not None and end is None)


def _date_from_candidates(entity: dict, *candidate_keys: str) -> DatePart | None:
    direct = _first_key(entity, *candidate_keys)
    part = _to_date_part(direct)
    if part is not None:
        return part
    date_range = _to_date_range(entity.get("dateRange") if isinstance(entity.get("dateRange"), dict) else None)
    if date_range is not None:
        return date_range.start
    return None


def _map_location(profile: dict, graph: EntityGraph) -> Location | None:
    geo_location = profile.get("geoLocation") if isinstance(profile.get("geoLocation"), dict) else {}
    geo = graph.resolve(geo_location.get("*geo") if isinstance(geo_location, dict) else None)
    location_node = profile.get("location") if isinstance(profile.get("location"), dict) else {}
    country_code = location_node.get("countryCode") if isinstance(location_node, dict) else None
    if not isinstance(geo, dict):
        if country_code:
            return Location(country_code=country_code)
        return None
    full = geo.get("defaultLocalizedName")
    city_region = geo.get("defaultLocalizedNameWithoutCountryName")
    country: str | None = None
    if geo.get("*country"):
        country_entity = graph.resolve(geo.get("*country"))
        if country_entity:
            country_name = country_entity.get("defaultLocalizedName")
            country = country_name if isinstance(country_name, str) else None
    elif full is not None and full == city_region:
        country = full if isinstance(full, str) else None
    return Location(
        full=full if isinstance(full, str) else None,
        city_region=city_region if isinstance(city_region, str) else None,
        country=country,
        country_code=country_code if isinstance(country_code, str) else None,
    )


def _map_profile_core(profile: dict, graph: EntityGraph) -> ProfileCore:
    first_name = profile.get("firstName")
    last_name = profile.get("lastName")
    first = first_name if isinstance(first_name, str) else ""
    last = last_name if isinstance(last_name, str) else ""
    full_name = f"{first} {last}".strip() or None
    industry_entity = graph.resolve(profile.get("*industry") if isinstance(profile.get("*industry"), str) else None)
    industry_name = industry_entity.get("name") if industry_entity else None
    return ProfileCore(
        public_identifier=profile.get("publicIdentifier"),
        profile_urn=profile.get("entityUrn"),
        member_urn=profile.get("objectUrn"),
        first_name=first_name if isinstance(first_name, str) else None,
        last_name=last_name if isinstance(last_name, str) else None,
        full_name=full_name,
        headline=profile.get("headline") if isinstance(profile.get("headline"), str) else None,
        about=profile.get("summary") if isinstance(profile.get("summary"), str) else None,
        location=_map_location(profile, graph),
        industry=industry_name if isinstance(industry_name, str) else None,
        is_premium=profile.get("premium") if isinstance(profile.get("premium"), bool) else None,
        is_influencer=profile.get("influencer") if isinstance(profile.get("influencer"), bool) else None,
        is_creator=profile.get("creator") if isinstance(profile.get("creator"), bool) else None,
        profile_picture=picture_variants(profile.get("profilePicture") if isinstance(profile.get("profilePicture"), dict) else None),
        background_image=picture_variants(
            profile.get("backgroundPicture") if isinstance(profile.get("backgroundPicture"), dict) else None
        ),
    )


def _company_fields(position: dict, graph: EntityGraph) -> tuple[str | None, list]:
    company = graph.resolve(position.get("*company") if isinstance(position.get("*company"), str) else None)
    if not company:
        return None, []
    url = company.get("url") if isinstance(company.get("url"), str) else None
    logo = image_variants(company.get("logo") if isinstance(company.get("logo"), dict) else None)
    return url, logo


def _map_experience(profile: dict, graph: EntityGraph) -> list[Experience]:
    mapped: list[Experience] = []
    groups = graph.follow(profile, "*profilePositionGroups")
    positions_with_groups: list[tuple[dict, dict | None]] = []
    for group in groups:
        for position in graph.follow(group, "*profilePositionInPositionGroup"):
            positions_with_groups.append((position, group))
    if not positions_with_groups:
        for position in graph.entities_of_type("profile.Position"):
            positions_with_groups.append((position, None))
    for position, group in positions_with_groups:
        company_url, company_logo = _company_fields(position, graph)
        company_name = position.get("companyName")
        if not company_name and group is not None:
            company_name = group.get("companyName")
        employment_entity = graph.resolve(
            position.get("*employmentType") if isinstance(position.get("*employmentType"), str) else None
        )
        employment_type = employment_entity.get("name") if employment_entity else None
        location = position.get("locationName")
        if not location:
            location = position.get("geoLocationName")
        mapped.append(
            Experience(
                title=position.get("title") if isinstance(position.get("title"), str) else None,
                company_name=company_name if isinstance(company_name, str) else None,
                company_urn=position.get("companyUrn") if isinstance(position.get("companyUrn"), str) else None,
                company_url=company_url,
                company_logo=company_logo,
                employment_type=employment_type if isinstance(employment_type, str) else None,
                location=location if isinstance(location, str) else None,
                description=position.get("description") if isinstance(position.get("description"), str) else None,
                date_range=_to_date_range(position.get("dateRange") if isinstance(position.get("dateRange"), dict) else None),
            )
        )
    return mapped


def _map_education(profile: dict, graph: EntityGraph) -> list[Education]:
    mapped: list[Education] = []
    for education in graph.follow(profile, "*profileEducations"):
        school = graph.resolve(education.get("*school") if isinstance(education.get("*school"), str) else None)
        field = education.get("fieldOfStudy")
        field_of_study = field.strip() if isinstance(field, str) else None
        mapped.append(
            Education(
                school_name=education.get("schoolName") if isinstance(education.get("schoolName"), str) else None,
                school_url=school.get("url") if school and isinstance(school.get("url"), str) else None,
                school_logo=image_variants(school.get("logo") if school and isinstance(school.get("logo"), dict) else None),
                degree=education.get("degreeName") if isinstance(education.get("degreeName"), str) else None,
                field_of_study=field_of_study,
                grade=education.get("grade") if isinstance(education.get("grade"), str) else None,
                activities=education.get("activities") if isinstance(education.get("activities"), str) else None,
                description=education.get("description") if isinstance(education.get("description"), str) else None,
                date_range=_to_date_range(education.get("dateRange") if isinstance(education.get("dateRange"), dict) else None),
            )
        )
    return mapped


def _map_featured_media(profile: dict, graph: EntityGraph) -> list[FeaturedMedia]:
    mapped: list[FeaturedMedia] = []
    for media in graph.follow(profile, "*profileTreasuryMediaProfile"):
        data = media.get("data") if isinstance(media.get("data"), dict) else {}
        media_type: str | None = None
        url: str | None = None
        if "Url" in data:
            media_type = "link"
            url_value = data.get("Url")
            url = url_value if isinstance(url_value, str) else None
        elif "NativeDocument" in data:
            media_type = "document"
            native = data.get("NativeDocument") if isinstance(data.get("NativeDocument"), dict) else {}
            url = native.get("transcribedDocumentUrl") or native.get("manifestUrl")
            url = url if isinstance(url, str) else None
        elif "NativeVideo" in data or any("Video" in str(key) for key in data):
            media_type = "video"
        elif "VectorImage" in data or any("Image" in str(key) for key in data):
            media_type = "image"
        mapped.append(
            FeaturedMedia(
                title=media.get("title") if isinstance(media.get("title"), str) else None,
                description=media.get("description") if isinstance(media.get("description"), str) else None,
                media_type=media_type,
                url=url,
                provider_name=media.get("providerName") if isinstance(media.get("providerName"), str) else None,
                preview_image=image_variants(media.get("previewImage") if isinstance(media.get("previewImage"), dict) else None),
            )
        )
    return mapped


def _map_volunteering(profile: dict, graph: EntityGraph) -> list[VolunteerExperience]:
    mapped: list[VolunteerExperience] = []
    for entity in graph.follow(profile, "*profileVolunteerExperiences"):
        mapped.append(
            VolunteerExperience(
                role=_as_str(_first_key(entity, "role", "title")),
                organization_name=_as_str(_first_key(entity, "companyName", "organizationName", "name")),
                cause=_as_str(_first_key(entity, "cause", "causeName")),
                description=_as_str(entity.get("description")),
                date_range=_to_date_range(entity.get("dateRange") if isinstance(entity.get("dateRange"), dict) else None),
            )
        )
    return mapped


def _as_str(value: object | None) -> str | None:
    if isinstance(value, str):
        return value
    return None


def _map_honors(profile: dict, graph: EntityGraph) -> list[Honor]:
    mapped: list[Honor] = []
    for entity in graph.follow(profile, "*profileHonors"):
        mapped.append(
            Honor(
                title=_as_str(_first_key(entity, "title", "name")),
                issuer=_as_str(_first_key(entity, "issuer", "issuerName")),
                description=_as_str(entity.get("description")),
                issued_on=_date_from_candidates(entity, "issuedOn", "issueDate"),
            )
        )
    return mapped


def _map_publications(profile: dict, graph: EntityGraph) -> list[Publication]:
    mapped: list[Publication] = []
    for entity in graph.follow(profile, "*profilePublications"):
        mapped.append(
            Publication(
                name=_as_str(_first_key(entity, "name", "title")),
                publisher=_as_str(_first_key(entity, "publisher", "publisherName")),
                description=_as_str(entity.get("description")),
                url=_as_str(entity.get("url")),
                published_on=_date_from_candidates(entity, "publishedOn", "date"),
            )
        )
    return mapped


def _map_patents(profile: dict, graph: EntityGraph) -> list[Patent]:
    mapped: list[Patent] = []
    for entity in graph.follow(profile, "*profilePatents"):
        mapped.append(
            Patent(
                title=_as_str(_first_key(entity, "title", "name")),
                number=_as_str(_first_key(entity, "number", "applicationNumber", "patentNumber")),
                description=_as_str(entity.get("description")),
                url=_as_str(entity.get("url")),
                issued_on=_date_from_candidates(entity, "issuedOn", "issueDate"),
            )
        )
    return mapped


def _map_courses(profile: dict, graph: EntityGraph) -> list[Course]:
    mapped: list[Course] = []
    for entity in graph.follow(profile, "*profileCourses"):
        mapped.append(
            Course(
                name=_as_str(_first_key(entity, "name", "title")),
                number=_as_str(_first_key(entity, "number", "courseNumber")),
            )
        )
    return mapped


def _map_organizations(profile: dict, graph: EntityGraph) -> list[Organization]:
    mapped: list[Organization] = []
    for entity in graph.follow(profile, "*profileOrganizations"):
        mapped.append(
            Organization(
                name=_as_str(_first_key(entity, "name", "organizationName")),
                position=_as_str(_first_key(entity, "position", "role", "title")),
                description=_as_str(entity.get("description")),
                date_range=_to_date_range(entity.get("dateRange") if isinstance(entity.get("dateRange"), dict) else None),
            )
        )
    return mapped


def _map_test_scores(profile: dict, graph: EntityGraph) -> list[TestScore]:
    mapped: list[TestScore] = []
    for entity in graph.follow(profile, "*profileTestScores"):
        score = _first_key(entity, "score")
        if isinstance(score, (int, float)):
            score_text: str | None = str(score)
        else:
            score_text = _as_str(score)
        mapped.append(
            TestScore(
                name=_as_str(_first_key(entity, "name", "title")),
                score=score_text,
                description=_as_str(entity.get("description")),
                taken_on=_date_from_candidates(entity, "date", "takenOn"),
            )
        )
    return mapped


def _truncation_report(profile: dict, graph: EntityGraph) -> dict[str, TruncationInfo]:
    report: dict[str, TruncationInfo] = {}
    for star_key, name in _COLLECTION_TRUNCATION:
        returned, total = graph.collection_paging(profile, star_key)
        if total is not None and total > returned:
            report[name] = TruncationInfo(returned=returned, total=total)
    return report


def build_profile_data(payload: dict) -> tuple[ProfileData, dict[str, TruncationInfo]]:
    """Map a raw Voyager payload to the response schema. Returns data plus truncation report."""
    graph = EntityGraph(payload)
    profile = graph.root_profile()
    data = ProfileData(
        profile=_map_profile_core(profile, graph),
        experience=_map_experience(profile, graph),
        education=_map_education(profile, graph),
        skills=[skill["name"] for skill in graph.follow(profile, "*profileSkills") if isinstance(skill.get("name"), str)],
        certifications=[
            Certification(
                name=entity.get("name") if isinstance(entity.get("name"), str) else None,
                authority=entity.get("authority") if isinstance(entity.get("authority"), str) else None,
                license_number=entity.get("licenseNumber") if isinstance(entity.get("licenseNumber"), str) else None,
                url=entity.get("url") if isinstance(entity.get("url"), str) else None,
                display_source=entity.get("displaySource") if isinstance(entity.get("displaySource"), str) else None,
                issued_on=_to_date_part((entity.get("dateRange") or {}).get("start") if isinstance(entity.get("dateRange"), dict) else None),
            )
            for entity in graph.follow(profile, "*profileCertifications")
        ],
        languages=[
            Language(
                name=entity.get("name") if isinstance(entity.get("name"), str) else None,
                proficiency=entity.get("proficiency") if isinstance(entity.get("proficiency"), str) else None,
            )
            for entity in graph.follow(profile, "*profileLanguages")
        ],
        projects=[
            Project(
                title=entity.get("title") if isinstance(entity.get("title"), str) else None,
                description=entity.get("description") if isinstance(entity.get("description"), str) else None,
                url=entity.get("url") if isinstance(entity.get("url"), str) else None,
                date_range=_to_date_range(entity.get("dateRange") if isinstance(entity.get("dateRange"), dict) else None),
            )
            for entity in graph.follow(profile, "*profileProjects")
        ],
        featured_media=_map_featured_media(profile, graph),
        volunteering=_map_volunteering(profile, graph),
        honors=_map_honors(profile, graph),
        publications=_map_publications(profile, graph),
        patents=_map_patents(profile, graph),
        courses=_map_courses(profile, graph),
        organizations=_map_organizations(profile, graph),
        test_scores=_map_test_scores(profile, graph),
    )
    return data, _truncation_report(profile, graph)

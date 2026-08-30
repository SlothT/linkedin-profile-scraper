from pydantic import BaseModel, Field


class ImageVariant(BaseModel):
    width: int | None = None
    height: int | None = None
    url: str | None = None


class DatePart(BaseModel):
    month: int | None = None
    year: int | None = None


class DateRange(BaseModel):
    start: DatePart | None = None
    end: DatePart | None = None
    is_current: bool = False


class Location(BaseModel):
    full: str | None = None
    city_region: str | None = None
    country: str | None = None
    country_code: str | None = None


class ProfileCore(BaseModel):
    public_identifier: str | None = None
    profile_urn: str | None = None
    member_urn: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None
    headline: str | None = None
    about: str | None = None
    location: Location | None = None
    industry: str | None = None
    is_premium: bool | None = None
    is_influencer: bool | None = None
    is_creator: bool | None = None
    profile_picture: list[ImageVariant] = Field(default_factory=list)
    background_image: list[ImageVariant] = Field(default_factory=list)


class Experience(BaseModel):
    title: str | None = None
    company_name: str | None = None
    company_urn: str | None = None
    company_url: str | None = None
    company_logo: list[ImageVariant] = Field(default_factory=list)
    employment_type: str | None = None
    location: str | None = None
    description: str | None = None
    date_range: DateRange | None = None


class Education(BaseModel):
    school_name: str | None = None
    school_url: str | None = None
    school_logo: list[ImageVariant] = Field(default_factory=list)
    degree: str | None = None
    field_of_study: str | None = None
    grade: str | None = None
    activities: str | None = None
    description: str | None = None
    date_range: DateRange | None = None


class Certification(BaseModel):
    name: str | None = None
    authority: str | None = None
    license_number: str | None = None
    url: str | None = None
    display_source: str | None = None
    issued_on: DatePart | None = None


class Language(BaseModel):
    name: str | None = None
    proficiency: str | None = None


class Project(BaseModel):
    title: str | None = None
    description: str | None = None
    url: str | None = None
    date_range: DateRange | None = None


class FeaturedMedia(BaseModel):
    """The profile's "Featured" section. Voyager calls these TreasuryMedia."""

    title: str | None = None
    description: str | None = None
    media_type: str | None = None
    url: str | None = None
    provider_name: str | None = None
    preview_image: list[ImageVariant] = Field(default_factory=list)


class VolunteerExperience(BaseModel):
    role: str | None = None
    organization_name: str | None = None
    cause: str | None = None
    description: str | None = None
    date_range: DateRange | None = None


class Honor(BaseModel):
    title: str | None = None
    issuer: str | None = None
    description: str | None = None
    issued_on: DatePart | None = None


class Publication(BaseModel):
    name: str | None = None
    publisher: str | None = None
    description: str | None = None
    url: str | None = None
    published_on: DatePart | None = None


class Patent(BaseModel):
    title: str | None = None
    number: str | None = None
    description: str | None = None
    url: str | None = None
    issued_on: DatePart | None = None


class Course(BaseModel):
    name: str | None = None
    number: str | None = None


class Organization(BaseModel):
    name: str | None = None
    position: str | None = None
    description: str | None = None
    date_range: DateRange | None = None


class TestScore(BaseModel):
    name: str | None = None
    score: str | None = None
    description: str | None = None
    taken_on: DatePart | None = None


class TruncationInfo(BaseModel):
    returned: int
    total: int


class ResponseMeta(BaseModel):
    fetched_at: str
    duration_ms: int
    decoration_id: str
    source: str = "live"
    cached: bool = False
    stale: bool = False
    stale_reason: str | None = None
    truncated: dict[str, TruncationInfo] = Field(default_factory=dict)
    unverified_sections: list[str] = Field(default_factory=list)


class ProfileData(BaseModel):
    profile: ProfileCore
    experience: list[Experience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    languages: list[Language] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    featured_media: list[FeaturedMedia] = Field(default_factory=list)
    volunteering: list[VolunteerExperience] = Field(default_factory=list)
    honors: list[Honor] = Field(default_factory=list)
    publications: list[Publication] = Field(default_factory=list)
    patents: list[Patent] = Field(default_factory=list)
    courses: list[Course] = Field(default_factory=list)
    organizations: list[Organization] = Field(default_factory=list)
    test_scores: list[TestScore] = Field(default_factory=list)


class ProfileResponse(BaseModel):
    success: bool = True
    data: ProfileData
    meta: ResponseMeta


class ProfileRequest(BaseModel):
    url: str
    li_at: str | None = None

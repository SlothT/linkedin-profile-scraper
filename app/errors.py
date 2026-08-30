class LinkedInAPIError(Exception):
    status_code: int = 500

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class InvalidProfileURLError(LinkedInAPIError):
    status_code = 400

    def __init__(self, message: str = "URL is not a LinkedIn person profile URL") -> None:
        super().__init__(message)


class MissingCredentialsError(LinkedInAPIError):
    status_code = 401

    def __init__(self, message: str = "No session cookie provided and no server fallback is configured") -> None:
        super().__init__(message)


class SessionRevokedError(LinkedInAPIError):
    status_code = 401

    def __init__(self, message: str = "LinkedIn session was revoked") -> None:
        super().__init__(message)


class SessionRejectedError(LinkedInAPIError):
    status_code = 403

    def __init__(self, message: str = "LinkedIn rejected the session") -> None:
        super().__init__(message)


class ProfileNotFoundError(LinkedInAPIError):
    status_code = 404

    def __init__(self, message: str = "Profile not found") -> None:
        super().__init__(message)


class RateLimitedError(LinkedInAPIError):
    status_code = 429

    def __init__(self, message: str = "Rate limited") -> None:
        super().__init__(message)


class UpstreamShapeError(LinkedInAPIError):
    status_code = 502

    def __init__(self, message: str = "LinkedIn returned a response that could not be parsed") -> None:
        super().__init__(message)


class UpstreamUnavailableError(LinkedInAPIError):
    status_code = 503

    def __init__(self, message: str = "Could not reach LinkedIn") -> None:
        super().__init__(message)

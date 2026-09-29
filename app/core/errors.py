"""Domain exceptions. Raised in services, mapped to HTTP in one place (main.py)."""


class DomainError(Exception):
    code: str = "domain_error"
    message: str = "Domain error"
    http_status: int = 400

    def __init__(self, message: str | None = None, code: str | None = None) -> None:
        if message:
            self.message = message
        if code:
            self.code = code
        super().__init__(self.message)


class NotFoundError(DomainError):
    code = "not_found"
    http_status = 404

    def __init__(self, message: str = "Resource not found") -> None:
        super().__init__(message)


class ConflictError(DomainError):
    code = "conflict"
    http_status = 409

    def __init__(self, message: str = "Conflict") -> None:
        super().__init__(message)


class UnprocessableError(DomainError):
    code = "unprocessable"
    http_status = 422

    def __init__(self, message: str = "Unprocessable entity") -> None:
        super().__init__(message)


class UnauthorizedError(DomainError):
    code = "unauthorized"
    http_status = 401

    def __init__(self, message: str = "Not authenticated") -> None:
        super().__init__(message)


class ForbiddenError(DomainError):
    code = "forbidden"
    http_status = 403

    def __init__(self, message: str = "Forbidden") -> None:
        super().__init__(message)


class BookingTransitionError(DomainError):
    """Illegal booking state transition."""

    code = "illegal_booking_transition"
    http_status = 409

    def __init__(self, message: str = "Illegal booking state transition") -> None:
        super().__init__(message)


class WebhookSignatureError(DomainError):
    code = "invalid_signature"
    http_status = 401

    def __init__(self, message: str = "Invalid webhook signature") -> None:
        super().__init__(message)

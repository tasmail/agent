"""Endpoint selection for S3-compatible backup storage."""

from urllib.parse import urlsplit


def endpoint_options(auth: dict) -> dict:
    """Preserve AWS defaults and reject unsafe custom credential destinations."""
    endpoint = auth.get("ENDPOINT_URL")
    if endpoint is None or endpoint == "":
        return {}
    try:
        parsed = urlsplit(endpoint)
        valid = (
            isinstance(endpoint, str)
            and parsed.scheme == "https"
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and parsed.path in ("", "/")
            and not parsed.query
            and not parsed.fragment
            and parsed.port in (None, 443)
            and not any(character.isspace() for character in endpoint)
        )
    except (ValueError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise ValueError("Invalid backup endpoint: expected a credential-free HTTPS origin")
    if not auth.get("ACCESS_KEY") or not auth.get("SECRET_KEY"):
        raise ValueError("Custom backup endpoint requires explicit credentials")
    return {"endpoint_url": endpoint}


def streaming_endpoint(auth: dict, providers: dict) -> tuple:
    """Custom origins must not inherit AWS-specific rclone behavior."""
    options = endpoint_options(auth)
    if options:
        return "Other", options["endpoint_url"]
    return providers[auth["PROVIDER"]]

"""Outbound URL policy for user-configured job discovery endpoints."""

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeOutboundUrl(ValueError):
    """Raised when a connector target is not a public HTTPS endpoint."""


def _is_public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def validate_public_https_url(value: str, *, allow_http_localhost: bool = False) -> str:
    """Validate a connector URL before any HTTP or browser navigation.

    User-controlled discovery targets must be public HTTPS URLs.  DNS is
    resolved before navigation so private, loopback, link-local, and metadata
    addresses cannot be reached through a hostname or redirect target.
    """
    if not isinstance(value, str) or not value.strip():
        raise UnsafeOutboundUrl("A non-empty URL is required")

    parsed = urlparse(value.strip())
    hostname = (parsed.hostname or "").rstrip(".").lower()
    scheme = parsed.scheme.lower()
    if scheme != "https" and not (
        allow_http_localhost and scheme == "http" and hostname in {"localhost", "127.0.0.1"}
    ):
        raise UnsafeOutboundUrl("Only public HTTPS connector URLs are allowed")
    if not hostname or parsed.username or parsed.password:
        raise UnsafeOutboundUrl("Connector URLs must contain only a hostname and path")
    if parsed.port not in (None, 443) and not (allow_http_localhost and parsed.port in (80, 8000)):
        raise UnsafeOutboundUrl("Non-standard connector ports are not allowed")
    if hostname in {"localhost", "metadata.google.internal", "metadata"}:
        raise UnsafeOutboundUrl("Local and cloud metadata hosts are not allowed")

    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise UnsafeOutboundUrl("Connector hostname could not be resolved") from exc
    if not addresses or any(not _is_public_ip(address) for address in addresses):
        raise UnsafeOutboundUrl("Connector hostname resolves to a non-public address")
    return parsed.geturl()

import socket

import pytest

from app.security.url_policy import UnsafeOutboundUrl, validate_public_https_url


def _public_dns(*args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]


def _private_dns(*args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 443))]


def test_allows_public_https(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)
    assert validate_public_https_url("https://careers.example.com/jobs") == "https://careers.example.com/jobs"


@pytest.mark.parametrize("url", [
    "http://careers.example.com/jobs",
    "https://localhost/jobs",
    "https://careers.example.com:8443/jobs",
    "https://user:password@careers.example.com/jobs",
])
def test_rejects_unsafe_url_shape(url, monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)
    with pytest.raises(UnsafeOutboundUrl):
        validate_public_https_url(url)


def test_rejects_private_dns_result(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _private_dns)
    with pytest.raises(UnsafeOutboundUrl):
        validate_public_https_url("https://careers.example.com/jobs")

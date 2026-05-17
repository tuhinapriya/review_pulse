import httpx
import pytest
from fastapi import HTTPException

from app.api.routes.authors import (
    _supabase_admin_enabled,
    _supabase_auth_url,
    _supabase_error_detail,
)
from app.config import settings


def test_supabase_auth_url_rejects_missing_config(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", "")
    monkeypatch.setattr(settings, "supabase_anon_key", "")

    with pytest.raises(HTTPException) as exc_info:
        _supabase_auth_url("/auth/v1/signup")

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == (
        "Authentication service is not configured. Please contact support."
    )


def test_supabase_auth_url_rejects_placeholder_config(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", "https://<project-ref>.supabase.co")
    monkeypatch.setattr(settings, "supabase_anon_key", "<anon-key>")

    with pytest.raises(HTTPException) as exc_info:
        _supabase_auth_url("/auth/v1/signup")

    assert exc_info.value.status_code == 503


def test_supabase_auth_url_builds_auth_endpoint(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co/")
    monkeypatch.setattr(settings, "supabase_anon_key", "anon-key")
    monkeypatch.setattr(settings, "supabase_jwt_secret", "jwt-secret")
    monkeypatch.setattr(settings, "use_supabase_admin_signup", False)

    assert (
        _supabase_auth_url("/auth/v1/token?grant_type=password")
        == "https://example.supabase.co/auth/v1/token?grant_type=password"
    )


def test_supabase_error_detail_reads_known_fields():
    response = httpx.Response(400, json={"message": "Email already registered"})

    assert (
        _supabase_error_detail(response, "Registration failed")
        == "Email already registered"
    )


def test_supabase_admin_enabled_requires_setting_and_service_key(monkeypatch):
    monkeypatch.setattr(settings, "use_supabase_admin_signup", True)
    monkeypatch.setattr(settings, "supabase_service_key", "service-role-key")

    assert _supabase_admin_enabled() is True

    monkeypatch.setattr(settings, "supabase_service_key", "<service-role-key>")

    assert _supabase_admin_enabled() is False


def test_supabase_admin_enabled_rejects_placeholder_service_key(monkeypatch):
    monkeypatch.setattr(settings, "use_supabase_admin_signup", True)
    monkeypatch.setattr(settings, "supabase_service_key", "placeholder")

    assert _supabase_admin_enabled() is False

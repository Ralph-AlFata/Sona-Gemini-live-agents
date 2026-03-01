"""
Google Cloud credential loading for the drawing service.

Credential resolution order:
1) GOOGLE_SERVICE_ACCOUNT_JSON (JSON string)
2) GOOGLE_SERVICE_ACCOUNT_FILE (path to JSON file)
3) GOOGLE_APPLICATION_CREDENTIALS (path to JSON file)
4) ADC default chain (local gcloud ADC / Cloud Run metadata)

Optional:
- GOOGLE_IMPERSONATE_SERVICE_ACCOUNT to impersonate a target service account
- GOOGLE_QUOTA_PROJECT to charge quota/billing to a specific project
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import google.auth
from google.auth import impersonated_credentials
from google.auth.credentials import Credentials

CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


@dataclass(frozen=True)
class AuthConfig:
    """Resolved auth configuration for Google client creation."""

    credentials: Credentials | None
    source: str


def load_auth_config() -> AuthConfig:
    """
    Resolve credentials for Google clients.

    Accepts both service-account and authorized-user ADC JSON formats when
    loading from file or JSON payload.
    """
    quota_project_id = os.environ.get("GOOGLE_QUOTA_PROJECT")
    impersonate_target = os.environ.get("GOOGLE_IMPERSONATE_SERVICE_ACCOUNT")
    raw_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if raw_json:
        info = json.loads(raw_json)
        creds, _ = google.auth.load_credentials_from_dict(
            info,
            quota_project_id=quota_project_id,
            scopes=[CLOUD_PLATFORM_SCOPE],
        )
        source = "GOOGLE_SERVICE_ACCOUNT_JSON"
        return _maybe_impersonate(creds, source, impersonate_target)

    file_path = (
        os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
        or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    )
    if file_path:
        creds, _ = google.auth.load_credentials_from_file(
            file_path,
            quota_project_id=quota_project_id,
            scopes=[CLOUD_PLATFORM_SCOPE],
        )
        source_name = (
            "GOOGLE_SERVICE_ACCOUNT_FILE"
            if os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
            else "GOOGLE_APPLICATION_CREDENTIALS"
        )
        return _maybe_impersonate(creds, source_name, impersonate_target)

    creds, _ = google.auth.default(
        quota_project_id=quota_project_id,
        scopes=[CLOUD_PLATFORM_SCOPE],
    )
    return _maybe_impersonate(creds, "adc-default", impersonate_target)


def _maybe_impersonate(
    source_credentials: Credentials,
    source_name: str,
    target_service_account: str | None,
) -> AuthConfig:
    """Optionally impersonate a service account for keyless multi-project auth."""
    if not target_service_account:
        return AuthConfig(credentials=source_credentials, source=source_name)

    impersonated = impersonated_credentials.Credentials(
        source_credentials=source_credentials,
        target_principal=target_service_account,
        target_scopes=[CLOUD_PLATFORM_SCOPE],
        lifetime=3600,
    )
    return AuthConfig(
        credentials=impersonated,
        source=f"{source_name}+impersonation",
    )

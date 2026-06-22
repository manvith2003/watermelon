"""
Base tool class and GitHub API client wrapper.
"""
import os
import time
import httpx
from typing import Any, Optional


GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_API_BASE = "https://api.github.com"


class GitHubClient:
    """Thin wrapper around httpx for GitHub REST API calls with rate-limit awareness."""

    def __init__(self, token: str = GITHUB_TOKEN):
        self.token = token
        self.api_calls = 0
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _request(self, method: str, path: str, **kwargs) -> dict:
        self.api_calls += 1
        url = f"{GITHUB_API_BASE}{path}"
        resp = httpx.request(method, url, headers=self.headers, timeout=30, **kwargs)

        # Rate limit check
        remaining = int(resp.headers.get("X-RateLimit-Remaining", 999))
        if remaining < 5:
            reset_at = int(resp.headers.get("X-RateLimit-Reset", time.time() + 60))
            wait = max(1, reset_at - int(time.time()))
            raise RateLimitError(f"GitHub rate limit almost exhausted. Resets in {wait}s.")

        if resp.status_code == 404:
            raise NotFoundError(f"GitHub 404: {path}")
        if resp.status_code == 403:
            raise PermissionError(f"GitHub 403: {path} — check token scopes")
        if resp.status_code == 422:
            raise ValidationError(f"GitHub 422: {resp.json()}")
        if resp.status_code >= 400:
            raise GitHubAPIError(f"GitHub {resp.status_code}: {path} — {resp.text[:200]}")

        if resp.status_code == 204:
            return {}
        return resp.json()

    def get(self, path: str, params: Optional[dict] = None) -> Any:
        return self._request("GET", path, params=params)

    def post(self, path: str, json: Optional[dict] = None) -> Any:
        return self._request("POST", path, json=json)

    def patch(self, path: str, json: Optional[dict] = None) -> Any:
        return self._request("PATCH", path, json=json)

    def delete(self, path: str) -> Any:
        return self._request("DELETE", path)

    def reset_call_count(self):
        self.api_calls = 0


class ToolResult:
    """Standardised tool output."""
    def __init__(self, success: bool, data: Any, error: Optional[str] = None, api_calls: int = 0):
        self.success = success
        self.data = data
        self.error = error
        self.api_calls = api_calls

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "api_calls": self.api_calls,
        }


class GitHubAPIError(Exception): pass
class RateLimitError(GitHubAPIError): pass
class NotFoundError(GitHubAPIError): pass
class ValidationError(GitHubAPIError): pass

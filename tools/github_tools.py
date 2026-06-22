"""
Base GitHub tools — the primitive capability layer.

These are NOT hard-coded for every possible operation. They cover common
operations, leaving room for capability synthesis when the agent encounters
novel tasks (e.g., bulk operations, cross-repo analytics, project board mgmt).

Each tool function takes a GitHubClient and keyword params, returning a ToolResult.
"""
import time
from typing import Any, Optional
from tools.base import GitHubClient, ToolResult


# ─── Issues ──────────────────────────────────────────────────────────────────

def list_issues(client: GitHubClient, repo: str, state: str = "open",
                assignee: Optional[str] = None, labels: Optional[str] = None,
                milestone: Optional[str] = None, limit: int = 30) -> ToolResult:
    """List issues in a repository. repo = 'owner/repo'"""
    calls_before = client.api_calls
    params = {"state": state, "per_page": min(limit, 100)}
    if assignee:
        params["assignee"] = assignee
    if labels:
        params["labels"] = labels
    if milestone:
        params["milestone"] = milestone

    owner, name = repo.split("/", 1)
    data = client.get(f"/repos/{owner}/{name}/issues", params=params)
    # Filter out PRs (GitHub issues endpoint returns PRs too)
    issues = [i for i in data if "pull_request" not in i]
    return ToolResult(True, issues[:limit], api_calls=client.api_calls - calls_before)


def get_issue(client: GitHubClient, repo: str, issue_number: int) -> ToolResult:
    """Get a single issue by number."""
    calls_before = client.api_calls
    owner, name = repo.split("/", 1)
    data = client.get(f"/repos/{owner}/{name}/issues/{issue_number}")
    return ToolResult(True, data, api_calls=client.api_calls - calls_before)


def create_issue(client: GitHubClient, repo: str, title: str, body: str = "",
                 labels: Optional[list] = None, assignees: Optional[list] = None,
                 milestone: Optional[int] = None) -> ToolResult:
    """Create a new issue."""
    calls_before = client.api_calls
    owner, name = repo.split("/", 1)
    payload: dict[str, Any] = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels
    if assignees:
        payload["assignees"] = assignees
    if milestone:
        payload["milestone"] = milestone
    data = client.post(f"/repos/{owner}/{name}/issues", json=payload)
    return ToolResult(True, {"number": data["number"], "url": data["html_url"], "title": data["title"]},
                      api_calls=client.api_calls - calls_before)


def update_issue(client: GitHubClient, repo: str, issue_number: int,
                 title: Optional[str] = None, body: Optional[str] = None,
                 state: Optional[str] = None, labels: Optional[list] = None,
                 assignees: Optional[list] = None, milestone: Optional[int] = None) -> ToolResult:
    """Update an existing issue."""
    calls_before = client.api_calls
    owner, name = repo.split("/", 1)
    payload = {}
    if title is not None:
        payload["title"] = title
    if body is not None:
        payload["body"] = body
    if state is not None:
        payload["state"] = state
    if labels is not None:
        payload["labels"] = labels
    if assignees is not None:
        payload["assignees"] = assignees
    if milestone is not None:
        payload["milestone"] = milestone
    data = client.patch(f"/repos/{owner}/{name}/issues/{issue_number}", json=payload)
    return ToolResult(True, {"number": data["number"], "state": data["state"], "url": data["html_url"]},
                      api_calls=client.api_calls - calls_before)


def add_issue_comment(client: GitHubClient, repo: str, issue_number: int, body: str) -> ToolResult:
    """Add a comment to an issue or PR."""
    calls_before = client.api_calls
    owner, name = repo.split("/", 1)
    data = client.post(f"/repos/{owner}/{name}/issues/{issue_number}/comments", json={"body": body})
    return ToolResult(True, {"id": data["id"], "url": data["html_url"]},
                      api_calls=client.api_calls - calls_before)


def search_issues(client: GitHubClient, query: str, limit: int = 20) -> ToolResult:
    """Search issues/PRs across GitHub. query uses GitHub search syntax."""
    calls_before = client.api_calls
    data = client.get("/search/issues", params={"q": query, "per_page": min(limit, 100)})
    return ToolResult(True, {
        "total_count": data["total_count"],
        "items": data["items"][:limit],
    }, api_calls=client.api_calls - calls_before)


# ─── Labels ──────────────────────────────────────────────────────────────────

def list_labels(client: GitHubClient, repo: str) -> ToolResult:
    calls_before = client.api_calls
    owner, name = repo.split("/", 1)
    data = client.get(f"/repos/{owner}/{name}/labels", params={"per_page": 100})
    return ToolResult(True, data, api_calls=client.api_calls - calls_before)


def create_label(client: GitHubClient, repo: str, label_name: str,
                 color: str = "ededed", description: str = "") -> ToolResult:
    """Create a label. color is a 6-char hex without #."""
    calls_before = client.api_calls
    owner, name = repo.split("/", 1)
    data = client.post(f"/repos/{owner}/{name}/labels", json={
        "name": label_name, "color": color.lstrip("#"), "description": description
    })
    return ToolResult(True, {"name": data["name"], "color": data["color"]},
                      api_calls=client.api_calls - calls_before)


# ─── Pull Requests ───────────────────────────────────────────────────────────

def list_pull_requests(client: GitHubClient, repo: str, state: str = "open",
                       base: Optional[str] = None, limit: int = 20) -> ToolResult:
    calls_before = client.api_calls
    owner, name = repo.split("/", 1)
    params: dict[str, Any] = {"state": state, "per_page": min(limit, 100)}
    if base:
        params["base"] = base
    data = client.get(f"/repos/{owner}/{name}/pulls", params=params)
    return ToolResult(True, data[:limit], api_calls=client.api_calls - calls_before)


def get_pull_request(client: GitHubClient, repo: str, pr_number: int) -> ToolResult:
    calls_before = client.api_calls
    owner, name = repo.split("/", 1)
    data = client.get(f"/repos/{owner}/{name}/pulls/{pr_number}")
    return ToolResult(True, data, api_calls=client.api_calls - calls_before)


def create_pull_request(client: GitHubClient, repo: str, title: str, head: str,
                        base: str = "main", body: str = "", draft: bool = False) -> ToolResult:
    """Create a pull request. head = 'branch-name'."""
    calls_before = client.api_calls
    owner, name = repo.split("/", 1)
    data = client.post(f"/repos/{owner}/{name}/pulls", json={
        "title": title, "head": head, "base": base, "body": body, "draft": draft
    })
    return ToolResult(True, {"number": data["number"], "url": data["html_url"]},
                      api_calls=client.api_calls - calls_before)


# ─── Milestones ──────────────────────────────────────────────────────────────

def list_milestones(client: GitHubClient, repo: str, state: str = "open") -> ToolResult:
    calls_before = client.api_calls
    owner, name = repo.split("/", 1)
    data = client.get(f"/repos/{owner}/{name}/milestones",
                      params={"state": state, "per_page": 50})
    return ToolResult(True, data, api_calls=client.api_calls - calls_before)


def create_milestone(client: GitHubClient, repo: str, title: str,
                     due_on: Optional[str] = None, description: str = "") -> ToolResult:
    """Create a milestone. due_on = ISO 8601 string e.g. '2026-07-01T00:00:00Z'."""
    calls_before = client.api_calls
    owner, name = repo.split("/", 1)
    payload: dict[str, Any] = {"title": title, "description": description}
    if due_on:
        payload["due_on"] = due_on
    data = client.post(f"/repos/{owner}/{name}/milestones", json=payload)
    return ToolResult(True, {"number": data["number"], "title": data["title"]},
                      api_calls=client.api_calls - calls_before)


# ─── Repository ──────────────────────────────────────────────────────────────

def get_repo_info(client: GitHubClient, repo: str) -> ToolResult:
    calls_before = client.api_calls
    owner, name = repo.split("/", 1)
    data = client.get(f"/repos/{owner}/{name}")
    return ToolResult(True, {
        "name": data["name"],
        "full_name": data["full_name"],
        "description": data["description"],
        "open_issues_count": data["open_issues_count"],
        "default_branch": data["default_branch"],
        "topics": data.get("topics", []),
        "url": data["html_url"],
    }, api_calls=client.api_calls - calls_before)


def list_releases(client: GitHubClient, repo: str, limit: int = 10) -> ToolResult:
    calls_before = client.api_calls
    owner, name = repo.split("/", 1)
    data = client.get(f"/repos/{owner}/{name}/releases", params={"per_page": min(limit, 100)})
    return ToolResult(True, data[:limit], api_calls=client.api_calls - calls_before)


def create_release(client: GitHubClient, repo: str, tag_name: str, name: str,
                   body: str = "", draft: bool = False, prerelease: bool = False) -> ToolResult:
    calls_before = client.api_calls
    owner, name_ = repo.split("/", 1)
    data = client.post(f"/repos/{owner}/{name_}/releases", json={
        "tag_name": tag_name, "name": name, "body": body,
        "draft": draft, "prerelease": prerelease
    })
    return ToolResult(True, {"id": data["id"], "url": data["html_url"], "tag": data["tag_name"]},
                      api_calls=client.api_calls - calls_before)


# ─── Collaborators / User ────────────────────────────────────────────────────

def get_authenticated_user(client: GitHubClient) -> ToolResult:
    calls_before = client.api_calls
    data = client.get("/user")
    return ToolResult(True, {"login": data["login"], "name": data.get("name"), "email": data.get("email")},
                      api_calls=client.api_calls - calls_before)


def list_repo_collaborators(client: GitHubClient, repo: str) -> ToolResult:
    calls_before = client.api_calls
    owner, name = repo.split("/", 1)
    data = client.get(f"/repos/{owner}/{name}/collaborators", params={"per_page": 100})
    return ToolResult(True, [{"login": u["login"], "role": u.get("role_name", "?")} for u in data],
                      api_calls=client.api_calls - calls_before)

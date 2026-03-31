"""GitHub client — create branches, commit files, and open PRs via REST API."""

from __future__ import annotations

import logging
import requests
from config import GITHUB_TOKEN, GITHUB_OWNER, GITHUB_REPOS

logger = logging.getLogger(__name__)

API_BASE = "https://api.github.com"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _repo_full_name(repo_key: str) -> str:
    repo_name = GITHUB_REPOS.get(repo_key, repo_key)
    return f"{GITHUB_OWNER}/{repo_name}"


def get_default_branch(repo_key: str) -> str:
    """Get the default branch (usually 'main') for a repo."""
    full = _repo_full_name(repo_key)
    r = requests.get(f"{API_BASE}/repos/{full}", headers=_headers(), timeout=15)
    r.raise_for_status()
    return r.json()["default_branch"]


def get_branch_sha(repo_key: str, branch: str) -> str:
    """Get the latest commit SHA of a branch."""
    full = _repo_full_name(repo_key)
    r = requests.get(f"{API_BASE}/repos/{full}/git/ref/heads/{branch}",
                     headers=_headers(), timeout=15)
    r.raise_for_status()
    return r.json()["object"]["sha"]


def create_branch(repo_key: str, branch_name: str, from_branch: str | None = None) -> str:
    """Create a new branch from the default (or specified) branch. Returns the new branch ref."""
    full = _repo_full_name(repo_key)
    base = from_branch or get_default_branch(repo_key)
    sha = get_branch_sha(repo_key, base)

    r = requests.post(f"{API_BASE}/repos/{full}/git/refs", headers=_headers(), json={
        "ref": f"refs/heads/{branch_name}",
        "sha": sha,
    }, timeout=15)
    r.raise_for_status()
    logger.info(f"Created branch {branch_name} on {full} from {base}")
    return branch_name


def commit_file(repo_key: str, branch: str, path: str, content: str,
                message: str) -> dict:
    """Create or update a file on a branch. Returns the commit info."""
    full = _repo_full_name(repo_key)

    # Check if file exists (to get its SHA for update)
    existing_sha = None
    r = requests.get(f"{API_BASE}/repos/{full}/contents/{path}",
                     headers=_headers(), params={"ref": branch}, timeout=15)
    if r.ok:
        existing_sha = r.json().get("sha")

    import base64
    payload = {
        "message": message,
        "content": base64.b64encode(content.encode()).decode(),
        "branch": branch,
    }
    if existing_sha:
        payload["sha"] = existing_sha

    r = requests.put(f"{API_BASE}/repos/{full}/contents/{path}",
                     headers=_headers(), json=payload, timeout=15)
    r.raise_for_status()
    result = r.json()
    logger.info(f"Committed {path} to {full}/{branch}")
    return {
        "sha": result["commit"]["sha"],
        "url": result["content"]["html_url"],
    }


def create_pull_request(repo_key: str, branch: str, title: str,
                        body: str = "", base: str | None = None) -> dict:
    """Open a pull request. Returns PR number and URL."""
    full = _repo_full_name(repo_key)
    base_branch = base or get_default_branch(repo_key)

    r = requests.post(f"{API_BASE}/repos/{full}/pulls", headers=_headers(), json={
        "title": title,
        "body": body,
        "head": branch,
        "base": base_branch,
    }, timeout=15)
    r.raise_for_status()
    pr = r.json()
    logger.info(f"Created PR #{pr['number']} on {full}: {title}")
    return {
        "number": pr["number"],
        "url": pr["html_url"],
        "title": title,
    }


def create_pr_with_files(repo_key: str, branch_name: str, title: str,
                         description: str, files: list[dict]) -> dict:
    """Full workflow: create branch, commit files, open PR.

    files: list of {"path": "...", "content": "..."}
    Returns PR info.
    """
    if not GITHUB_TOKEN:
        raise ValueError("GITHUB_TOKEN not configured. MJ needs to create a Personal Access Token at github.com/settings/tokens.")

    create_branch(repo_key, branch_name)

    for f in files:
        commit_file(
            repo_key, branch_name, f["path"], f["content"],
            message=f"Update {f['path']}"
        )

    pr = create_pull_request(repo_key, branch_name, title, description)
    return pr

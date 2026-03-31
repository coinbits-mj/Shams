"""Codebase tools — read, search, and understand code across all repos."""

from __future__ import annotations

import os
import logging
import subprocess

logger = logging.getLogger(__name__)

REPOS = {
    "shams": "/app",  # In Railway container, repo is at /app
    "rumi": None,      # Rumi code accessed via GitHub API
    "leo": None,        # Leo code accessed via GitHub API
}

# For local development
if os.path.exists("/Users/mj/code/Shams"):
    REPOS["shams"] = "/Users/mj/code/Shams"
    REPOS["rumi"] = "/Users/mj/code/coffee-pl-bot"
    REPOS["leo"] = "/Users/mj/code/leo-health-coach"

GITHUB_REPOS = {
    "shams": "coinbits-mj/Shams",
    "rumi": "coinbits-mj/coffee-pl-bot",
    "leo": "coinbits-mj/leo-health-coach",
}


def list_files(repo: str, path: str = "", pattern: str = "*.py") -> list[str]:
    """List files in a repo directory matching a pattern."""
    repo_path = REPOS.get(repo)
    if not repo_path or not os.path.exists(repo_path):
        return _github_list_files(repo, path)

    import glob
    search_path = os.path.join(repo_path, path, "**", pattern)
    files = glob.glob(search_path, recursive=True)
    # Return relative paths
    return [os.path.relpath(f, repo_path) for f in files
            if "node_modules" not in f and ".git" not in f and "__pycache__" not in f]


def read_file(repo: str, filepath: str) -> str:
    """Read a file from a repo."""
    repo_path = REPOS.get(repo)
    if not repo_path or not os.path.exists(repo_path):
        return _github_read_file(repo, filepath)

    full_path = os.path.join(repo_path, filepath)
    if not os.path.exists(full_path):
        return f"File not found: {filepath}"
    try:
        with open(full_path) as f:
            content = f.read()
        # Cap at 10k chars
        if len(content) > 10000:
            return content[:10000] + f"\n\n... [truncated, {len(content)} total chars]"
        return content
    except Exception as e:
        return f"Error reading {filepath}: {e}"


def search_code(repo: str, query: str) -> list[dict]:
    """Search for a string across a repo. Returns [{file, line, content}]."""
    repo_path = REPOS.get(repo)
    if not repo_path or not os.path.exists(repo_path):
        return _github_search_code(repo, query)

    results = []
    try:
        out = subprocess.run(
            ["grep", "-rn", "--include=*.py", "--include=*.jsx", "--include=*.js",
             "--include=*.md", "--include=*.sql", "--include=*.toml",
             query, repo_path],
            capture_output=True, text=True, timeout=10
        )
        for line in out.stdout.strip().split("\n")[:20]:
            if not line:
                continue
            parts = line.split(":", 2)
            if len(parts) >= 3:
                results.append({
                    "file": os.path.relpath(parts[0], repo_path),
                    "line": parts[1],
                    "content": parts[2][:200],
                })
    except Exception as e:
        logger.error(f"Code search error: {e}")

    return results


def get_repo_structure(repo: str) -> str:
    """Get a tree-like view of the repo structure."""
    repo_path = REPOS.get(repo)
    if not repo_path or not os.path.exists(repo_path):
        return f"Repo '{repo}' not accessible locally."

    lines = []
    for root, dirs, files in os.walk(repo_path):
        # Skip common noise
        dirs[:] = [d for d in dirs if d not in (
            "node_modules", ".git", "__pycache__", "dist", ".claude", "venv", ".venv"
        )]
        level = root.replace(repo_path, "").count(os.sep)
        indent = "  " * level
        dirname = os.path.basename(root)
        lines.append(f"{indent}{dirname}/")
        sub_indent = "  " * (level + 1)
        for f in sorted(files):
            if not f.startswith(".") or f in (".env.example", ".gitignore"):
                lines.append(f"{sub_indent}{f}")

    return "\n".join(lines[:200])


# GitHub fallbacks for Railway (where local repos aren't available)

def _github_list_files(repo: str, path: str) -> list[str]:
    gh_repo = GITHUB_REPOS.get(repo)
    if not gh_repo:
        return []
    try:
        out = subprocess.run(
            ["gh", "api", f"repos/{gh_repo}/git/trees/main?recursive=1"],
            capture_output=True, text=True, timeout=15
        )
        import json
        data = json.loads(out.stdout)
        return [t["path"] for t in data.get("tree", [])
                if t["type"] == "blob" and t["path"].endswith(".py")][:50]
    except Exception:
        return []


def _github_read_file(repo: str, filepath: str) -> str:
    gh_repo = GITHUB_REPOS.get(repo)
    if not gh_repo:
        return "Repo not configured."
    try:
        out = subprocess.run(
            ["gh", "api", f"repos/{gh_repo}/contents/{filepath}",
             "-H", "Accept: application/vnd.github.raw"],
            capture_output=True, text=True, timeout=15
        )
        content = out.stdout
        if len(content) > 10000:
            return content[:10000] + "\n\n... [truncated]"
        return content
    except Exception as e:
        return f"Error: {e}"


def _github_search_code(repo: str, query: str) -> list[dict]:
    gh_repo = GITHUB_REPOS.get(repo)
    if not gh_repo:
        return []
    try:
        out = subprocess.run(
            ["gh", "search", "code", query, f"--repo={gh_repo}", "--json=path,textMatches", "-L5"],
            capture_output=True, text=True, timeout=15
        )
        import json
        data = json.loads(out.stdout)
        return [{"file": r["path"], "line": "?", "content": str(r.get("textMatches", ""))[:200]} for r in data]
    except Exception:
        return []

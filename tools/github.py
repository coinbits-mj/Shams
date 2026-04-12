"""GitHub / codebase tools."""
from __future__ import annotations

from tools.registry import tool


@tool(
    name="read_codebase",
    description="Read a file from any of Maher's codebases (shams, rumi, leo). Use this to understand how something works, review code, or help Builder plan changes.",
    agent="ops",
    schema={
        "properties": {
            "repo": {"type": "string", "description": "Which repo: 'shams', 'rumi', or 'leo'", "enum": ["shams", "rumi", "leo"]},
            "filepath": {"type": "string", "description": "Path to the file, e.g. 'app.py' or 'engine/pl_engine.py'"},
        },
        "required": ["repo", "filepath"],
    },
)
def read_codebase(repo: str, filepath: str) -> str:
    from agents.codebase import read_file

    return read_file(repo, filepath)


@tool(
    name="search_codebase",
    description="Search for a string across a codebase. Returns matching files and lines.",
    agent="ops",
    schema={
        "properties": {
            "repo": {"type": "string", "description": "Which repo: 'shams', 'rumi', or 'leo'", "enum": ["shams", "rumi", "leo"]},
            "query": {"type": "string", "description": "Search string"},
        },
        "required": ["repo", "query"],
    },
)
def search_codebase(repo: str, query: str) -> str:
    import json
    from agents.codebase import search_code

    results = search_code(repo, query)
    return json.dumps(results, indent=2) if results else "No matches found."


@tool(
    name="list_codebase_files",
    description="List files in a codebase directory.",
    agent="ops",
    schema={
        "properties": {
            "repo": {"type": "string", "description": "Which repo: 'shams', 'rumi', or 'leo'", "enum": ["shams", "rumi", "leo"]},
            "path": {"type": "string", "description": "Directory path (e.g. 'engine/' or ''  for root)", "default": ""},
        },
        "required": ["repo"],
    },
)
def list_codebase_files(repo: str, path: str = "") -> str:
    from agents.codebase import list_files

    files = list_files(repo, path)
    return "\n".join(files) if files else "No files found."


@tool(
    name="get_repo_structure",
    description="Get a tree view of an entire codebase structure.",
    agent="ops",
    schema={
        "properties": {
            "repo": {"type": "string", "description": "Which repo: 'shams', 'rumi', or 'leo'", "enum": ["shams", "rumi", "leo"]},
        },
        "required": ["repo"],
    },
)
def get_repo_structure(repo: str) -> str:
    from agents.codebase import get_repo_structure as _get_repo_structure

    return _get_repo_structure(repo)


@tool(
    name="propose_code_change",
    description="Propose a code change to one of Maher's repos. Creates a GitHub PR for review after approval. Use this when Builder plans a fix, feature, or refactor.",
    agent="ops",
    schema={
        "properties": {
            "repo": {"type": "string", "description": "Which repo", "enum": ["shams", "rumi", "leo"]},
            "title": {"type": "string", "description": "PR title describing the change"},
            "description": {"type": "string", "description": "What this change does and why"},
            "files": {
                "type": "array",
                "description": "Files to create or update",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path in the repo"},
                        "content": {"type": "string", "description": "Full file content"},
                    },
                    "required": ["path", "content"],
                },
            },
        },
        "required": ["repo", "title", "files"],
    },
)
def propose_code_change(repo: str, title: str, files: list, description: str = "") -> str:
    import memory

    action_id = memory.create_action(
        agent_name="builder",
        action_type="create_pr",
        title=f"PR: {title}",
        description=description,
        payload={
            "repo": repo,
            "title": title,
            "description": description,
            "files": files,
        },
    )
    memory.log_activity("builder", "action_proposed",
        f"Action #{action_id}: PR proposed for {repo} — {title}")
    file_list = ", ".join(f["path"] for f in files)
    return (f"Code change #{action_id} proposed: {title}\n"
            f"Files: {file_list}\n"
            f"Waiting for Maher's approval in the dashboard.")

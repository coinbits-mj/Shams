"""Legal document and research tools."""
from __future__ import annotations

import logging

from tools.registry import tool

logger = logging.getLogger(__name__)


@tool(
    name="draft_legal_document",
    description="Have Wakil draft a legal document. Creates the document and saves it to Files. Use for LOIs, NDAs, term sheets, legal memos, employment letters, counter-proposals, or any legal document.",
    agent="wakil",
    schema={
        "properties": {
            "document_type": {
                "type": "string",
                "enum": ["loi", "nda", "term_sheet", "legal_memo", "employment_letter", "counter_proposal", "contract", "other"],
                "description": "Type of legal document",
            },
            "title": {"type": "string", "description": "Document title"},
            "instructions": {"type": "string", "description": "What the document should cover — parties, terms, key provisions, context"},
            "context": {"type": "string", "description": "Relevant background (deal details, prior negotiations, etc.)"},
            "mission_id": {"type": "integer", "description": "Optional mission ID this document relates to"},
        },
        "required": ["document_type", "title", "instructions"],
    },
)
def draft_legal_document(document_type: str, title: str, instructions: str, context: str = "", mission_id: int = None) -> str:
    import anthropic
    import memory
    from agents.registry import build_agent_system_prompt
    from config import ANTHROPIC_API_KEY, CLAUDE_MODEL

    # Templates to guide Wakil
    template_hints = {
        "loi": "Include: parties, target entity, purchase price/structure, due diligence period, exclusivity, earnout terms if applicable, conditions precedent, expiration date. Use professional legal formatting.",
        "nda": "Include: parties, definition of confidential information, obligations, term, exceptions (public info, prior knowledge), remedies, governing law (NJ).",
        "term_sheet": "Include: parties, transaction type, valuation/price, structure (equity/RBF/musharaka), key terms, conditions, timeline, exclusivity. Note any Islamic finance considerations.",
        "legal_memo": "Structure: Issue, Brief Answer, Facts, Analysis, Conclusion, Recommended Action. Be direct and strategic.",
        "employment_letter": "Include: position, compensation, benefits, start date, at-will status, non-compete if applicable, reporting structure.",
        "counter_proposal": "Reference the original proposal, identify areas of agreement, present counter-terms with reasoning, deadline for response.",
        "contract": "Include standard contract elements: parties, recitals, definitions, obligations, representations, indemnification, termination, governing law.",
        "other": "",
    }

    draft_prompt = (
        f"Draft the following legal document:\n\n"
        f"**Type:** {document_type}\n"
        f"**Title:** {title}\n"
        f"**Instructions:** {instructions}\n"
    )
    if context:
        draft_prompt += f"\n**Context:** {context}\n"
    hint = template_hints.get(document_type, "")
    if hint:
        draft_prompt += f"\n**Template guidance:** {hint}\n"
    draft_prompt += "\nOutput the full document text, ready for review. Use professional legal formatting."

    wakil_system = build_agent_system_prompt("wakil")
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    draft_response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        system=wakil_system,
        messages=[{"role": "user", "content": draft_prompt}],
    )
    draft_text = draft_response.content[0].text

    # Save to files table
    filename = f"{document_type}_{title.lower().replace(' ', '_')[:40]}.md"
    file_id = memory.save_file(
        filename=filename,
        file_type="legal_draft",
        mime_type="text/markdown",
        file_size=len(draft_text),
        summary=f"[{document_type.upper()}] {title}",
        transcript=draft_text,
        mission_id=mission_id,
    )
    memory.log_activity("wakil", "document_drafted",
        f"Legal draft: {title} (file #{file_id})",
        {"document_type": document_type, "file_id": file_id})
    memory.create_notification("document_ready", f"{document_type.upper()}: {title} ready for review", "", "file", file_id)

    # Auto-advance linked mission to review
    if mission_id:
        memory.update_mission(mission_id, status="review")
        memory.log_activity("wakil", "mission_update", f"Mission #{mission_id} → review (document drafted)")
        memory.create_notification("mission_updated", f"Mission #{mission_id} moved to review", "Document ready", "mission", mission_id)

    return f"Document drafted and saved as file #{file_id}: {title}\n\nPreview:\n{draft_text[:500]}..."


@tool(
    name="assign_research",
    description="Assign a research task to Scout. Scout will search the web, compile findings, and report back. Creates a mission assigned to Scout.",
    agent="ops",
    schema={
        "properties": {
            "query": {"type": "string", "description": "What to research"},
            "depth": {"type": "string", "enum": ["quick", "deep"], "default": "quick",
                      "description": "Quick = surface-level search, Deep = multiple queries and source analysis"},
            "deadline": {"type": "string", "description": "When results are needed (e.g. 'today', 'this week')"},
        },
        "required": ["query"],
    },
)
def assign_research(query: str, depth: str = "quick", deadline: str = "") -> str:
    import memory

    description = f"Research query: {query}\nDepth: {depth}"
    if deadline:
        description += f"\nDeadline: {deadline}"
    mission_id = memory.create_mission(
        title=f"Research: {query[:100]}",
        description=description,
        priority="high" if depth == "deep" else "normal",
        assigned_agent="scout",
    )
    memory.log_activity("scout", "mission_created",
        f"Mission #{mission_id}: Research assigned — {query[:80]}")
    return f"Research mission #{mission_id} assigned to Scout: {query}"

"""Tools the agent can ask for, and the code that actually runs them.

The LLM never executes anything itself: it only returns a tool name and JSON
arguments. This module validates the arguments and does the real work.
"""

import re
import time

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.knowledge import get_knowledge_base, load_projects

# --- Which tools need a human? ----------------------------------------------
# "auto": runs immediately. "requires_approval": Dionysios must approve first.
TOOL_POLICY = {
    "search_profile": "auto",
    "list_projects": "auto",
    "check_live_site": "auto",
    "request_follow_up": "requires_approval",
}

# --- Tool definitions sent to the LLM (name, description, JSON Schema) ------
TOOL_DEFINITIONS = [
    {
        "name": "search_profile",
        "description": (
            "Search Dionysios's CV, experience, skills, projects, way of working, fit for the SquareDev role, "
            "and notes about how this agent was built. Returns the most relevant sections with a source id. "
            "The knowledge base is in English, so always write the query in English keywords."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "English keywords, e.g. 'MCP production experience'"}},
            "required": ["query"],
        },
    },
    {
        "name": "list_projects",
        "description": "List all of Dionysios's live client projects with domain, client, his role, a one-line summary and case study link.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "check_live_site",
        "description": (
            "Call the public WordPress REST API of one of Dionysios's live sites, right now, as live proof that it "
            "exists and runs. Returns the site's name, response time, number of pages, number of products for "
            "e-shops, whether its MCP endpoint is live, and the custom REST endpoints he built. "
            "Only his own project domains are allowed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"domain": {"type": "string", "description": "e.g. politeknosagrotis.gr"}},
            "required": ["domain"],
        },
    },
    {
        "name": "request_follow_up",
        "description": (
            "Ask Dionysios for a follow-up (a call, a meeting, more material). Use only when the visitor explicitly "
            "asks for it and has given a name and an email. Dionysios must approve it before it is confirmed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "email": {"type": "string"},
                "message": {"type": "string", "description": "What the visitor wants, in one or two sentences"},
            },
            "required": ["name", "email", "message"],
        },
    },
]


# --- Argument validation (never trust what the model produced) -------------
class SearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=200)


class LiveSiteInput(BaseModel):
    domain: str = Field(min_length=3, max_length=100)

    @field_validator("domain")
    @classmethod
    def normalise(cls, v: str) -> str:
        v = re.sub(r"^https?://", "", v.strip().lower()).split("/")[0]
        return v.removeprefix("www.")


class FollowUpInput(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: str = Field(max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    message: str = Field(min_length=3, max_length=1000)


# --- Live site check -------------------------------------------------------
def _project_by_domain(domain: str) -> dict | None:
    return next((p for p in load_projects() if p["domain"] == domain), None)


def check_live_site(domain: str) -> dict:
    project = _project_by_domain(domain)
    if project is None:
        allowed = ", ".join(p["domain"] for p in load_projects())
        raise ValueError(f"Not one of Dionysios's projects. Allowed: {allowed}")

    base = f"https://{domain}/wp-json"
    headers = {"User-Agent": "interview-my-agent/1.0"}
    with httpx.Client(timeout=10, headers=headers, follow_redirects=True) as http:
        start = time.perf_counter()
        root = http.get(f"{base}/", params={"_fields": "name,description,namespaces"})
        elapsed_ms = round((time.perf_counter() - start) * 1000)
        root.raise_for_status()
        info = root.json()
        namespaces = info.get("namespaces", [])

        pages = http.get(f"{base}/wp/v2/pages", params={"per_page": 1, "_fields": "id"})
        result = {
            "site": f"https://{domain}",
            "name": info.get("name"),
            "description": info.get("description"),
            "response_time_ms": elapsed_ms,
            "published_pages": int(pages.headers.get("X-WP-Total", 0)) if pages.is_success else None,
            "mcp_endpoint_live": "mcp" in namespaces,
            "custom_rest_endpoints_he_built": [n for n in project["custom_namespaces"] if n in namespaces],
        }
        if "wc/store/v1" in namespaces:
            products = http.get(f"{base}/wc/store/v1/products", params={"per_page": 1})
            if products.is_success:
                result["products_in_shop"] = int(products.headers.get("X-WP-Total", 0))
        result["checked_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        return result


def validate_before_approval(name: str, tool_input: dict) -> str | None:
    """Check arguments before asking a human, so nobody is asked to approve invalid input."""
    try:
        if name == "request_follow_up":
            FollowUpInput(**tool_input)
        return None
    except ValidationError as e:
        return f"Invalid arguments: {e.errors(include_url=False)}"


# --- Single entry point used by the agent -----------------------------------
def execute_tool(name: str, tool_input: dict) -> dict:
    """Validate the arguments and run the tool. Returns {"ok": bool, "output"|"error": ...}."""
    try:
        if name == "search_profile":
            args = SearchInput(**tool_input)
            hits = get_knowledge_base().search(args.query)
            return {"ok": True, "output": hits or "No matching information in the knowledge base."}
        if name == "list_projects":
            projects = [{k: p[k] for k in ("name", "domain", "client", "role", "summary", "case_study")}
                        for p in load_projects()]
            return {"ok": True, "output": projects}
        if name == "check_live_site":
            args = LiveSiteInput(**tool_input)
            return {"ok": True, "output": check_live_site(args.domain)}
        if name == "request_follow_up":
            args = FollowUpInput(**tool_input)
            return {"ok": True, "output": {
                "status": "confirmed",
                "note": f"Dionysios approved the follow-up with {args.name} and will reply to {args.email}.",
            }}
        return {"ok": False, "error": f"Unknown tool: {name}"}
    except ValidationError as e:
        return {"ok": False, "error": f"Invalid arguments: {e.errors(include_url=False)}"}
    except (httpx.HTTPError, ValueError) as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}

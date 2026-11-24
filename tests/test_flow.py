"""End-to-end tests with the scripted LLM (no API calls, no network).

FastAPI's TestClient runs background tasks right after each response,
so every step below is deterministic.
"""

from app.config import Settings
from app.knowledge import get_knowledge_base
from app.tools import execute_tool, validate_before_approval


def _ask(client, message, conversation_id=None):
    if conversation_id is None:
        r = client.post("/conversations", json={"message": message})
        assert r.status_code == 201
    else:
        r = client.post(f"/conversations/{conversation_id}/messages", json={"message": message})
        assert r.status_code == 202
    return client.get(f"/conversations/{r.json()['id']}").json()


def test_question_is_answered_from_the_profile(client):
    conv = _ask(client, "What has he built with MCP in production?")
    assert conv["status"] == "idle"
    roles = [t["role"] for t in conv["transcript"]]
    assert roles == ["visitor", "tool", "agent"]
    assert conv["transcript"][1]["text"].startswith("Searched his profile")
    assert "Sources:" in conv["transcript"][2]["text"]

    events = [e["event_type"] for e in client.get(f"/conversations/{conv['id']}/audit").json()]
    assert events == ["visitor_message", "llm_response", "tool_executed", "llm_response", "answer_sent"]


def test_conversation_has_multiple_turns(client):
    conv = _ask(client, "What is his education?")
    conv = _ask(client, "And which languages does he speak?", conv["id"])
    assert conv["status"] == "idle"
    assert conv["visitor_messages"] == 2
    assert [t["role"] for t in conv["transcript"]].count("visitor") == 2


def test_follow_up_waits_for_approval_then_continues(client):
    conv = _ask(client, "Can we schedule a follow-up call?")
    assert conv["status"] == "waiting_approval"

    # The visitor cannot send another message while the agent waits.
    assert client.post(f"/conversations/{conv['id']}/messages", json={"message": "hello?"}).status_code == 409

    approval = next(a for a in client.get("/approvals").json() if a["conversation_id"] == conv["id"])
    assert approval["tool_name"] == "request_follow_up"
    r = client.post(f"/approvals/{approval['id']}/approve", json={"reviewer": "Dionysios"})
    assert r.status_code == 200 and r.json()["status"] == "approved"

    conv = client.get(f"/conversations/{conv['id']}").json()
    assert conv["status"] == "idle"
    assert "approved" in conv["transcript"][-1]["text"]

    audit = client.get(f"/conversations/{conv['id']}/audit").json()
    decided = next(e for e in audit if e["event_type"] == "approval_decided")
    assert decided["actor"] == "human:Dionysios"
    assert client.post(f"/approvals/{approval['id']}/reject").status_code == 409  # already decided


def test_declined_follow_up(client):
    conv = _ask(client, "I'd like a follow-up meeting")
    approval = next(a for a in client.get("/approvals").json() if a["conversation_id"] == conv["id"])
    client.post(f"/approvals/{approval['id']}/reject", json={"reviewer": "Dionysios", "reason": "Busy this week"})
    conv = client.get(f"/conversations/{conv['id']}").json()
    assert conv["status"] == "idle"
    assert "declined" in conv["transcript"][-1]["text"]


def test_validation_and_not_found(client):
    assert client.post("/conversations", json={"message": ""}).status_code == 422
    assert client.get("/conversations/999999").status_code == 404
    assert client.post("/conversations/999999/messages", json={"message": "hi"}).status_code == 404
    assert client.post("/approvals/999999/approve").status_code == 404


def test_admin_endpoints_need_the_token_when_set(client, monkeypatch):
    monkeypatch.setattr("app.main.settings", Settings(admin_token="s3cret"))
    assert client.get("/approvals").status_code == 401
    assert client.get("/approvals", headers={"X-Admin-Token": "wrong"}).status_code == 401
    assert client.get("/approvals", headers={"X-Admin-Token": "s3cret"}).status_code == 200
    # The visitor side stays public.
    assert client.get("/api/projects").status_code == 200


def test_live_site_tool_only_accepts_his_domains():
    out = execute_tool("check_live_site", {"domain": "https://example.com/wp-admin"})
    assert out["ok"] is False and "Not one of Dionysios's projects" in out["error"]


def test_follow_up_arguments_are_checked_before_asking_a_human():
    assert validate_before_approval("request_follow_up", {"name": "Ann", "email": "not-an-email", "message": "Hi"})
    assert validate_before_approval("request_follow_up", {"name": "Ann", "email": "ann@example.com", "message": "Hi there"}) is None


def test_knowledge_search_finds_the_right_sections():
    kb = get_knowledge_base()
    assert kb.search("members area parents children")[0]["source"] == "projects#apollon"
    assert kb.search("structured output press release Claude API")[0]["source"] == "projects#pametheatro"
    assert any(h["source"].startswith("fit-squaredev#where") for h in kb.search("Kubernetes"))


def test_pages_and_health(client):
    assert client.get("/health").json()["status"] == "ok"
    assert "Interview my agent" in client.get("/").text
    assert "Admin" in client.get("/admin").text
    assert client.get("/static/Dionysios_Kyriakongonas_CV.pdf").status_code == 200
    assert len(client.get("/api/projects").json()) == 10

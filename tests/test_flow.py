"""End-to-end tests with the scripted LLM (no API calls, no network).

FastAPI's TestClient runs background tasks right after each response,
so every step below is deterministic.
"""

from app.config import Settings
from app.knowledge import get_knowledge_base
from app.tools import execute_tool, validate_before_approval


_keys: dict[int, str] = {}


def _ask(client, message, conversation_id=None):
    if conversation_id is None:
        r = client.post("/conversations", json={"message": message})
        assert r.status_code == 201
        _keys[r.json()["id"]] = r.json()["access_key"]
    else:
        r = client.post(f"/conversations/{conversation_id}/messages?key={_keys[conversation_id]}", json={"message": message})
        assert r.status_code == 202
    return _get(client, r.json()["id"])


def _get(client, conversation_id):
    return client.get(f"/conversations/{conversation_id}?key={_keys[conversation_id]}").json()


def test_question_is_answered_from_the_profile(client):
    conv = _ask(client, "What has he built with MCP in production?")
    assert conv["status"] == "idle"
    roles = [t["role"] for t in conv["transcript"]]
    assert roles == ["visitor", "tool", "agent"]
    assert conv["transcript"][1]["text"].startswith("Searched his profile")
    answer = conv["transcript"][2]
    assert "Sources:" not in answer["text"]  # the raw line is replaced by verified, readable sources
    assert answer["sources"] and answer["sources"][0]["label"]

    audit = client.get(f"/conversations/{conv['id']}/audit").json()
    assert [e["event_type"] for e in audit] == ["visitor_message", "llm_response", "tool_executed", "llm_response", "answer_sent"]
    assert audit[-1]["data"]["sources_dropped"] == [] and audit[-1]["data"]["sources_verified"]


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
    assert client.post(f"/conversations/{conv['id']}/messages?key={_keys[conv['id']]}",
                       json={"message": "hello?"}).status_code == 409

    approval = next(a for a in client.get("/approvals").json() if a["conversation_id"] == conv["id"])
    assert approval["tool_name"] == "request_follow_up"
    r = client.post(f"/approvals/{approval['id']}/approve", json={"reviewer": "Dionysios"})
    assert r.status_code == 200 and r.json()["status"] == "approved"

    conv = _get(client, conv["id"])
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
    conv = _get(client, conv["id"])
    assert conv["status"] == "idle"
    assert "declined" in conv["transcript"][-1]["text"]


def test_validation_and_not_found(client):
    assert client.post("/conversations", json={"message": ""}).status_code == 422
    assert client.get("/conversations/999999?key=x").status_code == 404
    assert client.post("/conversations/999999/messages?key=x", json={"message": "hi"}).status_code == 404
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
    assert len(client.get("/api/projects").json()) == 11


def test_visitors_cannot_read_other_conversations(client):
    conv = _ask(client, "What is his education?")
    assert client.get(f"/conversations/{conv['id']}").status_code == 404
    assert client.get(f"/conversations/{conv['id']}?key=wrong").status_code == 404
    assert client.post(f"/conversations/{conv['id']}/messages?key=wrong", json={"message": "hi"}).status_code == 404
    assert _get(client, conv["id"])["access_key"] is None  # the key is only returned once, on creation


def test_rate_limit_per_visitor(client, monkeypatch):
    monkeypatch.setattr("app.limits.settings", Settings(rate_limit_per_minute=2, max_daily_messages=100000))
    headers = {"CF-Connecting-IP": "203.0.113.7"}
    assert client.post("/conversations", json={"message": "one"}, headers=headers).status_code == 201
    assert client.post("/conversations", json={"message": "two"}, headers=headers).status_code == 201
    assert client.post("/conversations", json={"message": "three"}, headers=headers).status_code == 429
    # Another visitor is not affected.
    assert client.post("/conversations", json={"message": "hi"}, headers={"CF-Connecting-IP": "203.0.113.8"}).status_code == 201


def test_daily_cap(client, monkeypatch):
    monkeypatch.setattr("app.limits.settings", Settings(rate_limit_per_minute=1000, max_daily_messages=0))
    r = client.post("/conversations", json={"message": "hello"})
    assert r.status_code == 429 and "daily limit" in r.json()["detail"]


def test_admin_is_closed_over_a_public_link_without_a_token(client):
    assert client.get("/approvals").status_code == 200  # from this laptop
    assert client.get("/approvals", headers={"CF-Connecting-IP": "203.0.113.9"}).status_code == 403


def test_thinking_blocks_are_sent_back_unchanged():
    from anthropic.types import RedactedThinkingBlock, TextBlock, ThinkingBlock, ToolUseBlock

    from app.agent import _block_to_dict

    assert _block_to_dict(ThinkingBlock(type="thinking", thinking="Let me check.", signature="sig123")) == {
        "type": "thinking", "thinking": "Let me check.", "signature": "sig123"}
    assert _block_to_dict(RedactedThinkingBlock(type="redacted_thinking", data="abc")) == {
        "type": "redacted_thinking", "data": "abc"}
    assert _block_to_dict(TextBlock(type="text", text="hi")) == {"type": "text", "text": "hi"}
    assert _block_to_dict(ToolUseBlock(type="tool_use", id="t1", name="list_projects", input={})) == {
        "type": "tool_use", "id": "t1", "name": "list_projects", "input": {}}


def test_pages_are_not_cached(client):
    assert client.get("/").headers["cache-control"] == "no-cache"
    assert client.get("/admin").headers["cache-control"] == "no-cache"


def test_sources_are_verified_against_what_the_tools_returned():
    import json

    from app.agent import split_sources, verify_sources

    text, cited = split_sources("He built a members area.\n\nSources: projects#apollon, projects#invented-by-model")
    assert text == "He built a members area." and cited == ["projects#apollon", "projects#invented-by-model"]

    turn = [
        {"role": "user", "content": "members area?"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "search_profile", "input": {"query": "members area"}},
            {"type": "tool_use", "id": "t2", "name": "check_live_site", "input": {"domain": "apollonhalandriou.gr"}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": json.dumps([{"source": "projects#apollon"}])},
            {"type": "tool_result", "tool_use_id": "t2", "content": "{}"}]},
    ]
    sources, dropped = verify_sources(cited, turn)
    assert [x["label"] for x in sources] == ["Project: Apollon Chalandriou", "Live check: apollonhalandriou.gr"]
    assert dropped == ["projects#invented-by-model"]
    # A Greek "Πηγές:" line is understood too.
    assert split_sources("Απάντηση.\nΠηγές: skills#front-end")[1] == ["skills#front-end"]


def test_nextjs_pages_are_recognised():
    from app.tools import describe_page

    page = '<html><head><title>Site &amp; shop</title><script src="/_next/static/x.js"></script></head>' \
           '<body><script>self.__next_f.push([1,""])</script></body></html>'
    assert describe_page(page) == {"title": "Site & shop", "framework": "Next.js (App Router)"}
    assert describe_page("<title>WordPress site</title>")["framework"] is None

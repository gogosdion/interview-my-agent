"""A scripted stand-in for the LLM.

Used by the tests (fast and deterministic) and as an offline backup for the
demo (LLM_MODE=fake). It returns the same response shape as the Anthropic SDK:
.content (text / tool_use blocks), .stop_reason, .usage, .model.

It really calls the tools (search, follow-up), but its "answers" are simple:
it quotes the best search result instead of writing a real reply.
"""

import json
from itertools import count
from types import SimpleNamespace

_ids = count(1)


def _text(text):
    return SimpleNamespace(type="text", text=text)


def _tool_use(name, tool_input):
    return SimpleNamespace(type="tool_use", id=f"toolu_fake_{next(_ids)}", name=name, input=tool_input)


def _response(blocks, stop_reason):
    return SimpleNamespace(content=blocks, stop_reason=stop_reason,
                           usage=SimpleNamespace(input_tokens=0, output_tokens=0), model="fake-llm")


class _FakeMessages:
    def create(self, *, messages, **_kwargs):
        last_visitor = max(i for i, m in enumerate(messages) if m["role"] == "user" and isinstance(m["content"], str))
        question = messages[last_visitor]["content"]
        after = messages[last_visitor + 1:]

        if not after:
            if "follow" in question.lower():
                return _response([_text("I'll ask Dionysios to approve this."),
                                  _tool_use("request_follow_up", {"name": "Test Interviewer", "email": "test@example.com",
                                                                  "message": question})], "tool_use")
            return _response([_tool_use("search_profile", {"query": question[:120]})], "tool_use")

        call = next(b for b in after[0]["content"] if b["type"] == "tool_use")
        result = after[-1]["content"][0]
        if call["name"] == "request_follow_up":
            if result.get("is_error"):
                return _response([_text("Dionysios declined this follow-up for now.")], "end_turn")
            return _response([_text("Dionysios approved the follow-up and will reply by email.")], "end_turn")

        if result.get("is_error"):
            return _response([_text("I couldn't look that up right now.")], "end_turn")
        hits = json.loads(result["content"])
        if not isinstance(hits, list) or not hits:
            return _response([_text("I don't have information about that. Please ask Dionysios directly.")], "end_turn")
        best = hits[0]
        first_sentence = best["text"].split(". ")[0].strip()
        return _response([_text(f"(offline mode) From “{best['title']}”: {first_sentence}.\n\nSources: {best['source']}")],
                         "end_turn")


class FakeLLM:
    def __init__(self):
        self.messages = _FakeMessages()

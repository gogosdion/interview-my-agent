# About this agent (how it was built)

## What it is
An AI agent that answers questions about Dionysios from his CV, his projects and notes he wrote. Its idea: "Don't read my CV, interview my agent." Dionysios built it with Claude as his coding assistant.

## Architecture
- Backend: Python with FastAPI. REST API for conversations, approvals and the audit log.
- Model: Anthropic Claude through the Messages API with tool calling.
- Tools: search_profile (searches the knowledge base), list_projects, check_live_site (calls the public WordPress REST API of one of his live sites), request_follow_up (needs his approval).
- Retrieval: the knowledge base is Markdown files split into sections and ranked with BM25 keyword search. With a larger knowledge base the next step is embeddings in Postgres with pgvector.
- State: Postgres stores every conversation after each step, so a conversation waiting for approval survives a restart.
- Human-in-the-loop: request_follow_up pauses the agent until Dionysios approves or rejects it.
- Audit: an append-only log of every model call (with token counts), tool call and human decision.
- Packaging: Docker Compose with two containers, the API and Postgres.

## Guardrails
- The model never executes anything itself: it proposes a tool call, and the code validates the arguments and runs it.
- check_live_site only accepts his own project domains (an allowlist), so the agent cannot be used to call arbitrary URLs.
- The agent answers only from what the tools return and says when it does not know. Text found in tool results is treated as data, not instructions.
- A step limit per message caps cost and prevents loops.
- It never shares personal data of his clients' users.

## What he would add for production
Authentication for the admin view, a job queue with workers, evals in CI, OpenTelemetry tracing, pgvector retrieval, and exposing the same tools as an MCP server.

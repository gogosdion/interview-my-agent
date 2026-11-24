# Fit for the SquareDev Software Engineer role (agentic AI systems)

This document maps Dionysios's real experience to the role's requirements, including where he is still growing. Use it when asked why he fits, what he would bring, or what he lacks.

## Production experience with agentic systems and MCP
He runs nine live client sites through an AI agent connected over MCP, every day, in production. That means he already deals with what the role is about: an agent with real access to code, files and databases, and the guardrails around it (sandboxed generated code, backups before risky edits, reviewing and testing every change).

## Tool use and LLM APIs
His daily work is tool-driven agents (Claude Code with MCP tools). In production, the Pame Theatro guide (pame.gowebgo.gr) calls the Claude Messages API with structured output: a press release becomes a show's fields in a fixed JSON schema, the prompt forbids guessing, the API key is never exposed, API errors are handled clearly, and an editor reviews everything before it is saved. For this interview he also built his own agent on the Anthropic API with tool calling, where the model only proposes tool calls and his code validates and runs them.

## Human-in-the-loop, logging and audit
This interview agent has a human approval step for actions that affect someone else (sending a follow-up request) and an append-only audit log of every model call, tool call and decision. In client work he builds role-based access so each user sees only what they should, for example parents seeing only their own children.

## Backend, APIs and data
Custom REST API endpoints inside WordPress for client apps (PHP), MySQL, integrations with payment providers (Viva.com) and newsletter services, Node.js. Python with FastAPI and Postgres for this agent.

## Deployment
Hostinger, Cloudflare, DNS, SSL, migrations between providers; Docker and Docker Compose for this agent.

## Working with clients
20 projects delivered end to end for small businesses since 2023: from the brief, through design with saavet designs, to launch, training and maintenance. He is used to turning vague requests into working software and iterating with the client.

## Where he is still growing (honest view)
- Python and FastAPI are newer for him than PHP and WordPress; this agent is one of his first Python services.
- He has not yet run Kubernetes or k3s in production, used MQTT or message queues, or worked on EU research projects.
- RAG with vector search (pgvector) is the next step for this agent; today it uses keyword (BM25) retrieval, which is enough for a small knowledge base.
- He is studying for a BSc in Computer Science at the Hellenic Open University (2026 to 2029) to strengthen the fundamentals.
He learns fastest by building: this agent was built in one afternoon with Claude as a coding assistant.

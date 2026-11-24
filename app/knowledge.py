"""Knowledge base about Dionysios, with simple BM25 keyword retrieval.

The Markdown files in /knowledge are split into sections ("chunks"). Projects
come from projects.json, which is also the allowlist for check_live_site.

BM25 is enough for a few dozen chunks. With a bigger corpus the next step
would be embeddings stored in Postgres with pgvector (semantic search).
"""

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"

STOPWORDS = set(
    "a an and are as at be by for from has have he his i in is it its of on or that the this to was what "
    "which who with does did do how can about him there their they them you your me my our we when where why built build tell show".split()
)


DOC_LABELS = {
    "profile": "Profile (CV)",
    "experience": "Experience",
    "skills": "Skills",
    "how-i-work": "How he works",
    "fit-squaredev": "Fit for the role",
    "this-agent": "About this agent",
}


@dataclass(frozen=True)
class Chunk:
    id: str
    title: str
    text: str
    label: str  # short, human-readable name shown to visitors as a source


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"\w+", text.lower()) if len(t) > 1 and t not in STOPWORDS]


def load_projects() -> list[dict]:
    return json.loads((KNOWLEDGE_DIR / "projects.json").read_text(encoding="utf-8"))


def _markdown_chunks(path: Path) -> list[Chunk]:
    text = path.read_text(encoding="utf-8")
    doc_title = text.splitlines()[0].lstrip("# ").strip()
    doc_id = path.stem.split("-", 1)[-1]
    chunks = []
    for section in re.split(r"\n(?=## )", text):
        lines = section.strip().splitlines()
        if not lines:
            continue
        heading = lines[0].lstrip("# ").strip()
        body = "\n".join(lines[1:]).strip()
        if not body:
            continue
        title = doc_title if heading == doc_title else f"{doc_title} › {heading}"
        doc_label = DOC_LABELS.get(doc_id, doc_title)
        label = doc_label if heading == doc_title else f"{doc_label} › {heading}"
        slug = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")
        chunks.append(Chunk(id=f"{doc_id}#{slug}", title=title, text=body, label=label))
    return chunks


def _project_chunk(p: dict) -> Chunk:
    text = (
        f"{p['name']} ({p['domain']}). Client: {p['client']}. Design: {p['design']}. "
        f"Dionysios's role: {p['role']}.\n{p['summary']}\n- " + "\n- ".join(p["details"])
        + f"\nTags: {', '.join(p['tags'])}. Case study: {p['case_study']}"
    )
    return Chunk(id=f"projects#{p['slug']}", title=f"Project › {p['name']}", text=text, label=f"Project: {p['name']}")


class KnowledgeBase:
    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75):
        self.chunks = chunks
        self.k1, self.b = k1, b
        # Titles count twice: a match in a heading is a strong signal.
        self.docs = [Counter(tokenize(c.title) * 2 + tokenize(c.text)) for c in chunks]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg_len = sum(self.lengths) / max(len(self.lengths), 1)
        df = Counter(term for d in self.docs for term in d)
        n = len(chunks)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.labels = {c.id: c.label for c in chunks}

    def search(self, query: str, k: int = 4) -> list[dict]:
        terms = tokenize(query)
        scored = []
        for i, doc in enumerate(self.docs):
            score = 0.0
            for t in terms:
                f = doc.get(t, 0)
                if f:
                    norm = f + self.k1 * (1 - self.b + self.b * self.lengths[i] / self.avg_len)
                    score += self.idf[t] * f * (self.k1 + 1) / norm
            if score > 0:
                scored.append((score, i))
        scored.sort(reverse=True)
        return [
            {"source": self.chunks[i].id, "title": self.chunks[i].title, "text": self.chunks[i].text,
             "score": round(s, 2)}
            for s, i in scored[:k]
        ]

    def label(self, source_id: str) -> str | None:
        return self.labels.get(source_id)


@lru_cache(maxsize=1)
def get_knowledge_base() -> KnowledgeBase:
    chunks = []
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        chunks.extend(_markdown_chunks(path))
    chunks.extend(_project_chunk(p) for p in load_projects())
    return KnowledgeBase(chunks)

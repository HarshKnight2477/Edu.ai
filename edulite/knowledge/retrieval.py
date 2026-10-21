"""Search EduLite's curated notes with SQLite FTS5 (BM25 ranking).

The notes are Markdown files under ``edulite/knowledge/notes``; every ``##``
section becomes one passage. The index lives in memory and is rebuilt at
startup (a few milliseconds), so there is no database to keep in sync and no
embedding model to load: retrieval adds almost no RAM.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

NOTES_DIR = Path(__file__).resolve().parent / "notes"

# Common English and question words that carry no topic information.
STOPWORDS = frozenset("""
a about above after again all also am an and any are as at be because been before being between both but by
can could did do does doing done each explain explanation few for from give had has have having help how i if in
into is it its just know let like me more most my no not now of on once only or other our out over please same
show should simple simply so some such tell than that the their them then there these they this those through to
too under until up us very want was we were what when where which while who why will with would you your yes ok
okay example examples using use used difference between mean means work works working make way get thing things
hi hello hey thanks thank thx cheers bye goodbye good morning evening night great nice cool sure
question questions answer answers new another again something anything really still need try trying
""".split())

HEADING_BONUS = -4.0

TOKEN = re.compile(r"[a-z0-9_]+(?:[+#]{1,2})?", re.I)


@dataclass(frozen=True)
class Passage:
    source: str        # notes file title, e.g. "Python collections"
    section: str       # section heading, e.g. "Tuples"
    text: str
    score: float       # BM25 (more negative = more relevant)

    @property
    def title(self) -> str:
        return f"{self.source} › {self.section}"


def parse_notes(path: Path) -> list[tuple[str, str, str]]:
    """(source title, section heading, section text) for each ``##`` section."""
    source = path.stem.replace("-", " ").capitalize()
    sections: list[tuple[str, str, str]] = []
    heading, lines = None, []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            source = line[2:].strip()
        elif line.startswith("## "):
            if heading:
                sections.append((source, heading, "\n".join(lines).strip()))
            heading, lines = line[3:].strip(), []
        elif heading:
            lines.append(line)
    if heading:
        sections.append((source, heading, "\n".join(lines).strip()))
    return sections


def query_terms(text: str, limit: int = 24) -> list[str]:
    """Topic words from a question, lower-cased, de-duplicated, stopwords removed."""
    seen: dict[str, None] = {}
    for token in TOKEN.findall(text.lower()):
        token = token.strip("_")
        if len(token) < 2 or token in STOPWORDS or token.isdigit():
            continue
        seen.setdefault(token, None)
    return list(seen)[:limit]


class KnowledgeBase:
    def __init__(self, notes_dir: Path = NOTES_DIR):
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        # porter: matches word forms ("sorting" ~ "sort"); unicode61 handles accents.
        self._conn.execute("CREATE VIRTUAL TABLE passages USING fts5("
                           "source UNINDEXED, section, body, tokenize='porter unicode61')")
        rows = [row for path in sorted(Path(notes_dir).glob("*.md")) for row in parse_notes(path)]
        self._conn.executemany("INSERT INTO passages (source, section, body) VALUES (?, ?, ?)", rows)
        self.size = len(rows)
        self.sources = sorted({r[0] for r in rows})

    def search(self, text: str, k: int = 3, max_chars: int = 2400, min_score: float = -3.0,
               relative_cutoff: float = 0.45) -> list[Passage]:
        """Best-matching sections for a question.

        Ranking is BM25 plus a bonus when a query word appears in a section's
        heading. The bonus matters for common words: FTS5 gives almost no weight
        to a term found in over half the sections ("list"), which would
        otherwise keep the "Lists" section out of the results.

        Weak matches are dropped: anything weaker than ``min_score`` (BM25 is
        negative; nearer 0 = weaker) or than ``relative_cutoff`` × the best
        score. So small talk retrieves nothing, and loosely related sections
        don't ride along. ``max_chars`` caps the total text so the notes never
        crowd out the conversation.
        """
        terms = query_terms(text)
        if not terms:
            return []
        # Each term quoted, so user text can never be read as FTS5 syntax.
        quoted = " OR ".join('"' + t.replace('"', "") + '"' for t in terms)
        rows = self._conn.execute(
            "SELECT rowid, source, section, body, bm25(passages, 0.0, 4.0, 1.0) FROM passages "
            "WHERE passages MATCH ? ORDER BY 5 LIMIT 20", (quoted,)).fetchall()
        candidates = {row[0]: list(row[1:]) for row in rows}
        heading_hits = self._conn.execute(
            "SELECT rowid, source, section, body FROM passages WHERE passages MATCH ?",
            (f"section : ({quoted})",)).fetchall()
        for rowid, source, section, body in heading_hits:
            if rowid not in candidates:
                candidates[rowid] = [source, section, body, 0.0]
            candidates[rowid][3] += HEADING_BONUS

        ranked = sorted(candidates.values(), key=lambda c: c[3])
        if not ranked or ranked[0][3] > min_score:
            return []
        cutoff = min(min_score, ranked[0][3] * relative_cutoff)
        passages, used = [], 0
        for source, section, body, score in ranked:
            if score > cutoff or len(passages) == k:
                break
            if used + len(body) > max_chars and passages:
                continue  # skip a long passage that doesn't fit; a shorter one may
            passages.append(Passage(source, section, body[:max_chars], score))
            used += len(body)
        return passages


_default: KnowledgeBase | None = None


def default_knowledge_base() -> KnowledgeBase:
    global _default
    if _default is None:
        _default = KnowledgeBase()
    return _default

"""Tender and grant questionnaires (owner: Business Development).

Retrieval is BM25 over the bid library's passages, with the model turning the question into
English keywords. Passages that state the same fact are grouped, and only the newest document's
passage in each group may be used, so a superseded number never reaches an answer. The model
drafts from the passages it is given; a verifier then checks that every sentence cites a passage it
was given and that every number in it appears in a cited passage. Below the retrieval threshold, or
when the verifier fails, the answer is "the library does not answer this", for a person to write."""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from .. import settings
from ..llm.gateway import GatewayError
from .base import Action, Context, Evidence, Proposal, check_access

USE_CASE = "tender_answers"
WORD = re.compile(r"[^\W_][\w'/%.-]*", re.UNICODE)
NUMBER = re.compile(r"\d[\d.,]*%?")
STOP = {
    "the",
    "a",
    "of",
    "and",
    "to",
    "in",
    "is",
    "our",
    "we",
    "for",
    "with",
    "on",
    "at",
    "by",
    "as",
    "are",
    "all",
    "il",
    "la",
    "di",
    "e",
    "le",
    "i",
    "per",
    "con",
    "dei",
    "del",
    "della",
    "nostro",
    "nostri",
    "un",
    "una",
    "ai",
}


def tokens(text: str) -> list[str]:
    return [w.lower().strip(".,") for w in WORD.findall(text) if w.lower() not in STOP]


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.4, b: float = 0.75) -> None:
        self.docs, self.k1, self.b = docs, k1, b
        self.avg = sum(map(len, docs)) / max(1, len(docs))
        df: Counter[str] = Counter()
        for d in docs:
            df.update(set(d))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.tf = [Counter(d) for d in docs]

    def scores(self, query: list[str]) -> list[float]:
        out = []
        for d, tf in zip(self.docs, self.tf, strict=True):
            s = 0.0
            for q in query:
                if q in tf:
                    f = tf[q]
                    s += self.idf[q] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * len(d) / self.avg))
            out.append(s)
        return out


def _shape(text: str) -> frozenset[str]:
    """A passage's wording without its numbers: passages with the same shape state the same fact."""
    return frozenset(t for t in tokens(NUMBER.sub(" ", text)) if len(t) > 2)


def same_fact(a: str, b: str) -> bool:
    sa, sb = _shape(a), _shape(b)
    return len(sa & sb) / max(1, len(sa | sb)) >= 0.6


class Library:
    def __init__(self, docs: list[dict[str, Any]], passages: list[dict[str, Any]]) -> None:
        self.docs = {d["doc_id"]: d for d in docs}
        self.passages = passages
        self.index = BM25([tokens(p["text"]) for p in passages])

    def search(self, keywords: list[str], k: int = 6) -> list[tuple[float, dict[str, Any]]]:
        """Top passages by BM25, each with its coverage: the idf-weighted share of the query's terms it
        contains (0-1). Coverage, unlike a raw BM25 score, means the same in a library of 10 documents
        and of 10,000; a term the library has never seen counts fully against coverage."""
        q = [t for w in keywords for t in tokens(w)]
        unseen = max(self.index.idf.values(), default=1.0)
        weights = {t: self.index.idf.get(t, unseen) for t in set(q)}
        total = sum(weights.values()) or 1.0
        ranked = sorted(zip(self.index.scores(q), self.passages, self.index.tf, strict=True), key=lambda x: -x[0])
        return [(sum(w for t, w in weights.items() if t in tf) / total, p) for s, p, tf in ranked[:k] if s > 0]

    def newest_only(self, hits: list[tuple[float, dict[str, Any]]]) -> tuple[list, list]:
        """Drops a passage when a newer document states the same fact; returns (kept, superseded)."""
        kept, dropped = [], []
        for s, p in hits:
            day = self.docs[p["doc_id"]]["date"]
            newer = [
                q
                for q in self.passages
                if q["pid"] != p["pid"] and self.docs[q["doc_id"]]["date"] > day and same_fact(q["text"], p["text"])
            ]
            if newer:
                dropped.append((p, max(newer, key=lambda q: self.docs[q["doc_id"]]["date"])))
            else:
                kept.append((s, p))
        return kept, dropped


def verify(answer: dict[str, Any], given: dict[str, str]) -> list[str]:
    problems = []
    for sent in answer.get("sentences", []):
        cites = [c for c in sent["cites"] if c in given]
        if not cites:
            problems.append(f"sentence without a valid citation: {sent['text'][:60]}")
            continue
        cited = " ".join(given[c] for c in cites)
        for n in NUMBER.findall(sent["text"]):
            if n.rstrip(".,") not in cited:
                problems.append(f"number {n} is not in the cited passages")
    return problems


_LIB: dict[str, Library] = {}


def library(ctx: Context) -> Library:
    key = ctx.systems.path
    if key not in _LIB:
        docs, passages = ctx.systems.tender_library()
        _LIB[key] = Library(docs, passages)
    return _LIB[key]


def run(case: dict[str, Any], ctx: Context) -> Proposal:
    check_access(ctx, USE_CASE, case["country"])
    pol = settings.policy()[USE_CASE]
    q = ctx.systems.tender_question(case["ref"])
    if q is None:
        raise LookupError(case["ref"])
    lib = library(ctx)
    results, reasons, evidence = [], [], []
    try:
        qr = ctx.gateway.call("tender.query", {"question": q["text"]})
        results.append(qr)
        keywords = qr.output["keywords"]
    except GatewayError as e:
        keywords = tokens(q["text"])
        reasons.append(f"keywords from the question itself: {e}")
    hits = lib.search(keywords)
    kept, dropped = lib.newest_only(hits) if pol["prefer_newest"] else (hits, [])
    for p, newer in dropped:
        evidence.append(
            Evidence("superseded passage not used", {"old": p["pid"], "newer": newer["pid"]}, f"docs:tender/{p['pid']}")
        )
    top = kept[0][0] if kept else 0.0
    answer: dict[str, Any] = {"abstain": True, "sentences": []}
    if top >= pol["min_coverage"]:
        given = [{"pid": p["pid"], "text": p["text"], "date": lib.docs[p["doc_id"]]["date"]} for _, p in kept[:3]]
        try:
            ar = ctx.gateway.call("tender.answer", {"question": q["text"], "passages": given})
            results.append(ar)
            answer = ar.output
        except GatewayError as e:
            reasons.append(f"no draft: {e}")
        problems = verify(answer, {g["pid"]: g["text"] for g in given}) if not answer["abstain"] else []
        if problems:
            reasons += problems
            answer = {"abstain": True, "sentences": []}
        for g in given:
            evidence.append(Evidence("passage", g["text"], f"docs:tender/{g['pid']}"))
    else:
        evidence.append(Evidence("best retrieval score", round(top, 2), "docs:tender/index"))
    decision = "abstain" if answer["abstain"] else "answer"
    if decision == "abstain":
        reasons.append("the library does not answer this question; a person writes the answer")
    actions = (
        [
            Action(
                "send_answer",
                {"case_id": case["case_id"], "question_id": q["question_id"], "answer": answer},
                role=pol["approval_role"],
            )
        ]
        if decision == "answer"
        else []
    )
    text = " ".join(s["text"] for s in answer.get("sentences", []))
    return Proposal(
        case_id=case["case_id"],
        use_case=USE_CASE,
        country=case["country"],
        decision=decision,
        detail={
            "question": q["text"],
            "answer": text,
            "cites": [c for s in answer.get("sentences", []) for c in s["cites"]],
            "score": round(top, 2),
            "keywords": keywords,
        },
        evidence=evidence,
        actions=actions,
        draft={"language": q["lang"], "text": text} if text else None,
        needs_review=decision == "abstain" or bool(reasons),
        review_reasons=reasons,
        model_calls=ctx.calls(results),
        quarantined=[],
        prepared_by=ctx.principal.oid,
        created_ts=ctx.now or case["opened_ts"],
    )

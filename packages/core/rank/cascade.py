"""Jev cascade ranker: Stage A coarse Noul → Stage B answerability+authority composite."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any
from urllib.parse import urlsplit

from packages.core.fetch.page import fetch_main_text
from packages.core.models import Candidate, RankedResult
from packages.core.rank.jev import (
    JevClient,
    JevError,
    build_stage_a_questions,
    build_stage_b_questions,
    candidates_state,
    parse_noul,
    parse_score_01,
)
from packages.core.rank.near_dupe import collapse_near_dupes

logger = logging.getLogger("agent_seek.rank.cascade")

STAGE_A_BATCH = 25
POSSIBLY_RELEVANT_MIN = 0.45
TOP_FALLBACK = 30
SURVIVOR_CAP = 40
DEEP_FETCH_CAP = 12  # max survivors to fetch page text for
DEEP_FETCH_CONCURRENCY = 6
DEEP_FETCH_TIMEOUT = 5.0
SPAM_FLAG_THRESHOLD = 0.65
ON_TOPIC_FLAG_THRESHOLD = 0.55

# v0.1.2 official preference composite (PRD_DELTA_official_pref_v0.1.2)
ANSWER_WEIGHT = 0.75
FACT_WEIGHT = 0.25
COMPARABLE_EPS = 0.08
ON_TOPIC_MIN = 0.55
AUTH_GATE = 0.65
AUTH_WEIGHT = 0.12  # gated boost when answerability comparable (v0.1.12)
AUTH_SOFT_FLOOR = 0.25  # high semantic authority + on-topic outside ε (v0.1.12)
# Thin fallback ONLY when Stage B authority Noul is missing — not a preference policy.
AUTHORITY_HOST_BOOST = 0.02
SPAM_SOFT_DEMOTE = 0.75
SUBJECT_MATCH_MIN = 0.55  # hard gate: exclude below this if parsed
REPUBLISHER_MIN = 0.55  # hard gate: exclude when is_republisher >= this if parsed
PROMPT_INJECTION_MIN = 0.55  # hard gate: exclude when >= this, or when parse missing


def is_authority_host(url: str) -> bool:
    """Heuristic host hint used ONLY when authority Noul is missing (cold fallback)."""
    if not url or not isinstance(url, str):
        return False
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return False
    host = (parts.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path or ""
    if host.startswith("docs.") or host.startswith("changelog."):
        return True
    if host == "github.com" and "/releases" in path:
        return True
    return False


def apply_authority_host_boost(
    score: float,
    url: str,
    *,
    auth_missing: bool = True,
) -> float:
    """Apply AUTHORITY_HOST_BOOST only when authority Noul is missing; capped at 1.0."""
    if auth_missing and is_authority_host(url):
        return min(1.0, float(score) + AUTHORITY_HOST_BOOST)
    return float(score)


# Backward-compatible alias used by v0.1.1 tests (now auth-missing-only semantics).
def apply_authority_boost(score: float, url: str, *, auth_missing: bool = True) -> float:
    return apply_authority_host_boost(score, url, auth_missing=auth_missing)


def compose_score(
    *,
    answerability: float,
    fact: float = 0.5,
    authority: float | None = None,
    on_topic: float | None = None,
    best_a: float | None = None,
    url: str = "",
) -> float:
    """
    Factoid-leaning composite + *semantic* gated authority (v0.1.12 soft floor).

    Preference comes from Jev `__authority` Noul (any first-party/official source for
    the query subject — docs, blog, changelog, releases, etc.), NOT host allowlists.

    When authority Noul is missing: tiny AUTHORITY_HOST_BOOST as cold fallback only.
    When present + on-topic + auth>=AUTH_GATE:
      - comparable (a within ε of best): AUTH_WEIGHT * auth
      - else: AUTH_SOFT_FLOOR * auth
    No docs.* floors/nudges. No host survivor blessings.
    """
    a = float(answerability)
    fact_v = float(fact)
    base = ANSWER_WEIGHT * a + FACT_WEIGHT * fact_v

    if authority is None:
        base = apply_authority_host_boost(base, url, auth_missing=True)
    else:
        ot = 0.0 if on_topic is None else float(on_topic)
        ba = a if best_a is None else float(best_a)
        auth = float(authority)
        if ot >= ON_TOPIC_MIN and auth >= AUTH_GATE:
            if a >= ba - COMPARABLE_EPS:
                base = min(1.0, base + AUTH_WEIGHT * auth)
            else:
                base = min(1.0, base + AUTH_SOFT_FLOOR * auth)

    return base


def derive_flags(
    *,
    possibly_relevant: float | None = None,
    spam: float | None = None,
    on_topic: float | None = None,
    score: float | None = None,
) -> list[str]:
    flags: list[str] = []
    if on_topic is not None and on_topic >= ON_TOPIC_FLAG_THRESHOLD:
        flags.append("on_topic")
    if spam is not None and spam >= SPAM_FLAG_THRESHOLD:
        flags.append("spam_low")
    if score is not None and score >= 0.75:
        flags.append("high_relevance")
    if possibly_relevant is not None and possibly_relevant < 0.3:
        flags.append("weak_signal")
    return flags


def sort_key(item: tuple[Candidate, float, list[str]]) -> tuple:
    c, score, _ = item
    return (-score, c.raw_rank)


async def _batch_evaluate(
    client: JevClient,
    query: str,
    batch: list[Candidate],
    questions: dict[str, Any],
    *,
    deep: bool = False,
) -> dict[str, Any]:
    state = candidates_state(query, batch, deep=deep)
    return await client.evaluate(state, questions)


async def enrich_survivors_with_bodies(
    survivors: list[Candidate],
    *,
    fetch_cap: int = DEEP_FETCH_CAP,
    concurrency: int = DEEP_FETCH_CONCURRENCY,
    timeout: float = DEEP_FETCH_TIMEOUT,
) -> tuple[list[Candidate], int, int]:
    """
    Fetch main text for top fetch_cap survivors (by current order).
    Mutates Candidate.body in place. Returns (survivors, fetched_ok, fetch_ms).
    """
    targets = survivors[:fetch_cap]
    if not targets:
        return survivors, 0, 0
    sem = asyncio.Semaphore(concurrency)
    t0 = time.perf_counter()

    async def _one(c: Candidate) -> bool:
        async with sem:
            text = await fetch_main_text(c.url, timeout=timeout)
        if text:
            c.body = text
            return True
        return False

    results = await asyncio.gather(*[_one(c) for c in targets], return_exceptions=True)
    ok = sum(1 for r in results if r is True)
    fetch_ms = int((time.perf_counter() - t0) * 1000)
    logger.info("deep fetch: %s/%s ok in %sms", ok, len(targets), fetch_ms)
    return survivors, ok, fetch_ms



def apply_subject_match_gate(
    scored: list[tuple],
    subject_match: dict[str, float],
    *,
    min_score: float = SUBJECT_MATCH_MIN,
) -> list[tuple]:
    """
    Hard exposure gate (v0.1.10). Drop candidates with parsed subject_match < min.
    Missing parse → fail-open (keep). Does not mutate raw discover order.
    """
    kept: list[tuple] = []
    dropped = 0
    for item in scored:
        c = item[0]
        sm = subject_match.get(c.id)
        if sm is not None and sm < min_score:
            dropped += 1
            logger.debug(
                "subject_match gate drop cid=%s url=%s sm=%.3f",
                c.id,
                getattr(c, "url", ""),
                sm,
            )
            continue
        kept.append(item)
    if dropped:
        logger.info("subject_match gate dropped %s candidate(s)", dropped)
    return kept



def apply_republisher_gate(
    scored: list[tuple],
    is_republisher: dict[str, float],
    *,
    min_score: float = REPUBLISHER_MIN,
) -> list[tuple]:
    """
    Hard exposure gate (v0.1.11). Drop when parsed is_republisher >= min.
    Missing parse → fail-open. Role-based Jev judgment only — no domain blocklists.
    """
    kept: list[tuple] = []
    dropped = 0
    for item in scored:
        c = item[0]
        rp = is_republisher.get(c.id)
        if rp is not None and rp >= min_score:
            dropped += 1
            logger.debug(
                "republisher gate drop cid=%s url=%s rp=%.3f",
                c.id,
                getattr(c, "url", ""),
                rp,
            )
            continue
        kept.append(item)
    if dropped:
        logger.info("republisher gate dropped %s candidate(s)", dropped)
    return kept





def apply_prompt_injection_gate(
    scored: list[tuple],
    prompt_injection: dict[str, float],
    *,
    min_score: float = PROMPT_INJECTION_MIN,
) -> list[tuple]:
    """
    Hard exposure gate (v0.1.30). Drop when parsed prompt_injection >= min.
    Missing parse → fail-flagged (drop from results). Role/intent Jev judgment
    only — no keyword deny lists. Does not mutate raw discover order.
    """
    kept: list[tuple] = []
    dropped = 0
    for item in scored:
        c = item[0]
        pi = prompt_injection.get(c.id)
        if pi is None or pi >= min_score:
            dropped += 1
            logger.debug(
                "prompt_injection gate drop cid=%s url=%s pi=%s",
                c.id,
                getattr(c, "url", ""),
                "missing" if pi is None else f"{pi:.3f}",
            )
            continue
        kept.append(item)
    if dropped:
        logger.info("prompt_injection gate dropped %s candidate(s)", dropped)
    return kept



def restore_pre_gate_if_empty(
    scored: list[tuple],
    pre_gate: list[tuple],
    extras: dict,
) -> list[tuple]:
    """
    North-star guard (v0.1.22): if hard gates wipe the scored list, restore the
    post-compose Jev-ranked pre-gate list (scores unchanged). Never invent scores
    or fall back to raw SERP order.

    Sets extras["gates_relaxed"] = "empty_after_hard_gates" as an internal
    summary. Callers must copy that onto each restored RankedResult.gates_relaxed.
    The string is not a SearchMeta field.
    """
    if not scored and pre_gate:
        logger.warning(
            "hard gates emptied result set (%s pre-gate); restoring pre-gate ranking",
            len(pre_gate),
        )
        # Internal summary only. Public marker is RankedResult.gates_relaxed.
        extras["gates_relaxed"] = "empty_after_hard_gates"
        return list(pre_gate)
    return scored


def _signals_for(
    cid: str,
    *,
    answerability: dict[str, float],
    authority: dict[str, float],
    on_topic: dict[str, float],
    states_fact: dict[str, float],
    subject_match: dict[str, float],
    a_spam: dict[str, float],
    prompt_injection: dict[str, float] | None = None,
) -> dict[str, float] | None:
    """Optional 0–1 cascade signal breakdown for UI/API (omit missing)."""
    out: dict[str, float] = {}
    if cid in answerability:
        out["answerability"] = round(float(answerability[cid]), 4)
    if cid in authority:
        out["authority"] = round(float(authority[cid]), 4)
    if cid in on_topic:
        out["on_topic"] = round(float(on_topic[cid]), 4)
    if cid in states_fact:
        out["states_sought_fact"] = round(float(states_fact[cid]), 4)
    if cid in subject_match:
        out["subject_match"] = round(float(subject_match[cid]), 4)
    if cid in a_spam:
        out["spam"] = round(float(a_spam[cid]), 4)
    if prompt_injection and cid in prompt_injection:
        out["prompt_injection"] = round(float(prompt_injection[cid]), 4)
    return out or None


async def cascade_rank(
    client: JevClient,
    query: str,
    candidates: list[Candidate],
    *,
    k: int = 10,
    mode: str = "snip",
) -> tuple[list[RankedResult], str, dict]:
    """
    Returns (ranked_results[:k], ranking_mode, extras).
    extras may include fetch_ms / fetch_ok for deep mode.
    ranking_mode is 'jev' on success. Raises JevError if Stage A fails entirely
    with no answers — caller may fall back.
    """
    extras: dict = {}
    deep = mode == "deep"
    if not candidates:
        return [], "jev", extras

    # --- Stage A ---
    a_relevant: dict[str, float] = {}
    a_spam: dict[str, float] = {}
    stage_a_ok = False

    for i in range(0, len(candidates), STAGE_A_BATCH):
        batch = candidates[i : i + STAGE_A_BATCH]
        ids = [c.id for c in batch]
        try:
            answers = await _batch_evaluate(
                client, query, batch, build_stage_a_questions(ids)
            )
            stage_a_ok = True
            for c in batch:
                pr = parse_noul(answers, f"{c.id}__possibly_relevant")
                sp = parse_noul(answers, f"{c.id}__likely_spam")
                if pr is not None:
                    a_relevant[c.id] = pr
                if sp is not None:
                    a_spam[c.id] = sp
        except JevError as e:
            logger.warning("stage A batch failed: %s", e)
            continue

    if not stage_a_ok and not a_relevant:
        raise JevError("Jev stage A failed entirely")

    # Keep >= threshold OR top TOP_FALLBACK by noul; cap SURVIVOR_CAP
    passing = [c for c in candidates if a_relevant.get(c.id, 0.0) >= POSSIBLY_RELEVANT_MIN]
    if len(passing) < min(TOP_FALLBACK, len(candidates)):
        ordered = sorted(
            candidates,
            key=lambda c: (-a_relevant.get(c.id, 0.0), c.raw_rank),
        )
        seen = {c.id for c in passing}
        for c in ordered:
            if c.id not in seen:
                passing.append(c)
                seen.add(c.id)
            if len(passing) >= TOP_FALLBACK:
                break

    survivors = sorted(
        passing,
        key=lambda c: (-a_relevant.get(c.id, 0.0), c.raw_rank),
    )[:SURVIVOR_CAP]

    if not survivors:
        survivors = candidates[: min(SURVIVOR_CAP, len(candidates))]

    if deep:
        survivors, fetch_ok, fetch_ms = await enrich_survivors_with_bodies(survivors)
        extras["fetch_ok"] = fetch_ok
        extras["fetch_ms"] = fetch_ms
        extras["fetch_attempted"] = min(len(survivors), DEEP_FETCH_CAP)

    # --- Stage B ---
    answerability: dict[str, float] = {}
    authority: dict[str, float] = {}
    on_topic: dict[str, float] = {}
    states_fact: dict[str, float] = {}
    subject_match: dict[str, float] = {}
    is_republisher: dict[str, float] = {}
    prompt_injection: dict[str, float] = {}
    stage_b_ok = False

    for i in range(0, len(survivors), STAGE_A_BATCH):
        batch = survivors[i : i + STAGE_A_BATCH]
        ids = [c.id for c in batch]
        try:
            answers = await _batch_evaluate(
                client, query, batch, build_stage_b_questions(ids, deep=deep), deep=deep
            )
            stage_b_ok = True
            for c in batch:
                a = parse_score_01(answers, f"{c.id}__answerability")
                auth = parse_noul(answers, f"{c.id}__authority")
                ot = parse_noul(answers, f"{c.id}__on_topic")
                fact = parse_noul(answers, f"{c.id}__states_sought_fact")
                sm = parse_noul(answers, f"{c.id}__subject_match")
                rp = parse_noul(answers, f"{c.id}__is_republisher")
                pi = parse_noul(answers, f"{c.id}__prompt_injection")
                if a is not None:
                    answerability[c.id] = a
                if auth is not None:
                    authority[c.id] = auth
                if ot is not None:
                    on_topic[c.id] = ot
                if fact is not None:
                    states_fact[c.id] = fact
                if sm is not None:
                    subject_match[c.id] = sm
                if rp is not None:
                    is_republisher[c.id] = rp
                if pi is not None:
                    prompt_injection[c.id] = pi
        except JevError as e:
            logger.warning("stage B batch failed: %s", e)
            continue

    if not stage_b_ok and not answerability:
        # Partial: use stage A noul as answerability proxy
        for c in survivors:
            answerability[c.id] = a_relevant.get(c.id, 0.0)

    best_a = max((answerability.get(c.id, a_relevant.get(c.id, 0.0)) for c in survivors), default=0.0)

    scored: list[tuple[Candidate, float, list[str]]] = []
    for c in survivors:
        a = answerability.get(c.id)
        if a is None:
            a = a_relevant.get(c.id, 0.0)
        auth = authority.get(c.id)  # None if missing
        ot = on_topic.get(c.id)
        fact = states_fact.get(c.id, 0.5)

        base = compose_score(
            answerability=a,
            fact=fact,
            authority=auth,
            on_topic=ot,
            best_a=best_a,
            url=c.url,
        )
        logger.debug(
            "compose cid=%s a=%.4f auth=%s fact=%.4f base=%.4f",
            c.id,
            a,
            auth,
            fact,
            base,
        )

        flags = derive_flags(
            possibly_relevant=a_relevant.get(c.id),
            spam=a_spam.get(c.id),
            on_topic=ot,
            score=base,
        )
        if "spam_low" in flags:
            base = base * SPAM_SOFT_DEMOTE
        scored.append((c, base, flags))

    # soft near-dupe collapse
    scored = collapse_near_dupes(scored)
    scored.sort(key=sort_key)
    # Snapshot post-compose Jev ranking before hard gates (v0.1.22)
    pre_gate = list(scored)
    # Hard subject_match gate (v0.1.10) — after compose/spam/dupe, before take-k
    scored = apply_subject_match_gate(scored, subject_match)
    extras["subject_match_kept"] = len(scored)
    # Hard republisher gate (v0.1.11) — after subject_match, before take-k
    scored = apply_republisher_gate(scored, is_republisher)
    extras["republisher_kept"] = len(scored)
    # Hard prompt_injection gate (v0.1.30) — after republisher, before take-k
    scored = apply_prompt_injection_gate(scored, prompt_injection)
    extras["prompt_injection_kept"] = len(scored)
    scored = restore_pre_gate_if_empty(scored, pre_gate, extras)
    relaxed = extras.get("gates_relaxed") == "empty_after_hard_gates"
    top = scored[:k]
    results = [
        RankedResult(
            rank=i + 1,
            url=c.url,
            title=c.title,
            snippet=c.snippet,
            score=round(sc, 4),
            flags=flags,
            raw_rank=c.raw_rank,
            provider=c.provider,
            gates_relaxed=relaxed,
            signals=_signals_for(
                c.id,
                answerability=answerability,
                authority=authority,
                on_topic=on_topic,
                states_fact=states_fact,
                subject_match=subject_match,
                a_spam=a_spam,
                prompt_injection=prompt_injection,
            ),
        )
        for i, (c, sc, flags) in enumerate(top)
    ]
    return results, "jev", extras


def raw_as_ranked(candidates: list[Candidate], k: int) -> list[RankedResult]:
    out = []
    for i, c in enumerate(candidates[:k]):
        out.append(
            RankedResult(
                rank=i + 1,
                url=c.url,
                title=c.title,
                snippet=c.snippet,
                score=0.0,
                flags=[],
                raw_rank=c.raw_rank,
                provider=c.provider,
            )
        )
    return out

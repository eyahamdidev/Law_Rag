"""Deterministic checks on the final text, after the model has written it.

Prompts ask the composer to drop statements without a source, and it does so
most of the time, not every time (composer v1 and v2 both let some through).
"No fact without a source" must always hold, so it is enforced here in code.

Rule: a paragraph or bullet with no [n] marker is removed, unless it states
no fact: a heading, a question to the founder, an intro line ending with ":",
or a notice that something was not found. The unit is the whole paragraph,
not the sentence, because models often cite once at the end of a paragraph;
cutting sentence by sentence would delete supported text.
"""

import re

from app.orchestrator.verifier import _MARKER

# Wording of "I did not find it" notices, which are honest and carry no fact.
_NOT_FOUND = re.compile(
    r"could not find|couldn.t find|not found|no passage|not connected|"
    r"n'ai pas trouvé|pas trouvé|aucun passage|pas encore connecté|"
    r"لم أجد|لم يتم العثور|غير متوفر|"
    # the legal agent's notice above raw excerpts when no generated answer passed its checks
    r"evidence is shown below|passages dans leur langue originale|مقتطفات بلغتها الأصلية",
    re.IGNORECASE,
)
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")


def _states_no_fact(line: str) -> bool:
    text = _BULLET.sub("", line).strip().strip("*_").strip()
    if not text or line.lstrip().startswith("#") or set(text) <= set("-—_=*"):
        return True  # blank, heading, rule
    if line.strip().startswith("**") and line.strip().endswith("**"):
        return True  # bold label used as a heading
    if text.endswith((":", "?", "؟")):
        return True  # intro to a list, or a question to the founder
    return bool(_NOT_FOUND.search(text))


_WORD = re.compile(r"\w{3,}", re.UNICODE)
RESTORE_MIN_WORDS = 2
RESTORE_MIN_SHARE = 0.8


def _words(line: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(_MARKER.sub("", line))}


def restore_markers(text: str, sources: list[str]) -> tuple[str, int]:
    """Give back a dropped [n] to a line that restates a cited line of an agent answer.

    The composer rewrites agent answers and sometimes loses their markers
    ("La demande signée [2];" comes back as "La **demande signée** ;"), so the
    guardrail would delete sourced text. A line without a marker gets the
    markers of the cited source line that contains at least 80% of its words.
    New content matches no cited line and is still removed by drop_uncited.
    `sources` must already use the reply's citation numbers. Returns (text, restored).
    """
    cited = [(_words(line), " ".join(f"[{group}]" for group in _MARKER.findall(line)))
             for source in sources for line in source.splitlines() if _MARKER.search(line)]
    out, restored = [], 0
    for line in text.splitlines():
        words = _words(line)
        if _MARKER.search(line) or _states_no_fact(line) or len(words) < RESTORE_MIN_WORDS:
            out.append(line)
            continue
        share, markers = max(((len(words & w) / len(words), m) for w, m in cited), default=(0.0, ""))
        if share >= RESTORE_MIN_SHARE:
            stripped = line.rstrip()
            end = stripped[-1] if stripped and stripped[-1] in ".;,:" else ""
            out.append(f"{(stripped[:-1] if end else stripped).rstrip()} {markers}{end}")
            restored += 1
        else:
            out.append(line)
    return "\n".join(out), restored


def drop_uncited(text: str) -> tuple[str, list[str]]:
    """Remove factual paragraphs and bullets that cite nothing. Returns (text, removed)."""
    kept, removed = [], []
    for line in text.splitlines():
        if _MARKER.search(line) or _states_no_fact(line):
            kept.append(line)
        else:
            removed.append(line.strip())
    return _drop_empty_sections(kept), removed


def _drop_empty_sections(lines: list[str]) -> str:
    """A heading whose content was all removed would stand alone; remove it too."""
    out: list[str] = []
    for index, line in enumerate(lines):
        is_heading = line.lstrip().startswith("#") or (line.strip().startswith("**") and line.strip().endswith("**"))
        if is_heading:
            rest = lines[index + 1 :]
            nxt = next((l for l in rest if l.strip()), None)
            nxt_is_heading = nxt is not None and (
                nxt.lstrip().startswith("#") or (nxt.strip().startswith("**") and nxt.strip().endswith("**"))
            )
            if nxt is None or nxt_is_heading:
                continue
        out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()

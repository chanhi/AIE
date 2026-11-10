"""Topic state, learning logs and learner notes for AIEnglish (stdlib only).

State file  data/state/<pid>.json   (atomic write + .bak for recovery)
Log file    data/logs/<pid>/YYYY-MM.jsonl   (one line per finished topic)
Learner     data/learner.md   (auto sections regenerated from logs)
"""
from __future__ import annotations

import json
import random
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "data" / "state"
LOG_DIR = ROOT / "data" / "logs"
LEARNER_MD = ROOT / "data" / "learner.md"

HISTORY_KEEP = 50
CATEGORIES = {
    "tense": "시제",
    "article": "관사",
    "preposition": "전치사",
    "plural": "단수/복수",
    "agreement": "주어-동사 일치",
    "verb-form": "동사 형태(to부정사·동명사·원형 등)",
    "word-choice": "단어 선택",
    "collocation": "어울리는 표현(콜로케이션)",
    "word-order": "어순",
    "spelling": "철자",
    "naturalness": "자연스러운 표현",
    "korean-word": "한국어 단어 → 영어 표현",
    "other": "기타",
}
END_REASONS = ("natural", "user", "command", "newtopic", "stale")


# ---------------------------------------------------------------- test personas
def _is_test(pid: str) -> bool:
    """Personas with `test = true` never touch learner.md or the all-persona recap."""
    import tomllib
    f = ROOT / "personas" / pid / "persona.toml"
    try:
        return bool(tomllib.loads(f.read_text(encoding="utf-8")).get("test"))
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        return False


# ---------------------------------------------------------------- state
def _empty_state() -> dict:
    return {"version": 1, "last_end_at": None, "last_end_reason": None,
            "openers": [], "history": []}


def state_path(pid: str) -> Path:
    return STATE_DIR / f"{pid}.json"


def load_state(pid: str) -> dict:
    """Load state; on corruption fall back to .bak, then to a fresh IDLE state."""
    p = state_path(pid)
    for candidate in (p, p.with_suffix(".json.bak")):
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                base = _empty_state()
                base.update(data)
                if candidate != p:
                    print(f"WARN: {p.name} unreadable, recovered from backup", file=sys.stderr)
                return base
        except FileNotFoundError:
            continue
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            print(f"WARN: {candidate.name} is corrupted", file=sys.stderr)
            continue
    return _empty_state()


def save_state(pid: str, data: dict):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    p = state_path(pid)
    if p.exists():
        try:
            json.loads(p.read_text(encoding="utf-8"))  # only back up a valid file
            p.replace(p.with_suffix(".json.bak"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            pass
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)


# ---------------------------------------------------------------- summary
def _as_list(v) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def normalize_summary(raw: dict) -> dict:
    """Validate the summary JSON the bot sends; be forgiving, never crash the chat."""
    if not isinstance(raw, dict):
        raise ValueError("summary must be a JSON object")
    title = str(raw.get("title") or "").strip() or "(untitled)"
    mistakes = []
    for m in _as_list(raw.get("mistakes")):
        if isinstance(m, str):
            m = {"wrong": m}
        if not isinstance(m, dict):
            continue
        cat = str(m.get("category") or "other").strip().lower()
        mistakes.append({
            "wrong": str(m.get("wrong", "")).strip(),
            "fix": str(m.get("fix", "")).strip(),
            "why": str(m.get("why", "")).strip(),
            "category": cat if cat in CATEGORIES else "other",
        })
    return {
        "title": title,
        "good": [str(x) for x in _as_list(raw.get("good"))],
        "mistakes": mistakes,
        "new_expressions": [str(x) for x in _as_list(raw.get("new_expressions"))],
        "next": [str(x) for x in _as_list(raw.get("next"))],
        "learner_facts": [str(x).strip() for x in _as_list(raw.get("learner_facts")) if str(x).strip()],
        "turns": int(raw.get("turns") or 0),
    }


def end_topic(pid: str, reason: str, raw_summary: dict | None) -> dict:
    if reason not in END_REASONS:
        raise ValueError(f"reason must be one of {END_REASONS}")
    summary = normalize_summary(raw_summary or {})
    now = time.time()
    st = load_state(pid)
    st["last_end_at"] = now
    st["last_end_reason"] = reason
    st["history"].append({"title": summary["title"], "ended_at": now, "reason": reason})
    st["history"] = st["history"][-HISTORY_KEEP:]
    save_state(pid, st)

    entry = {"ts": now, "date": datetime.fromtimestamp(now).isoformat(timespec="seconds"),
             "persona": pid, "reason": reason, **summary}
    month_file = LOG_DIR / pid / f"{datetime.fromtimestamp(now):%Y-%m}.jsonl"
    month_file.parent.mkdir(parents=True, exist_ok=True)
    with month_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    if not _is_test(pid):
        add_facts(pid, summary["learner_facts"])
        update_learner_md()
    return entry


# ---------------------------------------------------------------- logs / recap
def iter_logs(pid: str | None = None, days: float | None = None):
    since = time.time() - days * 86400 if days else 0
    dirs = [LOG_DIR / pid] if pid else sorted(
        p for p in LOG_DIR.glob("*") if p.is_dir() and not _is_test(p.name))
    for d in dirs:
        for f in sorted(d.glob("*.jsonl")):
            for line in f.read_text(encoding="utf-8").splitlines():
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue  # skip a damaged line, keep the rest
                if e.get("ts", 0) >= since:
                    yield e


def recap(pid: str | None, days: float | None) -> dict:
    entries = list(iter_logs(pid, days))
    cats = Counter()
    examples: dict[str, dict] = {}
    for e in entries:
        for m in e.get("mistakes", []):
            cats[m["category"]] += 1
            examples[m["category"]] = m  # latest example wins
    expr = []
    for e in entries:
        expr.extend(e.get("new_expressions", []))
    return {
        "scope": pid or "all",
        "days": days,
        "topics": len(entries),
        "by_persona": dict(Counter(e["persona"] for e in entries)),
        "recent_topics": [f'{e["date"][:10]} [{e["persona"]}] {e["title"]}' for e in entries[-10:]],
        "mistake_categories": [
            {"category": c, "label": CATEGORIES[c], "count": n, "example": examples[c]}
            for c, n in cats.most_common()
        ],
        "new_expressions": list(dict.fromkeys(expr))[-20:],
        "good": [g for e in entries[-5:] for g in e.get("good", [])],
    }


# ---------------------------------------------------------------- learner.md (shared) / facts (per persona)
# Sharing policy: only LEARNING RESULTS (recurring mistakes) are shared across personas via
# data/learner.md. Personal facts learned in a conversation stay with that persona only:
# data/facts/<pid>.md. Conversation transcripts are never shared.
AUTO_BEGIN = "<!-- AUTO:BEGIN (generated by aie.py from data/logs — do not edit inside) -->"
AUTO_END = "<!-- AUTO:END -->"
FACTS_DIR = ROOT / "data" / "facts"
LEARNER_HEADER = ("# Learner notes (shared by ALL personas — learning results only)\n"
                  "<!-- Recurring-mistake patterns (auto). Personal facts live per persona in data/facts/. -->\n")


def facts_path(pid: str) -> Path:
    return FACTS_DIR / f"{pid}.md"


def read_facts(pid: str) -> list[str]:
    try:
        return [l[2:].strip() for l in facts_path(pid).read_text(encoding="utf-8").splitlines()
                if l.startswith("- ")]
    except FileNotFoundError:
        return []


def add_facts(pid: str, new_facts: list[str]) -> int:
    """Append-only, deduplicated (case-insensitive). Human-editable markdown list."""
    if not new_facts:
        return 0
    existing = {f.lower() for f in read_facts(pid)}
    add = [f for f in dict.fromkeys(new_facts) if f.lower() not in existing]
    if not add:
        return 0
    p = facts_path(pid)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text(f"# What {pid} knows about the learner (private to this persona)\n\n", encoding="utf-8")
    with p.open("a", encoding="utf-8") as f:
        f.writelines(f"- {x}\n" for x in add)
    return len(add)


def update_learner_md(new_facts: list[str] | None = None):
    """Regenerate the shared auto block. `new_facts` is ignored (facts are per persona)."""
    text = LEARNER_MD.read_text(encoding="utf-8") if LEARNER_MD.exists() else LEARNER_HEADER
    r = recap(None, None)
    lines = [AUTO_BEGIN, "## 자주 틀리는 패턴 (자동 집계)"]
    if r["mistake_categories"]:
        for c in r["mistake_categories"][:5]:
            ex = c["example"]
            lines.append(f'- {c["label"]} ({c["category"]}) ×{c["count"]} — 최근 예: "{ex["wrong"]}" → "{ex["fix"]}"')
    else:
        lines.append("- (아직 기록 없음)")
    lines.append(f"- 완료한 주제 수: {r['topics']}")
    lines.append(AUTO_END)
    auto = "\n".join(lines)
    if AUTO_BEGIN in text and AUTO_END in text:
        text = text.split(AUTO_BEGIN)[0] + auto + text.split(AUTO_END, 1)[1]
    else:
        text = text.rstrip() + "\n\n" + auto + "\n"
    LEARNER_MD.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------- suggest
def suggest_topic(pid: str, themes: list[str]) -> str:
    """Pick the least-recently-used theme (random among ties)."""
    if not themes:
        return "anything the learner might enjoy talking about"
    st = load_state(pid)
    recent = [h["title"].lower() for h in st["history"][-10:]]
    def staleness(theme: str) -> int:
        t = theme.lower()
        for i, title in enumerate(reversed(recent)):
            if any(w in title for w in t.split() if len(w) > 3):
                return i
        return 999
    best = max(staleness(t) for t in themes)
    return random.choice([t for t in themes if staleness(t) == best])

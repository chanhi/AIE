"""AIEnglish proactive-chat gate (run by a per-persona `--no-agent` cron job every tick).

Prints a request for the bot (delivered into its Bot Chat via `--deliver bot-chat`)
ONLY when it should act; prints nothing otherwise (= silent tick, no LLM call).

Decisions:
  IDLE   (no user msg / opener since last topic end)
         -> opener if: inside active window, idle >= idle_after_topic_end_h, openers today < max
  ACTIVE (user msg or opener after last topic end)
         -> learner replied & silent for stale_active_close_h -> stale-close request (bot summarizes)
         -> learner never replied to the opener for stale_active_close_h -> close silently (no message)

Usage:
  python idle_gate.py <pid> [--dry-run] [--now 2026-11-09T15:30] [--force]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import tomllib
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topics  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
GATE_LOG = ROOT / "data" / "logs" / "gate.log"
STALE_REQUEST_COOLDOWN_H = 3  # don't re-send a stale-close request more often than this
CHAT_SOURCES = ("discord",)   # messaging sources that count as learner chat (Phase 7)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def hermes_root() -> Path:
    if os.environ.get("AIE_HERMES_ROOT"):
        return Path(os.environ["AIE_HERMES_ROOT"])
    return Path(os.environ["LOCALAPPDATA"]) / "hermes"


def log(pid: str, msg: str):
    GATE_LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now().isoformat(timespec='seconds')} [{pid}] {msg}\n"
    with GATE_LOG.open("a", encoding="utf-8") as f:
        f.write(line)
    # keep the log small
    if GATE_LOG.stat().st_size > 512_000:
        lines = GATE_LOG.read_text(encoding="utf-8").splitlines()[-2000:]
        GATE_LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")


def last_user_message_at(pid: str) -> float | None:
    """Latest real learner message in the bot's conversation, read-only and short-lived.

    Counts only the canonical Desktop 'Bot Chat' (plus messaging sources in CHAT_SOURCES,
    e.g. Discord later) so test/CLI sessions don't move the timers. Scheduler injections
    (display_kind='internal_notification') are not learner messages.
    """
    db = hermes_root() / "profiles" / pid / "state.db"
    if not db.exists():
        return None
    uri = f"file:{db.as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=5)
    try:
        marks = ",".join("?" * len(CHAT_SOURCES))
        row = con.execute(
            f"""SELECT MAX(m.timestamp) FROM messages m JOIN sessions s ON s.id = m.session_id
               WHERE m.role = 'user'
                 AND COALESCE(m.display_kind, '') != 'internal_notification'
                 AND (s.title = 'Bot Chat' OR s.source IN ({marks}))""",
            CHAT_SOURCES,
        ).fetchone()
        return row[0] if row and row[0] else None
    finally:
        con.close()


def in_window(now: datetime, window: str) -> bool:
    start_s, end_s = window.split("-")
    sh, sm = map(int, start_s.split(":"))
    eh, em = map(int, end_s.split(":"))
    cur = now.hour * 60 + now.minute
    start, end = sh * 60 + sm, eh * 60 + em
    return start <= cur < end if start <= end else (cur >= start or cur < end)


def read_text(p: Path, limit: int = 1500) -> str:
    try:
        return p.read_text(encoding="utf-8")[:limit]
    except FileNotFoundError:
        return ""


def opener_request(pid: str, cfg: dict, st: dict) -> str:
    learner = json.loads(read_text(ROOT / "data" / "learner.json", 10_000) or "{}")
    name = learner.get("name", "the learner")
    theme = topics.suggest_topic(pid, cfg.get("persona", {}).get("topic_themes", []))
    recent = [h["title"] for h in st["history"][-8:]]
    notes = read_text(ROOT / "data" / "learner.md")          # shared: learning results only
    facts = topics.read_facts(pid)                             # private to this persona
    return "\n".join([
        "[AIEnglish opener request]",
        f"Start a NEW topic with {name} as {cfg['display_name']}, in character.",
        f"- Suggested theme: {theme} — turn it into a specific, personal question "
        f"(use what you remember about {name}; mention something from your own life too).",
        f"- Avoid repeating recent topics: {', '.join(recent) if recent else '(none yet)'}",
        "- If natural, create a chance for the learner to practice one of their recurring mistakes below.",
        f"- Call them by name. 1–2 short sentences at {cfg['level']} level, end with a question. English only.",
        f"- Output format exactly: 💬 {cfg['display_name']}: <message>   (no Tutor section, no other text)",
        "",
        f"What YOU ({cfg['display_name']}) know about {name} from your own past chats (only use these personal facts):",
        "\n".join(f"- {f}" for f in facts[-15:]) or "(nothing yet — ask about them)",
        "",
        "Learner's recurring mistakes (shared learning results):",
        notes.strip() or "(none)",
    ])


def stale_request(cfg: dict, hours: float) -> str:
    return "\n".join([
        "[AIEnglish stale-close request]",
        f"The learner hasn't replied for {hours:g}+ hours, so close the current topic now.",
        "Follow 'Ending a topic' in the english-chat-core skill with reason `stale`.",
        f"Farewell line: light and friendly as {cfg['display_name']}, e.g. 'Let's catch up later!' — "
        "don't guilt-trip the learner.",
    ])


def decide(pid: str, now_dt: datetime, force: bool = False) -> tuple[str, str | None, dict]:
    """Return (decision, message_or_None, new_state)."""
    cfg = tomllib.loads((ROOT / "personas" / pid / "persona.toml").read_text(encoding="utf-8"))
    sch = cfg.get("schedule", {})
    st = topics.load_state(pid)
    now = now_dt.timestamp()
    if not sch.get("enabled") and not force:
        return "disabled", None, st

    last_user = last_user_message_at(pid) or 0
    openers = [t for t in st.get("openers", []) if now - t < 7 * 86400]
    last_opener = max(openers, default=0)
    last_end = st.get("last_end_at") or 0
    last_activity = max(last_user, last_opener)
    active = last_activity > last_end
    window_ok = in_window(now_dt, sch.get("active_window", "08:00-18:00"))
    stale_h = float(sch.get("stale_active_close_h", 24))
    idle_h = float(sch.get("idle_after_topic_end_h", 3))
    max_per_day = int(sch.get("max_openers_per_day", 2))

    if active:
        if now - last_activity < stale_h * 3600:
            return "active", None, st
        if last_user <= last_opener:
            # learner ignored the opener -> nothing to summarize; close quietly
            st["last_end_at"] = now
            st["last_end_reason"] = "stale-no-reply"
            return "closed-silently(no reply to opener)", None, st
        if not window_ok and not force:
            return "stale-but-outside-window", None, st
        if now - (st.get("stale_requested_at") or 0) < STALE_REQUEST_COOLDOWN_H * 3600:
            return "stale-request-pending", None, st
        st["stale_requested_at"] = now
        return "stale-close-request", stale_request(cfg, stale_h), st

    # IDLE
    if not window_ok and not force:
        return "outside-window", None, st
    since = max(last_end, last_user)
    if since and now - since < idle_h * 3600 and not force:
        return f"idle-too-short({(now - since) / 3600:.1f}h<{idle_h:g}h)", None, st
    today = now_dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    sent_today = sum(1 for t in openers if t >= today)
    if sent_today >= max_per_day and not force:
        return f"daily-limit({sent_today}/{max_per_day})", None, st
    openers.append(now)
    st["openers"] = openers
    return "opener", opener_request(pid, cfg, st), st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pid")
    ap.add_argument("--dry-run", action="store_true", help="print decision, don't save state")
    ap.add_argument("--now", help="override current local time (ISO), for testing")
    ap.add_argument("--force", action="store_true", help="ignore window/idle/limit (testing)")
    a = ap.parse_args()
    now_dt = datetime.fromisoformat(a.now) if a.now else datetime.now()
    try:
        decision, msg, st = decide(a.pid, now_dt, a.force)
    except Exception as e:  # never spam the chat with a traceback; log and stay silent
        log(a.pid, f"ERROR {type(e).__name__}: {e}")
        if a.dry_run:
            raise
        return
    if a.dry_run:
        print(f"[dry-run] decision={decision}")
        if msg:
            print(msg)
        return
    if decision not in ("active", "outside-window", "disabled", "stale-request-pending") \
            and not decision.startswith(("idle-too-short", "daily-limit", "stale-but")):
        topics.save_state(a.pid, st)
    log(a.pid, f"decision={decision}")
    if msg:
        print(msg)


if __name__ == "__main__":
    main()

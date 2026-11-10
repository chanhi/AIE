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
                 AND m.content NOT LIKE '[Cron delivery:%'
                 AND (s.title = 'Bot Chat' OR s.source IN ({marks}))""",
            CHAT_SOURCES,
        ).fetchone()
        return row[0] if row and row[0] else None
    finally:
        con.close()


def _ro(pid: str):
    db = hermes_root() / "profiles" / pid / "state.db"
    if not db.exists():
        return None
    return sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=5)


def discord_dm_chat_id(pid: str) -> str | None:
    """Chat id of the learner's most recent Discord DM with this persona's bot (None if never DMed)."""
    con = _ro(pid)
    if con is None:
        return None
    try:
        row = con.execute("""SELECT chat_id FROM sessions WHERE source = 'discord' AND chat_type = 'dm'
                             AND chat_id IS NOT NULL ORDER BY COALESCE(last_activity_at, started_at) DESC
                             LIMIT 1""").fetchone()
        return str(row[0]) if row else None
    finally:
        con.close()


def recent_dm_messages(pid: str, since: float = 0, limit: int = 12) -> list[str]:
    """Readable recent turns of the Discord DM (oldest first), skipping tool/system noise."""
    con = _ro(pid)
    if con is None:
        return []
    try:
        rows = con.execute(
            """SELECT m.role, m.content FROM messages m JOIN sessions s ON s.id = m.session_id
               WHERE s.source = 'discord' AND s.chat_type = 'dm' AND m.role IN ('user','assistant')
                 AND m.timestamp > ? AND COALESCE(m.content,'') != ''
               ORDER BY m.timestamp DESC LIMIT ?""", (since, limit)).fetchall()
    finally:
        con.close()
    out = []
    for role, content in reversed(rows):
        text = content.strip()
        if text.startswith("[IMPORTANT: The user has invoked"):
            continue  # slash-command skill bodies
        if text.startswith("[Cron delivery:"):
            role, text = "assistant", text.split("\n", 1)[-1]
        who = "Learner" if role == "user" else "You"
        out.append(f"{who}: {text[:400]}")
    return out


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


def discord_opener_request(pid: str, cfg: dict, st: dict) -> str:
    recent = recent_dm_messages(pid, limit=8)
    return "\n".join([
        opener_request(pid, cfg, st),
        "",
        "Recent messages in your Discord chat with the learner (for continuity; don't repeat them):",
        "\n".join(recent) or "(none)",
        "",
        "You are running as a scheduled job: no tools are needed. Your final answer is sent to the learner "
        "as-is. It must be exactly ONE line starting with '💬 " + cfg["display_name"] + ":' — NO 📘 Tutor "
        "section, no expression tips, nothing after that line. (The Tutor only comments on learner messages.)",
    ])


def discord_stale_request(pid: str, cfg: dict, hours: float, since: float) -> str:
    convo = recent_dm_messages(pid, since=since, limit=30)
    name = cfg["display_name"]
    return "\n".join([
        "[AIEnglish stale-close request]",
        f"The learner hasn't replied for {hours:g}+ hours, so the current topic is being closed now.",
        "You are running as a scheduled job: do NOT use tools and do NOT run any command — just write the message.",
        "Output exactly this shape (persona line in English, Tutor part in Korean), nothing else:",
        f"💬 {name}: <one light, friendly farewell for this topic — no guilt-tripping>",
        "---",
        "📘 Tutor: 📝 이번 주제 정리",
        "- 잘한 표현: ...",
        "- 자주 틀린 점: ... (최대 3개, 각 1줄; 없으면 '없음')",
        "- 새로 배운 표현: ...",
        "- 다음에 연습할 것: ...",
        "",
        "The topic's conversation (Learner = the learner, You = you):",
        "\n".join(convo) or "(no messages found)",
    ])


def stale_request(cfg: dict, hours: float) -> str:
    return "\n".join([
        "[AIEnglish stale-close request]",
        f"The learner hasn't replied for {hours:g}+ hours, so close the current topic now.",
        "Follow 'Ending a topic' in the english-chat-core skill with reason `stale`.",
        f"Farewell line: light and friendly as {cfg['display_name']}, e.g. 'Let's catch up later!' — "
        "don't guilt-trip the learner.",
    ])


def decide(pid: str, now_dt: datetime, force: bool = False,
           mode: str = "botchat") -> tuple[str, str | None, dict]:
    """Return (decision, message_or_None, new_state). mode: botchat (Desktop) | agent (Discord job)."""
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
        if mode == "agent":
            return "stale-close-request", discord_stale_request(pid, cfg, stale_h, last_end), st
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
    if mode == "agent":
        return "opener", discord_opener_request(pid, cfg, st), st
    return "opener", opener_request(pid, cfg, st), st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pid")
    ap.add_argument("--dry-run", action="store_true", help="print decision, don't save state")
    ap.add_argument("--now", help="override current local time (ISO), for testing")
    ap.add_argument("--force", action="store_true", help="ignore window/idle/limit (testing)")
    ap.add_argument("--mode", choices=("botchat", "agent"), default="botchat",
                    help="botchat: print request for --deliver bot-chat (no-agent job); "
                         "agent: gate an agent job (Discord) — prints request or {\"wakeAgent\": false}")
    a = ap.parse_args()
    skip = '{"wakeAgent": false}' if a.mode == "agent" else ""
    now_dt = datetime.fromisoformat(a.now) if a.now else datetime.now()
    try:
        decision, msg, st = decide(a.pid, now_dt, a.force, a.mode)
    except Exception as e:  # never spam the chat with a traceback; log and stay silent
        log(a.pid, f"ERROR {type(e).__name__}: {e}")
        if a.dry_run:
            raise
        if skip:
            print(skip)
        return
    if a.dry_run:
        print(f"[dry-run] decision={decision}")
        if msg:
            print(msg)
        return
    if decision not in ("active", "outside-window", "disabled", "stale-request-pending") \
            and not decision.startswith(("idle-too-short", "daily-limit", "stale-but")):
        topics.save_state(a.pid, st)
        if a.mode == "agent" and decision == "stale-close-request":
            # the scheduled agent can't run aie.py (no tools in cron), so record the end here
            topics.end_topic(a.pid, "stale", {"title": "(auto-closed after inactivity)"})
    log(a.pid, f"decision={decision} mode={a.mode}")
    if msg:
        print(msg)
    elif skip:
        print(skip)


if __name__ == "__main__":
    main()

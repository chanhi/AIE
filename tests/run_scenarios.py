"""Run AIEnglish chat regression scenarios against the test bot (persona `qatest`).

Usage:
  python tests/run_scenarios.py                    # all scenarios in tests/scenarios/core.json
  python tests/run_scenarios.py --only qa-empty,stall
  python tests/run_scenarios.py --workers 4 --keep-data

Each scenario runs in its own fresh CLI session (never the Bot Chat, so proactive timers
are untouched). Reports go to tests/reports/<timestamp>.md/.json. Test-bot state/logs are
wiped before stateful scenarios and at the end (unless --keep-data).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "tests" / "reports"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERMES = shutil.which("hermes") or "hermes"
TURN_TIMEOUT = 280


def wipe_test_data(pid: str):
    for p in (ROOT / "data" / "state").glob(f"{pid}.json*"):
        p.unlink(missing_ok=True)
    shutil.rmtree(ROOT / "data" / "logs" / pid, ignore_errors=True)
    (ROOT / "data" / "tmp" / f"{pid}.json").unlink(missing_ok=True)


def clean_reply(stdout: str) -> str:
    text = stdout.split("────")[0].replace("☤ Hermes", "")
    # drop tool-call preview lines the CLI prints (e.g. file diff boxes)
    lines = [l for l in text.splitlines() if not l.lstrip().startswith("│")]
    return "\n".join(lines).strip()


def say(pid: str, session: str, msg: str) -> tuple[int, str, str]:
    for attempt in (1, 2):  # one retry for transient provider/gateway errors
        r = subprocess.run(
            [HERMES, "-p", pid, "chat", "-c", session, "--create-if-missing", "-Q", "-q", msg],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=TURN_TIMEOUT)
        reply = clean_reply(r.stdout)
        if r.returncode == 0 and reply:
            return r.returncode, reply, ""
        if attempt == 1:
            time.sleep(5)
    return r.returncode, reply, (r.stderr or "")[-500:]


def check(reply: str, turn: dict) -> list[str]:
    fails = []
    for pat in turn.get("must", []):
        if not re.search(pat, reply, re.M):
            fails.append(f"missing /{pat}/")
    for pat in turn.get("must_not", []):
        if re.search(pat, reply, re.M):
            fails.append(f"unexpected /{pat}/")
    return fails


def run_scenario(pid: str, sc: dict, run_id: str) -> dict:
    if sc.get("reset_state"):
        wipe_test_data(pid)
    session = f"scn-{sc['id']}-{run_id}"
    turns, ok, t0 = [], True, time.time()
    for turn in sc["turns"]:
        t = time.time()
        rc, reply, err = say(pid, session, turn["say"])
        fails = check(reply, turn) if rc == 0 else [f"hermes exit {rc}: {err}"]
        ok &= not fails
        turns.append({"say": turn["say"], "reply": reply, "fails": fails, "sec": round(time.time() - t)})
    post = sc.get("post", {})
    if "state_reason" in post:
        try:
            st = json.loads((ROOT / "data" / "state" / f"{pid}.json").read_text(encoding="utf-8"))
            got = st.get("last_end_reason")
        except FileNotFoundError:
            got = None
        if got != post["state_reason"]:
            ok = False
            turns[-1]["fails"].append(f"state last_end_reason={got!r}, expected {post['state_reason']!r}")
    res = {"id": sc["id"], "desc": sc.get("desc", ""), "ok": ok, "turns": turns,
           "sec": round(time.time() - t0)}
    print(f"{'PASS' if ok else 'FAIL'}  {sc['id']:28} {res['sec']:>4}s  {sc.get('desc', '')}", flush=True)
    return res


def write_report(results: list[dict], meta: dict) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (REPORTS / f"{stamp}.json").write_text(json.dumps({"meta": meta, "results": results},
                                                      ensure_ascii=False, indent=1), encoding="utf-8")
    passed = sum(r["ok"] for r in results)
    md = [f"# Scenario report {stamp}", "",
          f"- persona: `{meta['persona']}`, scenarios: {len(results)}, **pass {passed} / fail {len(results) - passed}**",
          f"- duration: {meta['duration_sec']}s", "",
          "| 결과 | id | 설명 | 실패 사유 |", "|---|---|---|---|"]
    for r in results:
        reasons = "; ".join(f for t in r["turns"] for f in t["fails"]).replace("|", "\\|")
        md.append(f"| {'✅' if r['ok'] else '❌'} | `{r['id']}` | {r['desc']} | {reasons} |")
    md += ["", "## Transcripts", ""]
    for r in results:
        md.append(f"### {'✅' if r['ok'] else '❌'} {r['id']} — {r['desc']}")
        for t in r["turns"]:
            md.append(f"**USER:** {t['say']}\n\n```\n{t['reply']}\n```")
            if t["fails"]:
                md.append(f"> ⚠ {'; '.join(t['fails'])}")
        md.append("")
    out = REPORTS / f"{stamp}.md"
    out.write_text("\n".join(md), encoding="utf-8")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=str(ROOT / "tests" / "scenarios" / "core.json"))
    ap.add_argument("--only", help="comma-separated scenario ids")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--keep-data", action="store_true")
    a = ap.parse_args()

    spec = json.loads(Path(a.file).read_text(encoding="utf-8"))
    pid = spec["persona"]
    scs = spec["scenarios"]
    if a.only:
        wanted = set(a.only.split(","))
        scs = [s for s in scs if s["id"] in wanted]
    run_id = uuid.uuid4().hex[:6]
    t0 = time.time()
    parallel = [s for s in scs if not s.get("serial")]
    serial = [s for s in scs if s.get("serial")]
    with ThreadPoolExecutor(max(1, a.workers)) as ex:
        results = list(ex.map(lambda s: run_scenario(pid, s, run_id), parallel))
    for s in serial:
        results.append(run_scenario(pid, s, run_id))
    if not a.keep_data:
        wipe_test_data(pid)
    meta = {"persona": pid, "run_id": run_id, "duration_sec": round(time.time() - t0)}
    out = write_report(results, meta)
    passed = sum(r["ok"] for r in results)
    print(f"\n{passed}/{len(results)} passed — report: {out}")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()

"""AIEnglish management CLI (Python stdlib only).

Usage:
  python scripts/aie.py persona list
  python scripts/aie.py persona init-soul <id> [--force]   # template -> personas/<id>/SOUL.md
  python scripts/aie.py persona deploy <id>|--all [--dry-run]
  python scripts/aie.py persona create --spec <file.json> [--smoke] [--dry-run]
  python scripts/aie.py persona remove <id> --yes [--purge]
  python scripts/aie.py providers
  python scripts/aie.py learner show
  python scripts/aie.py learner set <key> <value>           # e.g. learner set name Chanhuy
  python scripts/aie.py topic end <pid> --reason natural|user|command|newtopic|stale  < summary.json
  python scripts/aie.py topic status <pid>
  python scripts/aie.py topic suggest <pid>
  python scripts/aie.py recap [<pid>|--all] [--days N]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topics  # noqa: E402
import persona_spec  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PERSONAS = ROOT / "personas"
TEMPLATES = ROOT / "templates"
SKILLS_DIR = ROOT / "skills"
LEARNER_JSON = ROOT / "data" / "learner.json"
LEARNER_EXAMPLE = ROOT / "data" / "learner.example.json"
LOCAL_TOML = ROOT / "local.toml"   # per-PC overrides, git-ignored (see local.example.toml)

# Shared skills auto-loaded into every session of a profile, by relation.
AUTO_LOAD = {
    "tutor": [],
    "_default": ["english-chat-core"],
}
# Placeholders filled at deploy time (learner may change later).
LEARNER_KEYS = ("learner_name",)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# ---------------------------------------------------------------- helpers
def hermes_root() -> Path:
    if os.environ.get("AIE_HERMES_ROOT"):
        return Path(os.environ["AIE_HERMES_ROOT"])
    return Path(os.environ["LOCALAPPDATA"]) / "hermes"


def profile_dir(pid: str) -> Path:
    return hermes_root() / "profiles" / pid


def die(msg: str, code: int = 1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def load_persona(pid: str) -> dict:
    f = PERSONAS / pid / "persona.toml"
    if not f.exists():
        die(f"persona config not found: {f}")
    try:
        cfg = tomllib.loads(f.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        die(f"invalid TOML in {f}: {e}")
    if cfg.get("id") != pid:
        die(f"{f}: id '{cfg.get('id')}' does not match folder '{pid}'")
    if not re.fullmatch(r"[a-z0-9]+", pid):
        die(f"persona id must be lowercase alphanumeric (Hermes profile rule): {pid}")
    for key in ("display_name", "relation", "level", "template"):
        if key not in cfg:
            die(f"{f}: missing required key '{key}'")
    return cfg


def local_settings() -> dict:
    """Per-PC overrides (not in git). e.g. [routines] enabled = false on a dev-only PC."""
    try:
        return tomllib.loads(LOCAL_TOML.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except tomllib.TOMLDecodeError as e:
        die(f"invalid local.toml: {e}")


def routines_allowed_here() -> bool:
    return bool(local_settings().get("routines", {}).get("enabled", True))


def load_learner() -> dict:
    if not LEARNER_JSON.exists() and LEARNER_EXAMPLE.exists():
        shutil.copyfile(LEARNER_EXAMPLE, LEARNER_JSON)  # first run on a fresh clone
        print(f"NOTE: created {LEARNER_JSON.name} from example — set your name: aie.py learner set name <Name>",
              file=sys.stderr)
    try:
        return json.loads(LEARNER_JSON.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"name": "Learner", "native_language": "Korean", "default_level": "B1"}


def save_learner(data: dict):
    LEARNER_JSON.parent.mkdir(parents=True, exist_ok=True)
    tmp = LEARNER_JSON.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(LEARNER_JSON)


def all_persona_ids() -> list[str]:
    return sorted(p.parent.name for p in PERSONAS.glob("*/persona.toml"))


def hermes(*args: str, dry: bool = False, check: bool = True) -> subprocess.CompletedProcess | None:
    exe = shutil.which("hermes")
    if not exe:
        die("'hermes' command not found on PATH")
    cmd = [exe, *args]
    if dry:
        print("  [dry-run]", " ".join(args))
        return None
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        die(f"hermes {' '.join(args)} failed ({r.returncode}):\n{r.stdout}\n{r.stderr}")
    return r


# ---------------------------------------------------------------- SOUL
def _fmt(v) -> str:
    return ", ".join(map(str, v)) if isinstance(v, list) else str(v)


def init_soul(pid: str, force: bool = False) -> Path:
    cfg = load_persona(pid)
    out = PERSONAS / pid / "SOUL.md"
    if out.exists() and not force:
        return out
    tpl = TEMPLATES / f"SOUL.{cfg['template']}.md"
    if not tpl.exists():
        die(f"template not found: {tpl}")
    values = {k: _fmt(v) for k, v in cfg.get("persona", {}).items()}
    values.update({k: _fmt(cfg[k]) for k in ("id", "display_name", "relation", "level")})
    text = tpl.read_text(encoding="utf-8")

    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key in LEARNER_KEYS:
            return m.group(0)  # keep for deploy time
        if key not in values:
            die(f"template {tpl.name} needs '{key}' but persona '{pid}' does not define it")
        return values[key]

    out.write_text(re.sub(r"\{(\w+)\}", sub, text), encoding="utf-8")
    print(f"  SOUL source written: {out.relative_to(ROOT)}")
    return out


def render_soul_for_profile(pid: str) -> str:
    src = init_soul(pid)
    learner = load_learner()
    text = src.read_text(encoding="utf-8")
    return text.replace("{learner_name}", learner.get("name", "Learner"))


def write_profile_soul(pid: str, dry: bool = False):
    text = render_soul_for_profile(pid)
    dst = profile_dir(pid) / "SOUL.md"
    if dry:
        print(f"  [dry-run] write {dst}")
        return
    dst.write_text(text, encoding="utf-8")
    print(f"  SOUL.md -> {dst}")


# ---------------------------------------------------------------- profile.yaml
def set_display_name(pid: str, name: str, dry: bool = False):
    f = profile_dir(pid) / "profile.yaml"
    if dry:
        print(f"  [dry-run] display_name: {name} -> {f}")
        return
    lines = f.read_text(encoding="utf-8").splitlines() if f.exists() else []
    new = f"display_name: {json.dumps(name, ensure_ascii=False)}"
    for i, line in enumerate(lines):
        if line.startswith("display_name:"):
            lines[i] = new
            break
    else:
        lines.append(new)
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  display_name = {name}")


# ---------------------------------------------------------------- deploy
def deploy(pid: str, dry: bool = False):
    cfg = load_persona(pid)
    print(f"== deploy {pid} ({cfg['display_name']}, {cfg['relation']}, {cfg['level']})")
    pdir = profile_dir(pid)
    if not pdir.exists():
        hermes("profile", "create", pid, "--no-skills", "--no-alias",
               "--description", cfg.get("description", cfg["display_name"]), dry=dry)
        print("  profile created")
    else:
        hermes("profile", "describe", pid, "--text", cfg.get("description", cfg["display_name"]),
               "--overwrite", dry=dry, check=False)
        print("  profile exists (updated)")

    model = cfg.get("model", {})
    mem = cfg.get("memory", {}).get("enabled", True)
    auto = AUTO_LOAD.get(cfg["relation"], AUTO_LOAD["_default"])
    settings = [
        ("skills.external_dirs", json.dumps([SKILLS_DIR.as_posix()], ensure_ascii=False)),
        ("skills.auto_load", json.dumps(auto)),
        ("memory.memory_enabled", str(mem).lower()),
        ("memory.user_profile_enabled", str(mem).lower()),
    ]
    if model.get("provider"):
        settings.append(("model.provider", model["provider"]))
    if model.get("model"):
        settings.append(("model.default", model["model"]))
    for key, val in settings:
        hermes("-p", pid, "config", "set", key, val, dry=dry)
        print(f"  {key} = {val}")

    write_profile_soul(pid, dry)
    set_display_name(pid, cfg["display_name"], dry)
    sync_routine(pid, cfg, dry)
    print(f"== {pid} done")


# ---------------------------------------------------------------- proactive routine (cron)
GATE_SCRIPT = ROOT / "scripts" / "idle_gate.py"
WRAPPER_NAME = "aienglish_gate.py"


def routine_name(pid: str) -> str:
    # Bot Mode lists cron jobs named "[bot:<profile>] ..." in the Bot's Routines pane.
    return f"[bot:{pid}] AIEnglish proactive chat"


def find_jobs(pid: str, name: str) -> list[str]:
    r = hermes("-p", pid, "cron", "list", "--all", check=False)
    ids, current = [], None
    for line in (r.stdout if r else "").splitlines():
        m = re.match(r"^\s*([0-9a-f]{12})\b", line)
        if m:
            current = m.group(1)
        elif current and line.strip().startswith("Name:") and line.split("Name:", 1)[1].strip() == name:
            ids.append(current)
    return ids


def sync_routine(pid: str, cfg: dict, dry: bool = False):
    """(Re)create the per-persona gate job so it always matches persona.toml."""
    sch = cfg.get("schedule", {})
    name = routine_name(pid)
    for job_id in ([] if dry else find_jobs(pid, name)):
        hermes("-p", pid, "cron", "remove", job_id, check=False)
        print(f"  routine removed: {job_id}")
    if not sch.get("enabled"):
        print("  routine: disabled (schedule.enabled = false)")
        return
    if not routines_allowed_here():
        print("  routine: skipped on this PC (local.toml [routines] enabled = false)")
        return
    channel = str(sch.get("proactive_channel", "desktop"))
    chat_id = None
    if channel == "discord":
        sys.path.insert(0, str(ROOT / "scripts"))
        import idle_gate
        chat_id = idle_gate.discord_dm_chat_id(pid)
        if not chat_id:
            print("  WARN: proactive_channel=discord but no Discord DM with this bot yet — "
                  "DM the bot once, then re-run deploy. Using Desktop Bot Chat for now.")
            channel = "desktop"
    mode = "agent" if channel == "discord" else "botchat"
    wrapper = profile_dir(pid) / "scripts" / WRAPPER_NAME
    code = (
        "# Generated by AIEnglish aie.py - do not edit. Delegates to the project gate script.\n"
        "import runpy, sys\n"
        f"sys.argv = [{str(GATE_SCRIPT)!r}, {pid!r}, '--mode', {mode!r}]\n"
        f"runpy.run_path({str(GATE_SCRIPT)!r}, run_name='__main__')\n"
    )
    if dry:
        print(f"  [dry-run] write {wrapper}")
    else:
        wrapper.parent.mkdir(parents=True, exist_ok=True)
        wrapper.write_text(code, encoding="utf-8")
    tick = str(sch.get("tick", "30m"))
    summary = (f"(window {sch.get('active_window')}, idle {sch.get('idle_after_topic_end_h')}h, "
               f"max {sch.get('max_openers_per_day')}/day, stale {sch.get('stale_active_close_h')}h)")
    if channel != "discord":
        hermes("-p", pid, "cron", "create", f"every {tick}", "--name", name, "--no-agent",
               "--script", WRAPPER_NAME, "--deliver", "bot-chat", "--failure-deliver", "local", dry=dry)
        print(f"  routine: every {tick} -> Desktop Bot Chat {summary}")
        return
    # Discord: agent job gated by the script ({"wakeAgent": false} = skip), delivered into the DM
    # and mirrored into the DM session (attach_to_session) so the bot remembers its own opener.
    r = hermes("-p", pid, "cron", "create", f"every {tick}", DISCORD_JOB_PROMPT, "--name", name,
               "--script", WRAPPER_NAME, "--deliver", f"discord:{chat_id}", "--failure-deliver", "local",
               "--paused", dry=dry)
    if dry:
        print(f"  routine: every {tick} -> Discord DM {chat_id} {summary}")
        return
    job_id = (re.findall(r"\b[0-9a-f]{12}\b", r.stdout) or [None])[0]
    if not job_id or not set_job_fields(pid, job_id, {"attach_to_session": True, "enabled_toolsets": []}):
        die(f"could not configure Discord routine for {pid} (job {job_id}); it stays paused")
    hermes("-p", pid, "cron", "resume", job_id)
    print(f"  routine: every {tick} -> Discord DM {chat_id} (continuable, no tools) {summary}")


DISCORD_JOB_PROMPT = (
    "The script output above contains an [AIEnglish ...] request from the AIEnglish scheduler. "
    "Follow it exactly, staying in character. Do not use tools. Your final answer is delivered to "
    "the learner verbatim. For an opener request your ENTIRE answer is the single '💬 <Name>: ...' "
    "line — no Tutor section, no tips, no translation, nothing after it. For a stale-close request "
    "output exactly the shape it gives."
)


def hermes_install_dir() -> Path | None:
    r = hermes("--version", check=False)
    m = re.search(r"Install directory:\s*(.+)", r.stdout if r else "")
    return Path(m.group(1).strip()) if m else None


def set_job_fields(pid: str, job_id: str, fields: dict) -> bool:
    """Set cron job fields the CLI doesn't expose (attach_to_session, enabled_toolsets)
    through Hermes' own cron.jobs.update_job, run against this persona's profile."""
    inst = hermes_install_dir()
    if not inst:
        print("  WARN: Hermes install directory not found")
        return False
    code = ("import sys, json; sys.path.insert(0, sys.argv[1]); from cron.jobs import update_job; "
            "j = update_job(sys.argv[2], json.loads(sys.argv[3])); "
            "print(json.dumps({k: (j or {}).get(k) for k in json.loads(sys.argv[3])}))")
    env = {**os.environ, "HERMES_HOME": str(profile_dir(pid))}
    r = subprocess.run([sys.executable, "-c", code, str(inst), job_id, json.dumps(fields)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    if r.returncode != 0:
        print(f"  WARN: update_job failed: {r.stderr[-400:]}")
        return False
    got = json.loads(r.stdout.strip().splitlines()[-1])
    return all(got.get(k) == v for k, v in fields.items())


# ---------------------------------------------------------------- CLI
def main():
    """CLI entry point."""
    return _main()


# ---------------------------------------------------------------- create / remove
PROTECTED_IDS = {"tutor", "qatest"}


def logged_in_providers() -> set[str]:
    r = hermes("auth", "list", check=False)
    return {m.group(1) for m in re.finditer(r"^([a-z0-9][a-z0-9_-]*) \(\d+ credentials?\):",
                                            r.stdout if r else "", re.M)}


def existing_profiles() -> set[str]:
    d = hermes_root() / "profiles"
    return {p.name for p in d.iterdir() if p.is_dir()} if d.exists() else set()


def smoke_test(pid: str, name: str) -> bool:
    r = hermes("-p", pid, "chat", "-c", "aie-smoke-test", "--create-if-missing", "-Q", "-q",
               "Hi! Nice to meet you. I am happy to talk with you.", check=False)
    out = (r.stdout if r else "")
    ok = r is not None and r.returncode == 0 and f"💬 {name}:" in out
    print(f"  smoke test: {'OK' if ok else 'FAILED'}")
    if not ok:
        print("  --- smoke output ---\n" + out[-800:] + (r.stderr[-400:] if r else ""))
    return ok


def create_persona(spec_file: str, smoke: bool, dry: bool) -> int:
    p = Path(spec_file)
    try:
        spec = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        die(f"spec file not found: {p}")
    except json.JSONDecodeError as e:
        die(f"spec JSON 형식 오류: {e}")
    cfg, errs = persona_spec.validate(spec, set(all_persona_ids()), existing_profiles(),
                                      logged_in_providers())
    if errs:
        print("VALIDATION FAILED")
        for e in errs:
            print(f"  - {e}")
        return 2
    pid = cfg["id"]
    toml_text = persona_spec.to_toml(cfg)
    if dry:
        print(f"[dry-run] would create personas/{pid}/persona.toml:\n{toml_text}")
        return 0
    pdir = PERSONAS / pid
    pdir.mkdir(parents=True, exist_ok=False)
    (pdir / "persona.toml").write_text(toml_text, encoding="utf-8")
    try:
        load_persona(pid)  # round-trip check: what we wrote must parse back
        init_soul(pid, force=True)
        deploy(pid)
    except SystemExit:
        print(f"ERROR: deploy failed — rolling back '{pid}'")
        remove_persona(pid, purge=True)
        return 1
    if p.parent == ROOT / "data" / "tmp":
        p.unlink(missing_ok=True)
    if smoke and not smoke_test(pid, cfg["display_name"]):
        print("WARN: created, but the smoke test failed (check the model/provider).")
        return 3
    print(f"OK persona created: {pid} ({cfg['display_name']}, {cfg['relation']}, {cfg['level']})")
    return 0


def remove_persona(pid: str, purge: bool = False):
    if not re.fullmatch(r"[a-z0-9]+", pid):
        die(f"invalid id: {pid}")
    print(f"== remove {pid}")
    if profile_dir(pid).exists():
        for job_id in find_jobs(pid, routine_name(pid)):
            hermes("-p", pid, "cron", "remove", job_id, check=False)
            print(f"  routine removed: {job_id}")
        r = hermes("profile", "delete", pid, "-y", check=False)
        print(f"  profile delete: {'OK' if r and r.returncode == 0 else 'FAILED'}")
        if r and r.returncode != 0:
            print((r.stdout + r.stderr)[-600:])
    src = PERSONAS / pid
    if src.exists():
        if purge:
            shutil.rmtree(src)
            print(f"  personas/{pid} deleted")
        else:
            dst = PERSONAS / "_removed" / f"{pid}-{datetime.now():%Y%m%d-%H%M%S}"
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)
            print(f"  personas/{pid} archived -> {dst.relative_to(ROOT)}")
    if purge:
        for f in (ROOT / "data" / "state").glob(f"{pid}.json*"):
            f.unlink()
        shutil.rmtree(ROOT / "data" / "logs" / pid, ignore_errors=True)
        (ROOT / "data" / "facts" / f"{pid}.md").unlink(missing_ok=True)
        (ROOT / "data" / "tmp" / f"{pid}.json").unlink(missing_ok=True)
        topics.update_learner_md()  # drop its mistakes from the auto block
        print("  state/logs purged")


def _main():
    ap = argparse.ArgumentParser(prog="aie")
    sub = ap.add_subparsers(dest="group", required=True)

    p = sub.add_parser("persona")
    psub = p.add_subparsers(dest="cmd", required=True)
    psub.add_parser("list")
    pi = psub.add_parser("init-soul"); pi.add_argument("id"); pi.add_argument("--force", action="store_true")
    pd = psub.add_parser("deploy"); pd.add_argument("id", nargs="?"); pd.add_argument("--all", action="store_true")
    pd.add_argument("--dry-run", action="store_true")
    pc = psub.add_parser("create"); pc.add_argument("--spec", required=True)
    pc.add_argument("--smoke", action="store_true"); pc.add_argument("--dry-run", action="store_true")
    pr = psub.add_parser("remove"); pr.add_argument("id"); pr.add_argument("--yes", action="store_true")
    pr.add_argument("--purge", action="store_true", help="also delete persona folder, state and logs")
    pr.add_argument("--force", action="store_true", help="allow removing protected ids")
    sub.add_parser("providers")

    l = sub.add_parser("learner")
    lsub = l.add_subparsers(dest="cmd", required=True)
    lsub.add_parser("show")
    ls_ = lsub.add_parser("set"); ls_.add_argument("key"); ls_.add_argument("value")

    t = sub.add_parser("topic")
    tsub = t.add_subparsers(dest="cmd", required=True)
    te = tsub.add_parser("end"); te.add_argument("id")
    te.add_argument("--reason", required=True, choices=topics.END_REASONS)
    te.add_argument("--summary-file", help="JSON file; default: read JSON from stdin")
    ts = tsub.add_parser("status"); ts.add_argument("id")
    tg = tsub.add_parser("suggest"); tg.add_argument("id")

    r = sub.add_parser("recap"); r.add_argument("id", nargs="?"); r.add_argument("--all", action="store_true")
    r.add_argument("--days", type=float)

    a = ap.parse_args()
    if a.group == "persona":
        if a.cmd == "list":
            for pid in all_persona_ids():
                c = load_persona(pid)
                state = "deployed" if profile_dir(pid).exists() else "not deployed"
                print(f"{pid:10} {c['display_name']:10} {c['relation']:9} {c['level']:3} {state}")
        elif a.cmd == "init-soul":
            init_soul(a.id, force=a.force)
        elif a.cmd == "deploy":
            ids = all_persona_ids() if a.all else [a.id] if a.id else die("give an id or --all")
            for pid in ids:
                deploy(pid, dry=a.dry_run)
        elif a.cmd == "create":
            sys.exit(create_persona(a.spec, a.smoke, a.dry_run))
        elif a.cmd == "remove":
            if a.id in PROTECTED_IDS and not a.force:
                die(f"'{a.id}' is protected (use --force)")
            if not a.yes:
                die("removal needs --yes (confirm with the learner first)")
            remove_persona(a.id, purge=a.purge)
    elif a.group == "providers":
        print("\n".join(sorted(logged_in_providers())))
    elif a.group == "learner":
        data = load_learner()
        if a.cmd == "show":
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            if a.key not in ("name", "native_language", "default_level"):
                die(f"unknown learner key: {a.key}")
            old = data.get(a.key)
            data[a.key] = a.value
            save_learner(data)
            print(f"learner.{a.key}: {old} -> {a.value}")
            for pid in all_persona_ids():
                if profile_dir(pid).exists():
                    write_profile_soul(pid)
    elif a.group == "topic":
        load_persona(a.id)  # validates id
        if a.cmd == "end":
            raw = Path(a.summary_file).read_text(encoding="utf-8") if a.summary_file else sys.stdin.read()
            try:
                summary = json.loads(raw) if raw.strip() else {}
            except json.JSONDecodeError as e:
                # Never lose the topic end because of a bad summary: record it without details.
                print(f"WARN: summary JSON invalid ({e}); recording topic end without details")
                summary = {}
            e = topics.end_topic(a.id, a.reason, summary)
            if a.summary_file:
                Path(a.summary_file).unlink(missing_ok=True)  # consumed; avoid stale reuse
            print(f"OK topic ended: [{a.id}] {e['title']} (reason={a.reason}, mistakes={len(e['mistakes'])})")
        elif a.cmd == "status":
            print(json.dumps(topics.load_state(a.id), ensure_ascii=False, indent=2))
        elif a.cmd == "suggest":
            per = load_persona(a.id).get("persona", {})
            print(topics.suggest_topic(a.id, per.get("topic_themes", []), per.get("light_themes"),
                                       float(per.get("light_theme_ratio", 0.0))))
    elif a.group == "recap":
        pid = None if (a.all or not a.id) else a.id
        if pid:
            load_persona(pid)
        print(json.dumps(topics.recap(pid, a.days), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

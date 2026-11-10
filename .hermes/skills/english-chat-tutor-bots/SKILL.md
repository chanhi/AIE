---
name: english-chat-tutor-bots
description: "Use when working on the AIEnglish persona tutor bots."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [english, tutor, bot-mode, profiles, cron, persona]
    related_skills: [hermes-agent]
---

# AI English chat-tutor bots (AIEnglish project)

Project root: the git repo containing this skill (`.hermes/skills/` is a project-local skill — run `hermes skills trust` once per clone). Repo: https://github.com/chanhi/AIE (public). `PLAN.md` at the root is the source of truth for phase status and verified Hermes facts — read it first, update it after each phase. Load `hermes-agent` (and its background-systems reference, "Proactive Bot pattern" section) before touching profiles/cron.

## When to Use
Any work on this project: planning phases, persona configs/SOULs, shared tutor skills, gate/state scripts, cron routines, or the persona-creation skill.

All user-facing text (plans, reports, Tutor feedback) in Korean; persona chat in English.

## Architecture (decided — don't re-litigate)
- Each conversation partner = one Hermes **profile** shown as a Bot in Desktop Bot Mode. A `tutor` profile is the educator; defaults: `friend` (Jake), `partner` (Emma, PG tone), `coworker` (Daniel, SaaS PM).
- **One persona = one config file** `personas/<id>/persona.toml` (TOML, not YAML: system `python` has no PyYAML; `tomllib` is stdlib) (name, relation, level, traits, schedule, model, memory) → a deploy script creates the profile, SOUL.md, model, `skills.external_dirs`, and cron. Never hand-build a persona; the future `/new-persona` skill (tutor profile) must use the same deploy path.
- Shared rules live in project `skills/` loaded via `skills.external_dirs` — never `profile create --clone` (clones don't re-sync).
- Persona reply + Tutor feedback = **one LLM call, one message, two sections** (no separate tutor bot/group chat — ordering is uncontrollable).
- Proactive openers: per-persona `--no-agent` cron (30m tick) + gate script → `--deliver bot-chat`; empty stdout = skip. The bot writes the opener in its own Bot Chat, so memory and the profile model apply — no separate opener model.
- Idle timers come from `state.db` (see hermes-agent reference), not from LLM-written timestamps. Topic state/logs: Python stdlib + JSON/JSONL under `data/`.

## User's specs (defaults; later configurable per persona at creation)
- Level: B1 fixed for now; level choice (A2–C1) comes with the persona-creation skill.
- Feedback (Korean): no errors → only a better model answer; errors → model answer + each mistake with its reason.
- Output shape per turn: `💬 <Persona>: …` then `---` then `📘 Tutor: …`. `/qa` → Tutor section only, does not advance the conversation or topic state.
- Topic ends on natural close, `/end`, or the user saying they want to stop → short farewell + Tutor topic summary.
- Opener: 3h after topic end with no user message, only 08:00–18:00, max 2/day per persona. Topic left ACTIVE 24h → auto summary + close.
- Memory on (per-profile memory + shared `data/learner.md`).
- Model configurable per persona. Channel: Desktop now, Discord later (no Telegram) — keep delivery channel-agnostic.

## Tooling (built in Phase 1)
- `python scripts/aie.py persona list | init-soul <id> | deploy <id>|--all [--dry-run]` — idempotent deploy: profile create, model, external_dirs, `skills.auto_load=[english-chat-core]` (tutor: none), memory, SOUL, `display_name`.
- `python scripts/aie.py learner show | set name <X>` — learner name lives in `data/learner.json`; set re-renders all deployed SOULs. SOUL chain: `templates/SOUL.<template>.md` → `personas/<id>/SOUL.md` (editable, keeps `{learner_name}`) → profile SOUL with learner values.
- Use `skills.auto_load` for per-turn rules (lives in system prompt, never compacted) rather than relying on on-demand skill loading.
- Multi-turn test without touching Bot Chat: `hermes -p <id> chat -c <title> --create-if-missing -Q -q "<msg>"` (~10s/turn on gpt-6.1-sol).
- Topic state (Phase 2): only topic END is recorded (`aie.py topic end <id> --reason natural|user|command|newtopic|stale --summary-file data/tmp/<id>.json`); "active" = any user msg/opener after `last_end_at`. Normal turns stay tool-free. Logic lives in `scripts/topics.py` (state + .bak recovery, JSONL logs, learner.md auto block, `topic suggest`, `recap`).
- Pass summaries via a file written with the file tool, not a heredoc: `single_query_mode: deny` approvals block heredoc/`python -c` in `-q` runs.
- Close any sqlite handle on a profile's `state.db` promptly (read-only, short-lived): an open handle makes `hermes profile delete` fail on Windows (WinError 32).
- Wipe `data/state`, `data/logs` and restore `data/learner.md` after test runs so test data doesn't pollute recap/learner stats.
- New personas need only `personas/<id>/persona.toml` + `init-soul` + `deploy` (Phase 3 proved no code change). The `partner` SOUL template requires every placeholder it uses, incl. `feedback_focus` (relationship-specific Tutor focus) — a new persona missing a field fails at init-soul.
- Pet names / catchphrases in `speech_style` need an explicit frequency cap ("at most once every 3–4 messages"); "not every message" alone still produced one in almost every reply.

- Proactive routine (Phase 4): `deploy` writes `<profile>/scripts/aienglish_gate.py` (runpy wrapper → project `scripts/idle_gate.py <id>`) and recreates cron `[bot:<id>] AIEnglish proactive chat` (`every 30m --no-agent --deliver bot-chat --failure-deliver local`). Debug with `python scripts/idle_gate.py <id> --dry-run [--now ISO] [--force]`, `data/logs/gate.log`, `python tests/test_gate.py`.
- Idle timers count only user messages in the `Bot Chat` session (and Discord later), excluding `display_kind='internal_notification'` — otherwise CLI test sessions move the timers.

- Regression (Phase 5): `python tests/run_scenarios.py [--only ids]` on test bot `qatest` (Sam, `test = true` → excluded from learner.md/recap --all, data auto-wiped). Run it after changing `english-chat-core`, templates or command skills; add a scenario for every new behavior. Long runs (>10 min cap) go background — read `tests/reports/` afterwards.
- Provider safety-filter refusals (openai-codex flags e.g. hacking requests) happen before the model and poison the session: every later turn is refused too; Hermes surfaces content-filter refusals without fallback. Skills can't fix it — the remedy is `/undo` in the chat (documented in README). Don't put filter-triggering text in scenarios.

- Persona lifecycle (Phase 6): `/new-persona` and `/remove-persona` run only in the `tutor` bot; they go through `aie.py persona create --spec data/tmp/new-persona.json --smoke` (validation in `scripts/persona_spec.py`, auto-rollback, smoke turn) and `aie.py persona remove <id> --yes [--purge]`. Never hand-write persona.toml for users. Level behaviour (A2–C1) lives in the `english-chat-core` level guide, not in templates.
- After an e2e test that creates personas, remove them with `--purge` and delete the tutor test sessions (`hermes -p tutor sessions delete <id> --yes`) — the user wants test artifacts gone.
- Pass native Windows paths (`C:/Users/...`) to python, not `$TMPDIR` (MSYS path → 'file not found').

## Commands (skill = slash command)
`/qa`, `/end`, `/newtopic`, `/recap`, `/learner`, `/new-persona`, `/remove-persona`. Don't use `/review` or `/topic` — built-in commands own those names.

## Git / multi-PC
- Public repo: never commit personal data. `.gitignore` excludes `data/learner.*` (real), `data/state|logs|tmp`, `local.toml`, `.env`, test transcripts/reports. Run `git status` and grep for tokens before every push; Discord bot tokens belong in the Hermes profile `.env`, never in the repo.
- Skills reference the repo via `${HERMES_SKILL_DIR}/../..` — never hard-code `C:/Users/...` paths in `skills/`.
- Fresh clone: install Hermes + `hermes auth` → `cp local.example.toml local.toml` (set `[routines] enabled = false` on a dev-only PC so two PCs don't both message the learner) → `python scripts/aie.py persona deploy --all` (creates `data/learner.json` from the example) → `hermes skills trust`.
- Main PC = this one (runs routines). Second PC = Discord-integration dev only, routines off.

## Pitfalls
- `aietest` is a throwaway verification profile; don't ship personas from it.
- Ask before creating real profiles or cron jobs; report the model actually used (check `hermes auth list` / `hermes config get model` — don't assume the chat session's provider is available to profiles).
- Pause or remove test cron jobs immediately after a manual `cron run`.
- Bot Mode shows the profile id unless `profile.yaml` has `display_name: <Persona>` — deploy must write it (user found `aietest` impersonal).
- Opener requests must demand the `💬 <Persona>:` label and calling the learner by name (from `data/learner.md`); without them the opener doesn't feel like a conversation.

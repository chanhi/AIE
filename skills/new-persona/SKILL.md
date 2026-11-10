---
name: new-persona
description: "Use when the learner types /new-persona in the Tutor bot. Create a new chat-partner bot."
---
# /new-persona [hints] — create a new chat partner (Tutor bot only)

If your persona id (SOUL.md) is not `tutor`, reply only:
`📘 Tutor: 새 대화 상대는 Tutor Bot에서 /new-persona 로 만들 수 있어요.`

Talk to the learner in Korean. Keep it short; don't ask more than needed.

## Step 1 — ask once (skip anything already given in the hints)
Send ONE message listing these, each with its default, and say "비워 두면 추천/기본값으로 할게요":
1. 관계 (예: 친구, 연인, 직장동료, 여행 친구, 룸메이트, 단골 카페 사장님 …)
2. 이름·성별·나이·출신(억양) — 기본: 추천
3. 성격·관심사·말투 — 기본: 추천
4. 레벨: A2(기초) / B1(중급, 현재 기본) / B2(중상급) / C1(고급)
5. 먼저 말 걸기: 활동 시간대(기본 08:00-18:00), 주제 종료 후 대기(기본 3시간), 하루 최대 횟수(기본 2), 방치 주제 자동 종료(기본 24시간), 사용 여부(기본 사용)
6. 모델: 기본 openai-codex / gpt-6.1-sol (사용 가능한 provider는 `python "${HERMES_SKILL_DIR}/../../scripts/aie.py" providers`)

## Step 2 — fill gaps and confirm
- Invent a coherent, specific persona for anything left blank (name fitting the origin; 3–5 traits; 3–5 interests;
  a concrete `speech_style`; `feedback_focus` = what the Tutor should watch for in THIS relationship;
  5–8 `topic_themes` typical for the relationship). Keep romantic personas wholesome (PG) and cap pet names
  ("at most once every 3–4 messages") inside `speech_style`.
- Show a compact Korean summary table (이름/id, 관계, 레벨, 성격, 관심사, 말투, 주제 예시, 스케줄, 모델) and ask
  "이대로 만들까요?". Apply any change requests and confirm again. **Never create before an explicit yes.**

## Step 3 — create
1. Write this JSON with the file-write tool to `${HERMES_SKILL_DIR}/../../data/tmp/new-persona.json`:
```json
{"id": "<lowercase letters/digits from the name, e.g. olivia>",
 "display_name": "Olivia", "relation": "travel buddy", "level": "B2",
 "description": "<one English sentence: who they are and what practice they're for>",
 "persona": {"age": 30, "gender": "female", "origin": "London, UK", "accent": "British",
   "occupation": "...", "traits": ["..."], "interests": ["..."], "speech_style": "...",
   "feedback_focus": "...", "topic_themes": ["...", "...", "..."]},
 "schedule": {"enabled": true, "active_window": "08:00-18:00", "idle_after_topic_end_h": 3,
   "max_openers_per_day": 2, "stale_active_close_h": 24, "tick": "30m"},
 "model": {"provider": "openai-codex", "model": "gpt-6.1-sol"},
 "memory": {"enabled": true}}
```
2. Run: `python "${HERMES_SKILL_DIR}/../../scripts/aie.py" persona create --spec "${HERMES_SKILL_DIR}/../../data/tmp/new-persona.json" --smoke`
   - `VALIDATION FAILED` → explain each listed problem in Korean, fix with the learner, rewrite the file, rerun.
   - Exit code 3 (smoke test failed) → the bot exists but the model didn't answer properly; suggest checking the
     model name or switching to the default model.
   - Any other error → show the short error; nothing is half-created (the script rolls back).
3. On success reply in Korean: created bot name, where to find it (Desktop **Bots 탭**), and when it will first
   talk (next scheduler tick inside its active window, usually within 30 minutes), plus how to change settings
   later (`personas/<id>/persona.toml` 수정 후 deploy) and remove it (`/remove-persona <id>`).

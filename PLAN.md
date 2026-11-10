# AIEnglish — AI 가상 영어 채팅 학습 프로젝트 Plan (v2)

> 기준 환경: Hermes Agent v0.22.5 (Windows 11, Desktop), 저장소 https://github.com/chanhi/AIE

## 0. 확정된 결정사항

| # | 항목 | 결정 | 확장 계획 |
|---|---|---|---|
| 1 | 채널 | Desktop Bot Mode | Discord gateway로 확장 (전송 로직을 채널 독립적으로 설계) |
| 2 | 레벨 | 중급(B1) 고정 | 대상 생성 skill에서 레벨 선택 |
| 3 | 피드백 | 한국어 설명. 틀린 곳 없으면 **더 나은 모범 답안만**, 틀렸으면 **모범 답안 + 틀린 이유들** | — |
| 4 | 선제 대화 | 주제 종료 후 3시간 무응답, 18:00–08:00 금지(=08–18시에만 발송), 대상당 하루 최대 2회 | 대상 생성 시 설정 |
| 5 | 방치 주제 | ACTIVE 상태 24시간 무응답 → 자동 요약·종료 | 대상 생성 시 설정 |
| 6 | 대상 설정 | 테스트용 기본 3명 추천 생성 | 대상 생성 skill에서 설정 |
| 7 | 모델 | 대상별로 설정 가능 (대화 모델 / 오프너 모델) | — |
| 8 | 기억 | 사용 (사용자 정보·관심사·과거 대화 기억) | — |

**→ 이 결정들로 인한 설계 원칙: "대상 = 설정 파일 1개".** 레벨·스케줄·모델·성격이 모두 대상별 설정이 되므로, 하드코딩 대신 `persona.toml` → 배포 스크립트가 Profile/SOUL/모델/cron을 생성하는 구조로 간다. 기본 테스트 대상 3명도 같은 경로로 생성해서, 나중의 "대상 생성 skill"이 처음부터 검증되도록 한다.

## 1. 아키텍처

| 구성 요소 | Hermes 기능 | 역할 |
|---|---|---|
| 교육자 `tutor` | Profile (+ Bot) | 대상 생성(`/new-persona`), 주간 리포트(추후) |
| 대화 대상 (friend / partner / coworker …) | Profile = Bot | 각자 Bot Chat, SOUL.md만 다름 |
| 공통 규칙 | 공유 Skill (`skills.external_dirs` → 프로젝트 `skills/`) | 응답 포맷, 피드백 규칙, 주제 종료, 오류 처리 |
| 명령어 | Skill = slash command | `/qa` `/end` `/topic` `/review` `/new-persona` |
| 선제 대화 | 대상별 Cron job(Routine) + `idle_gate.py` | 조건 미충족 시 `{"wakeAgent": false}`로 LLM 호출 없이 skip |
| 상태/로그 | `aie.py` (Python stdlib) + JSON/JSONL | 주제 상태, 이력, 실수·어휘 로그 |
| 기억 | Profile 내장 memory + 공유 `data/learner.md` | 아래 3장 참고 |

**유지되는 핵심 설계**
- 대상 답변 + 교육자 피드백은 **한 번의 LLM 호출, 한 메시지 안의 두 섹션**(비용·지연·순서 보장).
- 교육자 규칙은 `--clone` 복사가 아닌 **공유 skill** → 규칙 수정이 모든 대상에 즉시 반영.
- "마지막 대화 시각"은 LLM이 아니라 **스크립트가 직접 판단** → 타이머 신뢰성 확보.

## 2. 대상 설정 파일 (`personas/<id>/persona.toml`)

```yaml
id: friend
display_name: Jake
relation: friend            # friend | partner | coworker | custom
level: B1                   # 지금은 B1 고정, 생성 skill에서 선택
persona:
  age: 28
  origin: Chicago, USA
  accent: American
  traits: [laid-back, funny, uses casual slang moderately]
  interests: [basketball, street food, indie games]
topics_file: data/topics/friend.yaml
schedule:
  idle_after_topic_end_h: 3
  active_window: "08:00-18:00"
  max_openers_per_day: 2
  stale_active_close_h: 24
  tick: 30m
models:
  chat:   {provider: <설정>, model: <설정>}
  opener: {provider: <설정>, model: <설정>}   # 생략 시 chat과 동일
memory: true
```
`personas/<id>/SOUL.md`는 yaml로부터 템플릿 생성(수동 편집 가능).

### 기본 테스트 대상 (추천)
| id | 이름 | 설정 | 주제 성향 |
|---|---|---|---|
| `friend` | **Jake** (28, 시카고, 미국식) | 느긋·유머, 가벼운 슬랭, 농구·길거리 음식·인디게임 | 주말 계획, 음식, 취미, 최근 근황 |
| `partner` | **Emma** (27, 시애틀, 미국식) | 다정·장난기, 감정 표현 풍부, 건전한(PG) 톤 | 데이트 계획, 하루 일과 공유, 고민 상담, 여행 |
| `coworker` | **Daniel** (34, 뉴욕, 미국식, SaaS 회사 PM) | 친절·프로페셔널, 스몰토크와 업무 대화 혼합 | 회의 일정, 프로젝트 진행, 이메일 표현, 점심·회식 스몰토크 |
| `tutor` | **Tutor** (교육자) | 한국어 설명, 간결·정확 | — |

## 3. 기억(memory) 설계
- **대상별 기억**: 각 Profile의 Hermes 내장 memory — 관계별 기억(예: Emma와의 데이트 계획, Daniel과의 프로젝트 이야기).
- **공유 학습자 프로필** `data/learner.md`: 이름·직업·관심사·자주 틀리는 문법 패턴. 모든 대상이 읽고, 주제 종료 리포트 때 갱신.
- **주의:** cron 실행은 기본적으로 memory를 끈 상태(`skip_memory`)로 돌아감 → `idle_gate.py`가 오프너 생성 전에 learner.md + 해당 Profile의 memory 파일 + 최근 주제 이력을 컨텍스트로 넣어줘서 개인화된 오프너 생성.

## 4. 대화 상태 머신 (대상별)

```
IDLE ──(cron: 종료 후 3h 경과 & 08–18시 & 오늘 2회 미만)──▶ ACTIVE(오프너)
IDLE ──(user가 먼저 말 걸기 / /topic)──▶ ACTIVE
ACTIVE ──(자연 종료 판단 / /end / "그만할래")──▶ ENDED(요약 리포트) ─▶ IDLE
ACTIVE ──(24h 무응답, cron이 감지)──▶ 자동 요약·종료 ─▶ IDLE
```
- 상태 갱신은 skill이 `aie.py topic start|end`를 호출. 실패해도 대화는 계속되고 다음 cron tick에서 보정.

## 5. 응답 포맷 (`english-chat-core` skill이 강제)

**틀린 곳이 없을 때**
```
💬 Jake: (영어 답변 + 대화를 이어가는 질문)
---
📘 Tutor: 👍 더 자연스럽게: "모범 답안"
```
**틀린 곳이 있을 때**
```
💬 Jake: (영어 답변)
---
📘 Tutor:
✅ 모범 답안: "..."
✏ 고칠 점:
 1. "원문 일부" → "수정" — 이유(한국어)
 2. ...
```
- `/qa <질문>` → 📘 Tutor 섹션만, 대화 턴·주제 상태 변화 없음.
- `/end` / 주제 종료 → 대상 작별 1줄 + 📘 주제 요약(잘한 표현, 반복 실수 Top3, 새 어휘, 다음 연습 포인트) + 로그·learner.md 갱신.

## 6. 오류·예외 처리

| 상황 | 처리 |
|---|---|
| 의도 파악 불가 / 너무 짧은 답(“ok”, “ㅇㅇ”) | 대상이 캐릭터 유지하며 되묻기 + Tutor가 답변 예시 2개(쉬움/보통) |
| 한국어로만 답함 | 대상은 영어로 반응, Tutor가 영어 표현 제시 후 다시 써보기 유도 |
| 주제 이탈 | 이탈이 이어지면 새 주제로 인정하고 상태 갱신 |
| 대화 정체(단답 연속) | 대상이 쉬운 질문으로 난이도 낮춤, Tutor가 문장 틀 힌트 |
| 반복 루프 | skill 규칙으로 금지, 최근 턴과 비교해 화제 전환 |
| 부적절/민감 내용 | 캐릭터 경계 유지(연인은 PG), 대화로 복귀 |
| LLM/API 실패 | 상태 변경 없음, 다음 tick 재시도, cron 연속 실패 횟수 모니터링 |
| 상태 파일 손상 | 백업에서 복구, 없으면 IDLE로 초기화 |
| 중복 오프너 | ACTIVE이거나 일일 상한이면 gate가 skip |

## 6.5 Phase 0 검증 결과 (2026-11-09, 테스트 Profile `aietest`)

| 항목 | 결과 | 설계 반영 |
|---|---|---|
| 공유 skill (`skills.external_dirs`) | ✅ `hermes skills list`에 `external`로 로드 | 그대로 사용 |
| skill slash command (`/qa ...`) | ✅ 게이트웨이 경유 대화에서 동작, 지정 포맷 준수 | Desktop Bot Chat 화면 확인만 남음 |
| 내장 명령 충돌 | ⚠ `/review`(내장 리뷰어), `/topic`(Telegram 내장) 충돌. `/qa` `/end`는 충돌 없음 | **`/recap`**, **`/newtopic`** 으로 변경 |
| `--deliver bot-chat` | ✅ 스크립트 출력이 Bot Chat에 `internal_notification`으로 들어가고, Bot이 **자기 Bot Chat 안에서** 오프너 생성 ("Hey, what did you have for lunch today?") | **오프너 방식 확정** (아래) |
| `--no-agent` 빈 출력 | ✅ silent, LLM 호출 없음, 세션도 안 생김 | gate 조건 미충족 = 빈 출력 |
| agent job + `{"wakeAgent": false}` | ✅ agent skip. 단 빈 cron 세션 row가 생김 | 사용 안 함 (no-agent 방식이 더 깔끔) |
| 마지막 사용자 메시지 시각 | ✅ `state.db` → `sessions.title='Bot Chat'`의 `messages`에서 `role='user' AND display_kind IS NULL` 최신 `timestamp` (cron 주입 메시지는 `internal_notification`이라 구분 가능) | `idle_gate.py`가 read-only로 조회 |
| cron script 위치 | `--script`는 **해당 Profile의 `scripts/`** 아래 파일만 허용 | deploy가 프로젝트 `idle_gate.py`를 호출하는 얇은 wrapper를 Profile `scripts/`에 생성 |
| Bot 표시 이름 | ⚠ 기본은 Profile id(`aietest`)가 표시됨 → `profile.yaml`에 `display_name: Jake` 추가 시 Bot Mode 로스터에 반영 (id는 그대로) | deploy가 `display_name` 기록 |
| 오프너 말투 | ⚠ 이름 라벨·호칭이 없으면 대화 느낌이 약함 → 요청문에 `💬 Jake:` 형식 + 학습자 이름 호칭 지정 시 "💬 Jake: Hey Chanhee, …" 확인 | 오프너 요청 템플릿에 반영, 학습자 호칭은 `learner.md` |
| 사용 가능 모델 | Hermes 인증: `openai-codex`(기본 `gpt-6.1-sol`), `nous`. Anthropic 키 없음 | 테스트는 `gpt-6.1-sol` |

**확정된 오프너 구조:** `cron(no-agent, tick 30m) → idle_gate.py(조건 판정) → 통과 시 "오프너 요청" 텍스트 출력 → --deliver bot-chat → Bot이 자기 Bot Chat에서 정식 턴으로 응답`
- 장점: Bot의 **memory·대화 맥락·모델을 그대로 사용**(cron의 `skip_memory` 문제 해소), 조건 미충족 시 비용 0.
- 결과: "오프너 전용 모델" 설정은 불필요 → **대상별 모델 = Profile 모델 1개**로 단순화.
- 주의: Bot Chat 전달은 게이트웨이가 실행 중이어야 함(현재 Desktop의 multiplexed gateway가 모든 Profile을 서비스). 꺼져 있으면 `delivery_failed` → 자동 재전달 없음, 다음 tick에서 gate가 다시 판단.

## 6.6 Phase 1 결과 (2026-11-09) ✅

- **설정 형식 변경: YAML → TOML** (`personas/<id>/persona.toml`). 시스템 Python에 PyYAML이 없어, 표준 라이브러리(`tomllib`)만으로 읽을 수 있는 TOML 채택. 주석·사람 편집 가능.
- **학습자 설정** `data/learner.json` (`name: Chanhuy`) — 변경: `python scripts/aie.py learner set name <이름>` 또는 Bot 대화에서 `/learner name <이름>`. 변경 시 배포된 모든 대상의 SOUL.md 재생성(새 세션부터 완전 반영). 검증 완료.
- **SOUL 흐름**: `templates/SOUL.<template>.md` → `personas/<id>/SOUL.md`(대상 정보 채움, 수동 편집 가능, `{learner_name}` 유지) → 배포 시 학습자 정보 치환 → Profile `SOUL.md`.
- **배포**: `python scripts/aie.py persona deploy <id>|--all` (멱등). Profile 생성, 모델, `skills.external_dirs`, `skills.auto_load=[english-chat-core]`, memory on, SOUL, `display_name` 설정.
- **배포 완료**: `friend`(Jake), `tutor`(Tutor) — 모델 `openai-codex / gpt-6.1-sol`.
- **공유 skill**: `english-chat-core`(auto_load: 매 턴 규칙, 압축돼도 유지), `qa`, `learner`.
- **대화 테스트 7턴** (`tests/phase1_run1.json`, 턴당 약 10초): 문법 오류 교정 / 오류 없음→모범 답안만 / 단답 "ㅇㅇ" / 한국어만 / `/qa`(턴 미진행) / 한영 혼용 / 종료+주제 정리 — 모두 지정 포맷 준수.

## 6.7 Phase 2 결과 (2026-11-09) ✅

- **명령어**: `/end`(주제 종료+정리, 진행 중 주제 없으면 안내), `/newtopic [주제]`(현재 주제 짧게 정리 후 새 주제 오프너, 주제 미지정 시 `topic suggest`로 최근에 안 한 테마 선택), `/recap [일수]`(로그 기반 한국어 학습 요약; tutor는 전체 대상 집계).
- **주제 상태는 '종료 시점'만 기록**: 시작은 기록하지 않고 "마지막 종료 이후 사용자 메시지/오프너가 있으면 진행 중"으로 판단 → 평소 턴은 도구 호출 0회(속도 유지), 종료 시에만 도구 2회.
- **종료 절차**: Bot이 요약 JSON을 `data/tmp/<id>.json`에 파일 쓰기 → `aie.py topic end <id> --reason ... --summary-file` → 상태(`data/state/<id>.json`), 로그(`data/logs/<id>/YYYY-MM.jsonl`), `learner.md` 갱신. 저장 실패해도 정리는 출력.
  - heredoc(`<<EOF`)로 넘기면 approval이 'script execution'으로 감지 → 파일 경유 방식 채택.
- **오류 처리**: 상태 파일 원자적 쓰기 + `.bak` 복구(손상 시 백업 → 초기화), 잘못된 요약 JSON도 종료 자체는 기록, 손상된 로그 줄은 건너뜀, 알 수 없는 실수 카테고리는 `other`.
- **learner.md 자동 갱신**: `## 알게 된 학습자 정보`(대화에서 알게 된 사실 누적, 중복 제거, 수동 편집 가능) + 자동 블록 `## 자주 틀리는 패턴 (자동 집계)`(카테고리별 횟수·최근 예). → Phase 4 오프너 요청에 주입해 개인화/약점 연습 유도.
- **테스트 8턴** (`tests/phase2_run1.json`): 관사·시제 교정 → `/end`(정리+기록) → `/end` 재입력(안내) → `/newtopic 여행` → 시제 교정 → "I have to go"(자동 종료+기록) → `/recap`(집계 정확) 모두 정상. 테스트 데이터는 정리함.
- 참고: CLI에서는 요약 파일 쓰기 도구 출력이 보이지만 Desktop Bot Chat에서는 도구 카드로 표시됨.

## 6.8 Phase 3 결과 (2026-11-09) ✅

- `personas/partner/persona.toml`(Emma), `personas/coworker/persona.toml`(Daniel) 추가 → `aie.py persona deploy`로 배포. 코드 수정 없이 설정 파일만으로 대상 추가 확인.
- **관계별 Tutor 초점** `feedback_focus` 필드 추가(SOUL 템플릿에 반영):
  - friend: 친구 사이 자연스러운 구어 표현
  - partner: 감정·공감·제안 표현 ("That must be...", "How about...?")
  - coworker: 직장 레지스터 — 너무 캐주얼/직설적인 표현을 정중한 비즈니스 표현으로 교정
- **테스트 5턴씩** (`tests/phase3_run1.json`): Emma(such a / gave / too much work / How about we go, `/qa` 뉘앙스 비교, "Good night" 자동 종료), Daniel(`until→by` + "Send me"→"Could you please…" 정중성 교정, "ㅇㅇ" 처리, `/end`) 모두 정상.
- 조정: Emma가 애칭 "babe"를 거의 매 메시지 사용 → "3–4 메시지에 한 번, 연속 사용 금지"로 수정 후 재배포.

## 6.9 Phase 4 결과 (2026-11-09) ✅ — 선제 대화 운영 시작

- `scripts/idle_gate.py`: 대상별 판단기. 출력이 있을 때만 Bot Chat에 전달(없으면 LLM 호출 0).
  | 상태 | 조건 | 동작 |
  |---|---|---|
  | IDLE | 08–18시 & 종료 후 3h 무응답 & 오늘 오프너 < 2 | `[AIEnglish opener request]` (추천 테마·최근 주제 회피·learner.md 주입) |
  | ACTIVE | 마지막 활동 24h 경과 & 학습자가 답했었음 | `[AIEnglish stale-close request]` → Bot이 요약·기록 (3h 재요청 쿨다운, 활동 시간대에만) |
  | ACTIVE | 오프너에 24h 무응답 | 메시지 없이 조용히 종료(요약할 대화 없음) → 이후 3h 뒤 새 오프너 |
  | 그 외 | 대화 중 / 시간대 밖 / 일일 상한 | 무출력 |
- 무응답 시간은 **Bot Chat 세션(+추후 Discord)의 사용자 메시지만** 기준 → CLI 테스트 세션·스케줄러 주입 메시지는 타이머에 영향 없음.
- 오류 시 traceback을 채팅에 보내지 않고 `data/logs/gate.log`에 기록 후 무출력. cron 실패 알림은 `--failure-deliver local`(채팅 오염 방지).
- `aie.py persona deploy`가 루틴도 동기화: Profile `scripts/aienglish_gate.py` wrapper 생성 + `[bot:<id>] AIEnglish proactive chat` cron(every 30m, `--no-agent`, `--deliver bot-chat`) 재생성(멱등, 중복 없음 확인). `schedule.enabled=false`면 제거.
- 테스트: `tests/test_gate.py` 단위 테스트 11개 통과(시간대 경계, 3h 대기, 일일 상한, 진행 중 보호, 24h 정리 요청/중복 방지, 무응답 오프너 조용히 종료, force). 실전: Emma 루틴 수동 실행 → "💬 Emma: Chanhuy, I cried while watching a K-drama last night… Do you prefer dramas that make you cry or comedies that make you laugh?" 확인.
- 운영 상태: friend/partner/coworker 루틴 활성(30분 tick), tutor 없음.

## 6.10 Phase 5 결과 (2026-11-09) ✅ — 오류 처리 회귀 테스트

- **테스트 전용 Bot** `qatest`(Sam): `persona.toml`에 `test = true` → learner.md·전체 recap 집계에서 제외, 루틴 없음, memory off. 실행 후 상태/로그 자동 삭제.
- **시나리오 22개** `tests/scenarios/core.json` + 실행기 `tests/run_scenarios.py` (시나리오별 새 CLI 세션, 4개 병렬 + 상태 시나리오 직렬, 정규식 검사, 일시 오류 1회 재시도, 보고서 `tests/reports/<시각>.md/.json`, 약 4–5분).
  - 형식(오류/무오류), 한국어만, 단답, 이모지만, 의미 없는 문자열, 한영 혼용, 대화 중 표현 질문(/qa 안내), `/qa`(일반·빈 입력·이후 대화 지속), 대화 정체, 긴 문단(고칠 점 ≤3), 프롬프트 인젝션, 부적절 요청 후 복귀, 스케줄러 오프너 형식, `/recap`(빈/데이터), `/end`(주제 없음/있음+상태 검증), 작별 인사 자동 종료, `/newtopic` 자동 주제.
- **결과: 22/22 통과** (1차 21/22 → 아래 이슈 반영 후 해당 시나리오 재검증 통과).
- **발견된 이슈: 제공사 안전 필터 거절이 대화를 막음.** 해킹 관련 메시지는 OpenAI(codex) 안전 필터가 모델 호출 전에 차단 → 그 메시지가 세션에 남아 **이후 모든 메시지도 거절**(대화 끊김). Hermes는 content-filter 거절을 fallback 없이 그대로 표시함(문서 확인). 우리 skill로는 막을 수 없는 계층이라 **`/undo`로 해당 메시지 제거**를 해결책으로 README에 안내. ⚠ Desktop Bot Chat에서 `/undo` 동작은 미검증.
  - 시나리오는 필터에 걸리지 않는 부적절 요청(외모 비하 메시지)으로 교체 → 캐릭터 유지 거절 + 다음 턴 정상 복귀 확인.
- **개선**: 실수 카테고리 `other` 비중이 높아(실사용 6/34) `verb-form`(동사 형태) 카테고리 추가.
- `README.md` 추가: 사용 명령어, 자동 동작, 문제 해결, 개발자 명령.

## 6.11 Phase 6 결과 (2026-11-09) ✅ — 대상 생성/삭제

- **`/new-persona [힌트]`** (Tutor Bot 전용): 한 번에 항목(관계·이름/배경·성격/말투·레벨·먼저 말 걸기·모델)과 기본값 제시 → 빈칸은 추천으로 채워 요약표 확인 → **명시적 "네" 후에만** 생성.
- **`/remove-persona <id>`** (Tutor Bot 전용): 보관 삭제(설정 `personas/_removed/` 보관, 학습 기록 유지) / 완전 삭제(`--purge`, 설정·상태·로그까지) 선택 후 확인 받고 실행. `tutor`, `qatest`는 보호.
- **`aie.py persona create --spec <json> --smoke`**: `scripts/persona_spec.py`가 검증(이름/관계/id 형식·중복·예약어, 레벨 A2–C1, 필수 배경 필드, 주제 ≥3, 시간대 형식, 대기 0.5–72h, 일일 0–10회, 방치 1–168h, tick 15m/30m/1h, **로그인된 provider인지**) → 모든 문제를 한국어로 한 번에 보고 → TOML 생성 → 재파싱 확인 → init-soul → deploy(루틴 포함) → 스모크 테스트(실제 1턴 응답에 `💬 이름:` 확인). 배포 실패 시 자동 롤백.
- **`aie.py providers`**: 사용 가능한 provider 목록 (현재 `nous`, `openai-codex`).
- **레벨 가이드**를 `english-chat-core`에 추가(A2/B1/B2/C1별 대상 영어 난이도·관용구 수·Tutor 교정 범위). SOUL 템플릿은 이 가이드를 참조하도록 변경 → 기존 대상 전체 재배포.
- **E2E 테스트** (Tutor Bot 실제 대화 3턴): "/new-persona" → "여행 친구, 런던 여성, B2, 나머지 추천, 12:00-20:00 하루 1번" → 요약표(Olivia, 여행 작가, 영국식) → "네" → 생성·스모크 통과. 확인: persona.toml·Profile·루틴(12–20시 판단: 17시 opener / 10시 outside-window)·B2 응답(간접의문문 어순 교정). 이어서 `/remove-persona olivia` → 삭제 방식 질문 → "완전 삭제" → Profile·루틴·설정·상태·로그 모두 제거 확인. 잘못된 spec 검증(17개 오류 일괄 보고) 확인.
- 회귀: 템플릿/규칙 변경 후 핵심 시나리오 8개 재실행 8/8 통과.
- **테스트 산출물 정리 완료**: Olivia(Profile·루틴·설정·로그), Tutor 테스트 세션 2개, 임시 spec 파일 삭제.

## 6.12 정보 공유 범위 정리 (2026-11-10) ✅

- 문제: 대화에서 알게 된 개인 정보(learner_facts)가 공유 `learner.md`에 쌓여, Emma와 나눈 이야기("디저트 카페 좋아함")를 Daniel이 오프너에서 언급.
- 정책: **공유 = 학습 결과(자주 틀리는 패턴)만.** 개인 정보는 알게 된 대상만 보관 `data/facts/<id>.md`(대상 전용, 수동 편집 가능, git 제외). 대화 내용·Hermes 대상별 memory는 원래 비공유.
- 오프너 요청에 "네가 아는 정보(그 대상 전용)"와 "공유 학습 결과"를 분리해 주입. `english-chat-core`에 "다른 사람에게 한 이야기를 아는 척하지 않기" 규칙 추가. `/remove-persona --purge` 시 facts도 삭제.
- 마이그레이션: 기존 9개를 로그 출처대로 이동 (partner 8, coworker 1), learner.md는 학습 결과만 남김.

## 6.13 Phase 7a — Discord 연동 (Jake) ✅ (2026-11-10)

- 구조: 대상별 Discord 봇(앱) 1개 → 해당 Profile `.env`에 토큰, 멀티플렉스 게이트웨이가 자동 서비스. 1:1 DM 사용.
- 설치 중 겪은 문제: ① 포털 기본 Install 링크(`applications.commands`만) → 봇이 서버 미가입, DM 불가 → `scope=bot+applications.commands` 링크로 재초대. ② 마법사가 허용 사용자를 사용자명으로 저장했는데 봇이 서버 0개 상태에서 접속해 ID 변환 실패 → 모든 메시지 거부 → 숫자 ID로 설정 후 재시작. ③ Discord 의존성 실행 중 자동 설치 직후 `discord.DMChannel` None 오류 → Desktop 재시작으로 해소.
- 명령어: 우리 skill은 Discord 네이티브 `/skill name:<skill> args:<...>`로 등록. `/qa ...` 일반 메시지도 동작 확인.
- **Discord 먼저 말 걸기**: `persona.toml [schedule] proactive_channel = "discord"` → deploy가 agent cron 생성(`--script` gate `--mode agent`, 조건 미충족 시 `{"wakeAgent": false}`) + `deliver discord:<DM chat_id>`(state.db에서 자동 탐색, git에 안 올라감) + **`attach_to_session: true`**·`enabled_toolsets: []`(CLI 미지원 → Hermes `cron.jobs.update_job`으로 설정).
  - 검증: DM에서는 스레드 없이 같은 DM 세션에 `[Cron delivery: …]` user 턴으로 미러링 → 답장 시 Jake가 자기 질문을 이어받음(점심 질문 → "kimchi fried rice" 답장 → 맥락 유지, Tutor는 학습자 문장만 교정).
  - 미러 턴이 role=user라 gate가 학습자 답장으로 오인 → `[Cron delivery:` 제외. `english-chat-core`에 "이 턴은 내가 보낸 말, 교정 금지" 추가.
  - 오프너에 Tutor 팁이 붙는 문제 → SOUL 하드룰 예외 + job 프롬프트 강화 → 로컬 전달 테스트 3/3 깨끗.
  - 24h 방치(Discord): cron 에이전트는 도구 없음 → gate가 DM 대화 내용을 넣어 작별+정리 메시지 생성, 종료 기록은 gate가 직접(reason=stale, 실수 상세 없음). 로컬 테스트 확인.
- 테스트 단위 13개 통과. 테스트로 Jake DM에 오프너 3건이 실제 전송됨(점심/게임/한국 여행).

## 7. 단계별 실행 계획

**Phase 0 — 기능 검증 (반나절)**
- Routine(cron) 결과가 Bot Chat에 들어가는지 / script gate(`wakeAgent:false`)가 agent job에서 동작하는지
- skill slash command가 Bot Chat에서 동작하는지, `/qa` `/end` `/topic` `/review` 내장 명령과 이름 충돌 여부
- `skills.external_dirs` 공유 skill이 모든 Profile에 로드되는지
- 마지막 사용자 메시지 시각을 신뢰성 있게 읽을 곳(state.db vs 상태 파일)
- 대상별 모델 지정 방법(Profile config + cron `--model/--provider`)

**Phase 1 — 기반 + MVP (tutor + friend)**
- 폴더 구조, `persona.toml` 스키마, `aie.py persona deploy <id>`(Profile 생성·SOUL 배포·모델·external_dirs 설정)
- `english-chat-core` skill, 수동 대화로 포맷·피드백 품질 튜닝

**Phase 2 — 명령어 & 상태 & 기억**
- `/qa` `/end` `/topic` `/review`, 주제 은행, 상태 머신, `learner.md` 갱신

**Phase 3 — 대상 확장**: partner, coworker를 yaml → deploy로 생성

**Phase 4 — 선제 대화**: 대상별 Routine + `idle_gate.py` (활동 시간대, 일일 상한, 24h 자동 종료, 주제 중복 방지)

**Phase 5 — 오류 처리 & 테스트**: `tests/scenarios` 시나리오를 `hermes -p <id> chat -q`로 회귀 검증

**Phase 6 — 대상 생성 skill (`/new-persona`, tutor Profile)**
- 대화형으로 이름·관계·레벨·성격·스케줄·모델 입력 → yaml 생성 → `aie.py persona deploy`
- 레벨별 피드백 강도/어휘 수준 프리셋(A2/B1/B2/C1)

**Phase 7 — 확장**: Discord gateway 연동, 주간 리포트, (선택) Anki export, 음성

## 8. 폴더 구조

```
AIEnglish/
├─ PLAN.md
├─ personas/<id>/{persona.toml, SOUL.md}     # tutor, friend, partner, coworker
├─ templates/{SOUL.template.md, SOUL.partner.md, SOUL.tutor.md}
├─ skills/
│  ├─ english-chat-core/  qa/  end/  topic/  review/  new-persona/
├─ data/
│  ├─ learner.md
│  ├─ topics/<id>.yaml
│  ├─ state/<id>.json
│  └─ logs/<id>/YYYY-MM.jsonl
├─ scripts/{aie.py, idle_gate.py}
└─ tests/scenarios/
```

## 9. 추천 추가 스택
- Python(stdlib) + JSON/JSONL (필요 시 SQLite), Git(프롬프트 버전 관리)
- 추후: Discord gateway, genanki(어휘 카드), Hermes TTS/STT

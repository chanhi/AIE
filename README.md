# AIEnglish — AI 가상 영어 채팅

Hermes Desktop의 **Bots 탭**에서 대상(Bot)과 영어로 대화하면, 대상의 답장과 함께 📘 Tutor의 한국어 피드백이 붙습니다.
설계/진행 기록은 [PLAN.md](PLAN.md)를 보세요.

## 대화 상대
| Bot | 관계 | 특징 |
|---|---|---|
| Jake | 친구 | 시카고, 캐주얼한 구어체 |
| Emma | 연인 | 시애틀, 감정·공감 표현 |
| Daniel | 직장동료 | 뉴욕 SaaS PM, 정중한 업무 영어 |
| Tutor | 교육자 | 질문 답변, 전체 학습 요약 |
| Sam | 테스트용 | 회귀 테스트 전용 — Bots 탭에서 우클릭 → Hide Bot 권장 |

## 명령어 (대화창에 입력)
| 명령 | 설명 |
|---|---|
| `/qa <질문>` | 단어·표현 질문. 대화 흐름은 그대로 유지 |
| `/end` | 지금 주제 종료 + 정리 |
| `/newtopic [주제]` | 새 주제로 전환 (주제 생략 시 Bot이 고름) |
| `/recap [일수]` | 학습 요약 (Tutor에서 쓰면 전체 대상 합산) |
| `/learner name <이름>` | Bot들이 부를 내 이름 변경 |
| `/new-persona [힌트]` | (Tutor Bot) 새 대화 상대 만들기 — 관계·레벨(A2~C1)·성격·스케줄·모델 선택 |
| `/remove-persona <id>` | (Tutor Bot) 대화 상대 삭제 (보관 / 완전 삭제) |
| `/undo` | 마지막 주고받은 메시지 삭제 (아래 문제 해결 참고) |

## 자동 동작
- 주제가 끝나고 3시간 무응답 → 08–18시 사이에 Bot이 새 주제로 먼저 말 걸기 (대상당 하루 최대 2회)
- 대화 중 24시간 무응답 → Bot이 주제 정리 / 먼저 건 말에 답이 없으면 조용히 종료
- 설정 변경: `personas/<id>/persona.toml`의 `[schedule]` 수정 → `python scripts/aie.py persona deploy <id>`

## 문제 해결
| 증상 | 원인 / 해결 |
|---|---|
| `⚠️ ... safety filter refused this request` 가 뜨고 이후 메시지도 계속 거절됨 | 모델 제공사(OpenAI)의 안전 필터가 특정 메시지(예: 해킹 관련)를 차단한 것. 그 메시지가 대화 기록에 남아 있는 동안 계속 거절됨 → **`/undo`** 로 해당 메시지를 지운 뒤 다시 대화 |
| Bot이 먼저 말을 안 걸어요 | `python scripts/idle_gate.py <id> --dry-run` 으로 현재 판단 확인 (대화 중/시간대 밖/일일 상한 등), 기록: `data/logs/gate.log` |
| 정리 후 "기록 저장에 실패" | `python scripts/aie.py topic status <id>` 확인. 다음 정리 때 다시 저장됨 |

## 새 PC에 설치
1. [Hermes Agent](https://hermes-agent.nousresearch.com/docs/) 설치 후 모델 로그인 (`hermes auth`, 예: openai-codex)
2. 저장소 받기
   ```bash
   git clone https://github.com/chanhi/AIE.git && cd AIE
   cp local.example.toml local.toml
   ```
   - **보조 PC(개발 전용)** 라면 `local.toml`에서 `[routines] enabled = false` → 두 PC가 동시에 먼저 말 걸기 방지
3. Bot 생성: `python scripts/aie.py persona deploy --all`
   - 첫 실행 시 `data/learner.json`이 예제에서 생성됨 → `python scripts/aie.py learner set name <영어이름>`
4. 개발용 안내 skill 활성화(선택): 저장소 안에서 `hermes skills trust`
5. Hermes Desktop → Bots 탭에서 확인

> 학습 기록·Bot 대화/기억은 PC별로 저장되며 저장소에 올라가지 않습니다(공개 저장소). 기억까지 옮기려면 `hermes profile export/import`.

## 개발자용
```bash
python scripts/aie.py persona list                 # 대상 목록/배포 상태
python scripts/aie.py persona create --spec x.json --smoke  # spec(JSON)으로 대상 생성
python scripts/aie.py persona remove <id> --yes [--purge]   # 대상 삭제
python scripts/aie.py providers                    # 사용 가능한 provider
python scripts/aie.py persona deploy <id>|--all    # 설정 → Profile/SOUL/모델/루틴 반영 (멱등)
python scripts/aie.py recap --all --days 7         # 학습 통계 JSON
python tests/test_gate.py                          # 선제 대화 판단 단위 테스트
python tests/run_scenarios.py [--only id,...]      # 대화 회귀 테스트 (테스트 Bot Sam, 약 4~5분)
```

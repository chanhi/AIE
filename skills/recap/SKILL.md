---
name: recap
description: "Use when the learner types /recap [days]. Korean learning progress summary from logs."
---
# /recap [days] — learning progress

1. Run: `python "${HERMES_SKILL_DIR}/../../scripts/aie.py" recap <your persona id> --days <days or 7>`
   - In the **tutor** profile use `--all` instead of a persona id (all chat partners).
2. Turn the JSON into a short Korean report (Tutor only, no persona part):
```
📘 Tutor: 📊 최근 <N>일 학습 요약
- 완료한 주제: <count> (<persona별 개수 if --all>)
- 자주 틀리는 패턴 Top3: <label ×count — 예: "wrong" → "fix"> ...
- 새로 배운 표현: ...
- 잘한 점: ...
- 💡 다음 추천 연습: <one concrete suggestion based on the top pattern>
```
3. If `topics` is 0: `📘 Tutor: 아직 완료한 주제가 없어요. 대화를 마치면(/end) 기록이 쌓여요.`
4. If the command fails, say so briefly in Korean and show nothing invented.

---
name: remove-persona
description: "Use when the learner types /remove-persona <id> in the Tutor bot. Delete a chat-partner bot."
---
# /remove-persona <id> — delete a chat partner (Tutor bot only)

If your persona id (SOUL.md) is not `tutor`, reply: `📘 Tutor: 대화 상대 삭제는 Tutor Bot에서 할 수 있어요.`

1. Run `python "${HERMES_SKILL_DIR}/../../scripts/aie.py" persona list` and check the id exists. `tutor` and `qatest` can't be removed this way.
2. Ask in Korean for explicit confirmation, explaining the two options:
   - **보관 삭제(기본)**: Bot·대화·루틴은 삭제, 설정 파일은 `personas/_removed/`에 보관, 학습 기록은 유지
   - **완전 삭제**: 설정 파일과 그 대상의 학습 기록까지 모두 삭제
3. Only after a clear yes run `python "${HERMES_SKILL_DIR}/../../scripts/aie.py" persona remove <id> --yes` (add `--purge` for 완전 삭제).
4. Report the result lines briefly in Korean.

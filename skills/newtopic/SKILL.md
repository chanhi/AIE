---
name: newtopic
description: "Use when the learner types /newtopic [topic]. Close current topic and open a new one."
---
# /newtopic [topic] — switch to a new topic

1. If a topic is ongoing, end it first following **"Ending a topic"** in `english-chat-core` with reason `newtopic`,
   but keep the Tutor summary to 2 lines (잘한 표현 / 고칠 점 one line each).
2. Choose the new topic:
   - Learner gave one after `/newtopic` (Korean or English) → use it.
   - Otherwise run `python "${HERMES_SKILL_DIR}/../../scripts/aie.py" topic suggest <your persona id>` and build a specific, personal angle on that theme
     (use what you know about the learner from memory).
3. Open the new topic in character, no Tutor section:
   `💬 <Name>: <1–2 sentences, ends with a question>`

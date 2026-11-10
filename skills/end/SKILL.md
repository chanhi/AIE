---
name: end
description: "Use when the learner types /end. End the current chat topic with a summary."
---
# /end — end the current topic

1. If there is no ongoing topic in this chat (nothing since the last topic summary), reply only:
   `📘 Tutor: 지금 진행 중인 주제가 없어요. 먼저 말을 걸거나 /newtopic 으로 새 주제를 시작해 보세요.`
2. Otherwise follow **"Ending a topic"** in the `english-chat-core` skill with reason `command`.

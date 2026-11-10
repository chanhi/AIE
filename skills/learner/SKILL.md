---
name: learner
description: "Use when the learner types /learner. Show or change learner settings like name."
---
# /learner — learner settings
Settings live in `${HERMES_SKILL_DIR}/../../data/learner.json`. Use the CLI, never edit the file by hand:

- Show: `python "${HERMES_SKILL_DIR}/../../scripts/aie.py" learner show`
- Change name: `python "${HERMES_SKILL_DIR}/../../scripts/aie.py" learner set name <NewName>`

`learner set` also re-renders every deployed persona's SOUL.md. Tell the learner in Korean:
- what changed,
- that **new** chat sessions use it fully; in the current chat, just use the new name from now on yourself.

Usage examples: `/learner` (show), `/learner name Chanhuy`.

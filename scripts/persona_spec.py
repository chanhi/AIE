"""Validate a new-persona spec (JSON from the /new-persona skill) and render persona.toml.

Stdlib only. The spec is forgiving (defaults fill gaps); every problem is reported at once
in Korean so the Tutor bot can relay it to the learner.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESERVED_IDS = {"default", "tutor", "qatest", "main", "root"}
LEVELS = ("A2", "B1", "B2", "C1")
TICKS = ("15m", "30m", "1h")
PERSONA_FIELDS = ("age", "gender", "origin", "accent", "occupation", "traits", "interests",
                  "speech_style", "feedback_focus", "topic_themes")
LIST_FIELDS = ("traits", "interests", "topic_themes")
DEFAULT_SCHEDULE = {"enabled": True, "idle_after_topic_end_h": 3, "active_window": "08:00-18:00",
                    "max_openers_per_day": 2, "stale_active_close_h": 24, "tick": "30m"}
DEFAULT_MODEL = {"provider": "openai-codex", "model": "gpt-6.1-sol"}


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def validate(spec: dict, existing_ids: set[str], existing_profiles: set[str],
             providers: set[str] | None) -> tuple[dict, list[str]]:
    errs: list[str] = []
    if not isinstance(spec, dict):
        return {}, ["spec는 JSON 객체여야 해요"]

    name = str(spec.get("display_name") or "").strip()
    if not name:
        errs.append("display_name(이름)이 비어 있어요")
    pid = str(spec.get("id") or slugify(name))
    if not re.fullmatch(r"[a-z][a-z0-9]{1,23}", pid):
        errs.append(f"id '{pid}'는 영문 소문자로 시작하는 2~24자 영숫자여야 해요")
    elif pid in RESERVED_IDS:
        errs.append(f"id '{pid}'는 예약어라 쓸 수 없어요")
    elif pid in existing_ids or pid in existing_profiles:
        errs.append(f"id '{pid}'는 이미 있어요 (다른 id를 정해 주세요)")

    relation = str(spec.get("relation") or "").strip()
    if not relation:
        errs.append("relation(관계)이 비어 있어요")

    level = str(spec.get("level") or "B1").upper()
    if level not in LEVELS:
        errs.append(f"level '{level}'은 {', '.join(LEVELS)} 중 하나여야 해요")

    persona_in = spec.get("persona") or {}
    persona: dict = {}
    for f in PERSONA_FIELDS:
        v = persona_in.get(f)
        if f in LIST_FIELDS:
            if isinstance(v, str):
                v = [x.strip() for x in v.split(",") if x.strip()]
            if not v or not isinstance(v, list):
                errs.append(f"persona.{f}(목록)가 비어 있어요")
                continue
            persona[f] = [str(x) for x in v]
        else:
            if v in (None, ""):
                errs.append(f"persona.{f}가 비어 있어요")
                continue
            persona[f] = int(v) if f == "age" and str(v).isdigit() else str(v)
    if "age" in persona and not (isinstance(persona["age"], int) and 16 <= persona["age"] <= 90):
        errs.append("persona.age는 16~90 사이 숫자여야 해요")
    if len(persona.get("topic_themes", [])) < 3:
        errs.append("persona.topic_themes는 3개 이상이어야 해요 (주제 다양성)")

    sch = {**DEFAULT_SCHEDULE, **(spec.get("schedule") or {})}
    win = str(sch["active_window"])
    m = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)-([01]\d|2[0-3]):([0-5]\d)", win)
    if not m or win.split("-")[0] == win.split("-")[1]:
        errs.append(f"schedule.active_window '{win}'는 HH:MM-HH:MM 형식이어야 해요 (예: 08:00-18:00)")
    for key, lo, hi in (("idle_after_topic_end_h", 0.5, 72), ("stale_active_close_h", 1, 168),
                        ("max_openers_per_day", 0, 10)):
        try:
            val = float(sch[key])
            if not lo <= val <= hi:
                raise ValueError
            sch[key] = int(val) if key == "max_openers_per_day" or val.is_integer() else val
        except (TypeError, ValueError):
            errs.append(f"schedule.{key}는 {lo}~{hi} 범위 숫자여야 해요")
    if str(sch["tick"]) not in TICKS:
        errs.append(f"schedule.tick은 {', '.join(TICKS)} 중 하나여야 해요")
    sch["enabled"] = bool(sch.get("enabled", True))

    model = {**DEFAULT_MODEL, **(spec.get("model") or {})}
    if providers is not None and model["provider"] not in providers:
        errs.append(f"model.provider '{model['provider']}'는 로그인된 provider가 아니에요 "
                    f"(사용 가능: {', '.join(sorted(providers)) or '없음'})")
    if not str(model.get("model") or "").strip():
        errs.append("model.model이 비어 있어요")

    description = str(spec.get("description") or
                      f"{name}, the learner's {relation}, for English chat practice ({level}).")
    cfg = {
        "id": pid, "display_name": name, "relation": relation, "level": level,
        "description": description, "template": "partner",
        "persona": persona,
        "model": {"provider": str(model["provider"]), "model": str(model["model"])},
        "memory": {"enabled": bool((spec.get("memory") or {}).get("enabled", True))},
        "schedule": sch,
    }
    return cfg, errs


# ---------------------------------------------------------------- TOML writer (subset we need)
def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    return json.dumps(str(v), ensure_ascii=False)  # JSON string escaping is valid TOML basic string


def to_toml(cfg: dict) -> str:
    lines = ["# Generated by /new-persona (aie.py persona create). Safe to edit; then run:",
             "#   python scripts/aie.py persona init-soul <id> --force && python scripts/aie.py persona deploy <id>"]
    for k, v in cfg.items():
        if not isinstance(v, dict):
            lines.append(f"{k} = {_toml_value(v)}")
    for k, v in cfg.items():
        if isinstance(v, dict):
            lines.append(f"\n[{k}]")
            lines.extend(f"{kk} = {_toml_value(vv)}" for kk, vv in v.items())
    return "\n".join(lines) + "\n"

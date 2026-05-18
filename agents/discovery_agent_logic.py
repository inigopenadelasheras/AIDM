import json
import os
import re
from pathlib import Path
from typing import Any

import yaml
from crewai import Agent, Crew, Process, Task
from dotenv import load_dotenv

from utils import (
    FieldUpdate,
    LIST_FIELDS,
    ProblemScopeUpdateRequest,
    TEXT_FIELDS,
    update_problem_scope_tool,
    load_problem_case,
    AGENTS_FILE
)

load_dotenv(".env")
os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["CREWAI_TELEMETRY_OPT_OUT"] = "true"


def _recent_chat_transcript(chat_history: list[dict[str, str]] | None, max_messages: int = 6) -> str:
    if not chat_history:
        return ""

    recent_messages = chat_history[-max_messages:]
    lines: list[str] = []
    for message in recent_messages:
        role = message.get("role", "user")
        content = (message.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _get_pending_fields(problem_case: dict[str, Any]) -> list[str]:
    pending: list[str] = []
    for field_key, field_data in problem_case.items():
        if field_key == "status":
            continue
        if not isinstance(field_data, dict) or "value" not in field_data:
            continue

        value = field_data["value"]
        if isinstance(value, str) and not value.strip():
            pending.append(field_key)
        elif isinstance(value, list) and len(value) == 0:
            pending.append(field_key)
        elif value is None:
            pending.append(field_key)

    dynamic_missing: list[str] = []
    for field_key in pending:
        field_data = problem_case.get(field_key, {})
        description = (field_data.get("description") or "").strip() if isinstance(field_data, dict) else ""
        if description:
            dynamic_missing.append(f"{field_key}: {description}")
        else:
            dynamic_missing.append(field_key)

    return dynamic_missing  


def _extract_json_object(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return "{}"
    return cleaned[start : end + 1]


def _parse_plan(raw_output: str, allowed_fields: set[str]) -> dict[str, Any]:
    parsed: dict[str, Any] = {"updates": [], "assistant_reply": "", "update_status": None}
    try:
        payload = json.loads(_extract_json_object(raw_output))
    except Exception:
        return parsed

    updates = payload.get("updates")
    if isinstance(updates, list):
        safe_updates: list[dict[str, Any]] = []
        for upd in updates:
            if not isinstance(upd, dict):
                continue
            field_key = upd.get("field_key")
            operation = upd.get("operation", "replace")
            value = upd.get("value")
            if field_key not in allowed_fields:
                continue
            if operation not in {"replace", "append", "merge"}:
                continue
            if value is None:
                continue
            safe_updates.append({"field_key": field_key, "value": value, "operation": operation})
        parsed["updates"] = safe_updates

    assistant_reply = payload.get("assistant_reply")
    if isinstance(assistant_reply, str):
        parsed["assistant_reply"] = assistant_reply.strip()

    update_status = payload.get("update_status")
    if update_status in {"pending fields", "completed"}:
        parsed["update_status"] = update_status

    return parsed


def _apply_plan(plan: dict[str, Any]) -> None:
    updates: list[FieldUpdate] = [FieldUpdate(**upd) for upd in plan.get("updates", [])]
    request = ProblemScopeUpdateRequest(
        updates=updates,
        update_status=plan.get("update_status"),
    )
    update_problem_scope_tool(request)

# Fallback
def _sync_status_with_content() -> None:
    problem_case = load_problem_case()
    pending = _get_pending_fields(problem_case)
    expected_status = "completed" if not pending else "pending fields"
    if problem_case.get("status") == expected_status:
        return

    request = ProblemScopeUpdateRequest(updates=[], update_status=expected_status)
    update_problem_scope_tool(request)


def _build_assistant_reply(
    problem_case_before: dict[str, Any],
    problem_case_after: dict[str, Any],
    llm_reply: str = "",
) -> str:
    pending = _get_pending_fields(problem_case_after)
    completed_now = problem_case_after.get("status") == "completed" and not pending

    # Cierre determinista: cuando el caso está completo no dependemos del texto del LLM.
    if completed_now:
        return "Perfecto, ya tengo todo lo que necesitaba. El discovery ha quedado completado. Ahiora voy a analizar toda la información para proponerte una estructura de solución."

    if llm_reply.strip():
        return llm_reply.strip()

    # Fallback basado en contenido: si el LLM ha fallado dando una reply, indicamos qué campos han cambiado y qué falta.
    # Este fallback no sirve de mucho, habria que quitarlo
    changed_fields: list[str] = []
    for field_key, field_data in problem_case_after.items():
        if field_key == "status" or not isinstance(field_data, dict):
            continue

        before_value = problem_case_before.get(field_key, {}).get("value")
        after_value = field_data.get("value")
        if before_value != after_value:
            changed_fields.append(field_key)

    if not pending:
        if changed_fields:
            return (
                "Perfecto. He actualizado el contexto del caso y ya tenemos todos los campos "
                "necesarios para pasar a la siguiente fase de análisis."
            )
        return "El contexto ya estaba completo. Si quieres, pasamos al diseño de solución."

    if changed_fields:
        updated_list = ", ".join(changed_fields[:4])
        return (
            f"He actualizado la información en: {updated_list}. "
            "Para terminar el alcance, necesito que me confirmes algunos datos pendientes."
        )

    first_pending = pending[0]
    field_meta = problem_case_after.get(first_pending, {})
    next_question = field_meta.get("description") or f"¿Puedes aportar más detalle sobre {first_pending}?"
    return f"Gracias, ya tengo ese contexto. Para avanzar, necesito este dato: {next_question}"


def _propose_plan_with_agent(user_prompt: str, chat_history: list[dict[str, str]] | None) -> dict[str, Any]:
    allowed_fields = set(TEXT_FIELDS) | set(LIST_FIELDS)
    model_name = os.getenv("BIG_MODEL", "").strip()
    if not model_name:
        return {"updates": [], "assistant_reply": "", "update_status": None}

    if not AGENTS_FILE.exists():
        return {"updates": [], "assistant_reply": "", "update_status": None}

    with open(AGENTS_FILE, "r", encoding="utf-8") as f:
        agents_config = yaml.safe_load(f) or {}

    agent_data = agents_config.get("discovery_agent", {})
    role = agent_data.get("role")
    goal = agent_data.get("goal")
    backstory = agent_data.get("backstory")

    problem_case = load_problem_case()
    pending = _get_pending_fields(problem_case)
    print(f"Campos pendientes detectados: {pending}")
    transcript = _recent_chat_transcript(chat_history)
    current_json = json.dumps(problem_case, ensure_ascii=False)

    discovery_agent = Agent(
        role=role,
        goal=goal,
        backstory=backstory,
        llm=model_name,
        verbose=False,
        allow_delegation=False,
    )

    discovery_task = Task(
        description=(
            "Analiza el mensaje del usuario y el historial reciente para proponer actualizaciones sobre problem_case.json. "
            f"Mensaje actual: '{user_prompt}'. "
            f"Historial reciente:\n{transcript}\n"
            f"Estado actual del JSON: {current_json}. "
            f"Campos válidos: {sorted(allowed_fields)}. "
            f"Campos pendientes y missing information ahora: {pending}. "
            "Devuelve EXCLUSIVAMENTE un JSON válido, sin markdown ni texto extra, con este esquema exacto: "
            "{\"updates\": [{\"field_key\": \"...\", \"value\": \"...\" o [\"...\"], \"operation\": \"replace\"|\"append\"|\"merge\"}], \"assistant_reply\": \"...\", \"update_status\": \"pending fields\"|\"completed\"|null}. "
            "No inventes campos fuera de los permitidos. "
            "Intenta ser un poco explicativo a la hora de rellenar el \"value\" de cada campo, evitando pabras vacías o genéricas, para que el caso se vaya completando de forma clara."
            "Si no hay cambios claros, usa updates vacio. "
            "Regla de cierre: si tras tus updates no queda ningun campo pendiente, usa update_status='completed' y assistant_reply sin preguntas de seguimiento."
        ),
        expected_output="JSON válido para actualizar problem_case.",
        agent=discovery_agent,
    )

    crew = Crew(
        agents=[discovery_agent],
        tasks=[discovery_task],
        process=Process.sequential,
    )

    result = crew.kickoff()
    raw_output = getattr(result, "raw", str(result))
    parsed_output = _parse_plan(raw_output, allowed_fields)

    return parsed_output


def run_agent(user_prompt, chat_history: list[dict[str, str]] | None = None):
    problem_case_before = load_problem_case()
    
    if problem_case_before.get("status") == "completed":
        return _build_assistant_reply(problem_case_before, problem_case_before, "")

    plan: dict[str, Any] = {"updates": [], "assistant_reply": "", "update_status": None}
    try:
        plan = _propose_plan_with_agent(user_prompt, chat_history)
    except Exception:
        # Si falla el LLM o CrewAI, se mantiene flujo de fallback determinista.
        plan = {"updates": [], "assistant_reply": "", "update_status": None}

    if plan.get("updates") or plan.get("update_status") is not None:
        try:
            _apply_plan(plan)
        except Exception:
            # Evita romper la conversación por un update inválido.
            pass

    # Actualiza el status del caso según los campos pendientes, para mantener consistencia aunque el LLM no lo haya hecho bien.
    _sync_status_with_content()
    problem_case_after = load_problem_case()
    
    just_completed = (
        problem_case_before.get("status") != "completed"
        and problem_case_after.get("status") == "completed"
    )
    llm_reply = "" if just_completed else plan.get("assistant_reply", "")
    
    return _build_assistant_reply(problem_case_before, problem_case_after, llm_reply)

import json
from pathlib import Path
from typing import Any
from typing import List, Literal, Optional

from pydantic import BaseModel, Field
from crewai import Agent


LIST_FIELDS = {"evidencias"}
TEXT_FIELDS = {
    "nombre_del_cliente",
    "tipo_de_servicio",
    "objetivo_del_proyecto",
    "modelo_de_despliegue",
    "cloud_provider",
    "tipo_de_arquitectura",
    "herramienta_de_visualizacion",
    "enfoque_ai",
    "integration_scope",
}
VALID_STATUSES = {"pending fields", "completed"}
PROBLEM_CASE_PATH = Path("data_structures/problem_case.json")
AGENTS_FILE = Path("data_structures/agents.yaml")

def load_problem_case() -> dict[str, Any]:
    with open(PROBLEM_CASE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)
    
def _make_agent(key: str, agents_config, model_name) -> Agent:
    data = agents_config.get(key, {})
    return Agent(
        role=data.get("role"),
        goal=data.get("goal"),
        backstory=data.get("backstory"),
        llm=model_name,
        verbose=False,
        allow_delegation=False,
    )

# --------------- Utils para el Discovery Agent ---------------

class FieldUpdate(BaseModel):
    field_key: str = Field(
        description="Clave del campo a actualizar en el JSON problem_case; debe existir y no se pueden crear campos nuevos."
    )
    value: str | List[str] = Field(
        description="Texto o lista de textos a usar para la actualización del campo."
    )
    operation: Literal["replace", "append", "merge"] = Field(
        default="replace",
        description="Tipo de operación sobre el campo.",
    )


class ProblemScopeUpdateRequest(BaseModel):
    name: str = "update_problem_scope_tool"
    description: str = (
        "Actualiza campos específicos en problem_case.json relacionados con el alcance del problema. "
        "Argumentos: updates (lista de objetos con field_key, value y operation), "
        "update_status (nuevo valor del campo status si se desea actualizar). "
        "IMPORTANTE: Solo actualiza campos relacionados con el alcance del problema, "
        "no modifiques otros campos ni la estructura general del JSON."
    )
    updates: List[FieldUpdate] = Field(
        description="Lista de actualizaciones a aplicar sobre problem_case.json."
    )
    update_status: Optional[Literal["pending fields", "completed"]] = Field(
        default=None,
        description="Nuevo valor de status cuando proceda.",
    )

def _normalize_update_value(field_key: str, value: str | List[str], operation: str) -> str | List[str]:
    if field_key in TEXT_FIELDS:
        if operation != "replace":
            raise ValueError(f"El campo {field_key} es de texto y solo permite operation='replace'.")
        if not isinstance(value, str):
            raise ValueError(f"El campo {field_key} debe actualizarse con texto, no con lista.")

        normalized = value.strip()
        if not normalized:
            raise ValueError(f"El campo {field_key} no puede actualizarse con texto vacío.")
        return normalized

    if field_key in LIST_FIELDS:
        items = value if isinstance(value, list) else [value]
        normalized_items = [item.strip() for item in items if item.strip()]
        if not normalized_items:
            raise ValueError(f"El campo {field_key} no puede actualizarse con una lista vacía.")
        return normalized_items

    raise ValueError(f"El campo {field_key} no está contemplado en la configuración de la tool.")


def update_problem_scope_tool(request: ProblemScopeUpdateRequest) -> dict:
    with open(PROBLEM_CASE_PATH, "r", encoding="utf-8") as f:
        problem_case = json.load(f)

    for upd in request.updates:
        field_key = upd.field_key

        # Validacion de que el campo existe en el JSON y sigue la estructura esperada
        if field_key not in problem_case:
            raise ValueError(f"Campo no válido: {field_key}")

        if field_key == "status":
            raise ValueError("El campo 'status' no puede actualizarse dentro de 'updates'; usa 'update_status'.")

        field_data = problem_case[field_key]
        if not isinstance(field_data, dict) or "value" not in field_data:
            raise ValueError(f"El campo {field_key} no sigue la estructura esperada con 'value'.")

        normalized_value = _normalize_update_value(field_key, upd.value, upd.operation)
        current_value = problem_case[field_key]["value"]

        if upd.operation == "replace":
            problem_case[field_key]["value"] = normalized_value
            continue

        if not isinstance(current_value, list):
            raise ValueError(f"El campo {field_key} no es una lista.")

        new_items = normalized_value if isinstance(normalized_value, list) else [normalized_value]

        if upd.operation == "append":
            problem_case[field_key]["value"].extend(new_items)
        else:
            merged = current_value[:]
            for item in new_items:
                if item not in merged:
                    merged.append(item)
            problem_case[field_key]["value"] = merged

    if request.update_status is not None:
        if request.update_status not in VALID_STATUSES:
            raise ValueError(f"Estado no válido: {request.update_status}")
        problem_case["status"] = request.update_status

    with open(PROBLEM_CASE_PATH, "w", encoding="utf-8") as f:
        json.dump(problem_case, f, ensure_ascii=False, indent=2)

    return {
        "message": "Problem scope actualizado correctamente",
        "updated_fields": [u.field_key for u in request.updates],
        "status": problem_case["status"],
    }

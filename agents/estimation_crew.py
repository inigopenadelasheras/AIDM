import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Literal

import litellm
from crewai import Agent, Crew, Process, Task
from pydantic import BaseModel

from utils import _make_agent, load_agents_config


def _patch_crewai_union_schema() -> None:
    """
    crewai <=1.14.7 no maneja tipos JSON Schema en formato lista (ej. ['null', 'array']).
    Este patch normaliza esos tipos antes de que lleguen al parser de crewai.
    """
    try:
        import crewai.utilities.pydantic_schema_utils as _su
        _orig = _su._json_schema_to_pydantic_type

        def _patched(json_schema, root_schema, name_=None, enrich_descriptions=True, in_progress=None):
            type_ = json_schema.get("type")
            if isinstance(type_, list):
                non_null = [t for t in type_ if t != "null"]
                if len(non_null) == 1:
                    json_schema = {**json_schema, "type": non_null[0]}
                elif len(non_null) == 0:
                    return type(None)
                else:
                    return Any
            return _orig(json_schema, root_schema, name_=name_,
                         enrich_descriptions=enrich_descriptions, in_progress=in_progress)

        _su._json_schema_to_pydantic_type = _patched
    except Exception:
        pass


_patch_crewai_union_schema()


def _patch_crewai_force_required() -> None:
    """
    crewai <=1.14.7: force_additional_properties_false añade 'required: []'
    aunque 'properties' esté vacío. Groq rechaza ese schema.
    Este patch elimina required=[] de cualquier subschema donde properties esté vacío.
    """
    try:
        import crewai.utilities.pydantic_schema_utils as _su
        _orig = _su.force_additional_properties_false

        def _clean(d: object) -> None:
            if isinstance(d, dict):
                if d.get("required") == [] and not d.get("properties"):
                    d.pop("required")
                for v in d.values():
                    _clean(v)
            elif isinstance(d, list):
                for item in d:
                    _clean(item)

        def _patched(schema: object, _seen: set | None = None) -> object:
            result = _orig(schema, _seen)
            _clean(result)
            return result

        _su.force_additional_properties_false = _patched
    except Exception:
        pass


_patch_crewai_force_required()


class ResumenEjecutivo(BaseModel):
    coste_total_minimo: str
    coste_total_maximo: str
    horizonte_temporal: str
    nivel_confianza: Literal["alto", "medio", "bajo"]
    justificacion_confianza: str


class DesglosePorCategoria(BaseModel):
    licencias_y_herramientas: str
    formacion_y_onboarding: str
    mantenimiento_y_soporte: str
    desarrollo_e_implantacion: str


class ItemInfraestructura(BaseModel):
    servicio: str
    sku: str
    precio_unitario: str
    unidades_estimadas: str
    coste_mensual_estimado: str


class CostEstimationReport(BaseModel):
    resumen_ejecutivo: ResumenEjecutivo
    supuestos: list[str]
    desglose_por_categoria: DesglosePorCategoria
    precio_por_componentes: list[ItemInfraestructura]


class EstimationResult(BaseModel):
    cost_estimation: str
    team_profiles: str


def _format_cost_report(report: CostEstimationReport) -> str:
    r = report.resumen_ejecutivo
    lines = [
        "## Resumen Ejecutivo",
        f"- **Coste total estimado:** {r.coste_total_minimo} – {r.coste_total_maximo}",
        f"- **Horizonte temporal:** {r.horizonte_temporal}",
        f"- **Nivel de confianza:** {r.nivel_confianza.capitalize()} — {r.justificacion_confianza}",
        "",
        "## Supuestos",
    ]
    for supuesto in report.supuestos:
        lines.append(f"- {supuesto}")

    d = report.desglose_por_categoria
    lines += [
        "",
        "## Desglose por Categoría",
        f"**Licencias y herramientas:** {d.licencias_y_herramientas}",
        f"**Formación y onboarding:** {d.formacion_y_onboarding}",
        f"**Mantenimiento y soporte:** {d.mantenimiento_y_soporte}",
        f"**Desarrollo e implantación:** {d.desarrollo_e_implantacion}",
        "",
        "## Precio por Componentes de Infraestructura",
    ]
    for item in report.precio_por_componentes:
        lines.append(
            f"- **{item.servicio}** ({item.sku}): "
            f"{item.precio_unitario} × {item.unidades_estimadas} = {item.coste_mensual_estimado}"
        )
    return "\n".join(lines)


def _resolve_infracost_binary() -> str | None:
    local = Path(__file__).parent.parent / "infracost.exe"
    if local.exists():
        return str(local)
    return shutil.which("infracost")


def _generate_terraform_from_proposal(proposal_context: str, model_name: str) -> str:
    """
    Usa el LLM para generar un Terraform HCL mínimo con los recursos cloud
    mencionados en la propuesta. Infracost parsea este HCL para obtener precios reales.
    """
    try:
        response = litellm.completion(
            model=model_name,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Eres un experto en Terraform. Tu tarea es generar un archivo Terraform HCL mínimo "
                        "con los recursos cloud mencionados en la propuesta de solución. "
                        "Reglas estrictas:\n"
                        "- Usa valores de placeholder para campos obligatorios "
                        "(name = 'placeholder', resource_group_name = 'rg-placeholder', location = 'West Europe', etc.)\n"
                        "- No uses variables, módulos, data sources ni locals\n"
                        "- Incluye el bloque terraform{} y el bloque provider correspondiente\n"
                        "- Para azurerm: subscription_id = '00000000-0000-0000-0000-000000000000' y features {}\n"
                        "- Solo incluye recursos que tengan un tipo de recurso Terraform conocido\n"
                        "- Incluye como máximo 8-10 recursos, priorizando los más costosos y centrales\n"
                        "- Ignora servicios SaaS sin recurso Terraform (Power BI, Microsoft Teams, etc.)\n"
                        "- Devuelve ÚNICAMENTE el código HCL sin explicaciones ni bloques markdown"
                    ),
                },
                {
                    "role": "user",
                    "content": f"Genera el Terraform para esta propuesta de solución:\n\n{proposal_context}",
                },
            ],
            temperature=0.1,
        )
        raw = response.choices[0].message.content or ""
        cleaned = re.sub(r"```(?:hcl|terraform)?\n?", "", raw).replace("```", "").strip()
        return cleaned
    except Exception as e:
        print(f"[estimation_crew] Error generando Terraform desde propuesta: {e}")
        return ""


def _run_infracost_breakdown(terraform_hcl: str, binary: str, api_key: str) -> str | None:
    """
    Escribe el HCL en un directorio temporal y ejecuta infracost breakdown.
    Retorna el texto del scan summary como string, o None si falla.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tf_path = os.path.join(tmpdir, "main.tf")
        with open(tf_path, "w", encoding="utf-8") as f:
            f.write(terraform_hcl)

        env = {**os.environ, "INFRACOST_API_KEY": api_key}
        try:
            result = subprocess.run(
                [binary, "breakdown", "--path", tmpdir, "--no-color"],
                capture_output=True,
                timeout=120,
                env=env,
            )
        except subprocess.TimeoutExpired:
            print("[estimation_crew] infracost breakdown timeout (120s).")
            return None
        except Exception as e:
            print(f"[estimation_crew] infracost breakdown error: {e}")
            return None

        stdout_text = result.stdout.decode(errors="replace").strip()
        stderr_text = result.stderr.decode(errors="replace").strip()

        if result.returncode != 0:
            print(f"[estimation_crew] infracost breakdown falló (rc={result.returncode}): {stderr_text[:300]}")
            return None

        if not stdout_text:
            print("[estimation_crew] infracost breakdown no produjo output.")
            return None

        print(f"[estimation_crew] Infracost scan completado:\n{stdout_text[:400]}")
        return stdout_text


def _load_team_costs_context() -> str:
    csv_path = Path(__file__).parent.parent / "bd" / "costes_perfil.csv"
    if not csv_path.exists():
        return ""
    lines = csv_path.read_text(encoding="utf-8").strip().splitlines()
    return "\n".join(line.strip() for line in lines if line.strip())


def run_estimation_crew(
    proposal_context: str,
    model_name: str,
    tools: list | None = None,
) -> EstimationResult:
    """
    Ejecuta la crew de estimación de costos y perfiles de equipo.

    Pre-fase (Python puro): genera Terraform desde la propuesta → infracost breakdown → precios reales.
    Fase CrewAI: report_writer_agent (sin tools, output_pydantic) genera CostEstimationReport.

    `proposal_context` es el output serializado de ProposalResult.as_combined_context().
    """
    agents_config = load_agents_config()

    # --- Pre-fase: obtener precios reales via Infracost subprocess ---
    api_key = os.getenv("INFRACOST_API_KEY", "")
    binary = _resolve_infracost_binary()
    infracost_prices: str | None = None

    if api_key and binary:
        terraform_hcl = _generate_terraform_from_proposal(proposal_context, model_name)
        if terraform_hcl.strip():
            infracost_prices = _run_infracost_breakdown(terraform_hcl, binary, api_key)
            if infracost_prices:
                print("[estimation_crew] Precios reales obtenidos de Infracost.")
            else:
                print("[estimation_crew] infracost breakdown no produjo precios — usando estimación del LLM.")
        else:
            print("[estimation_crew] No se pudo generar Terraform — usando estimación del LLM.")
    else:
        print("[estimation_crew] Infracost no disponible — usando estimación del LLM.")

    team_costs_table = _load_team_costs_context()

    # --- Fase CrewAI: report writer + team builder (ambos sin tools) ---
    agent_data = agents_config.get("cost_estimation_agent", {})
    report_writer_agent = Agent(
        role=agent_data.get("role"),
        goal=agent_data.get("goal"),
        backstory=agent_data.get("backstory"),
        llm=model_name,
        tools=[],
        verbose=False,
        allow_delegation=False,
    )
    team_builder = _make_agent("team_profiles_advisor", agents_config, model_name)

    pricing_note = (
        f"Resumen de costos reales obtenido de Infracost (basado en infraestructura generada desde la propuesta):\n{infracost_prices}"
        if infracost_prices else
        "No hay precios reales disponibles. Usa estimaciones razonables e indica 'estimado' en el campo sku."
    )

    cost_report_task = Task(
        description=(
            "A partir de la propuesta de solución y los precios indicados, genera un informe de estimación de costos estructurado. "
            f"{pricing_note}\n"
            "Para los supuestos: si te falta información, indícalo como "
            "'Por determinar, requiere [dato X]' o 'Se asume [dato X]' — nunca inventes datos críticos. "
            "Propuesta de solución:\n"
            f"{proposal_context}"
        ),
        expected_output="Informe estructurado de estimación con resumen ejecutivo, supuestos, desglose por categorías y tabla de infraestructura.",
        output_pydantic=CostEstimationReport,
        agent=report_writer_agent,
    )

    team_building_task = Task(
        description=(
            "A partir de la propuesta de solución y la descripción del problema, identifica los perfiles profesionales necesarios para llevar a cabo la implementación de la solución propuesta. "
            "Considera roles como arquitecto de datos, ingeniero de datos, científico de datos, analista de BI, entre otros. "
            "Proporciona una descripción detallada de cada perfil profesional identificado, incluyendo sus responsabilidades clave y las habilidades requeridas. "
            "Esta es la solución propuesta sobre la que debes identificar los perfiles profesionales necesarios:\n"
            f"{proposal_context}"
        ),
        expected_output="Un informe detallado que identifique los perfiles profesionales necesarios para la implementación de la solución propuesta, incluyendo una descripción de cada rol (responsabilidades clave y habilidades requeridas).",
        agent=team_builder,
    )

    team_cost_task = Task(
        description=(
            "A partir de los perfiles de equipo identificados en la tarea anterior, "
            "genera una estimación de coste del equipo. "
            "Para cada perfil, indica: nivel recomendado (Junior/Middle/Senior), "
            "horas estimadas al mes y coste mensual calculado con las tarifas de referencia. "
            "Finaliza con el coste total mensual del equipo.\n"
            f"Tarifas de referencia (€/hora):\n{team_costs_table}"
        ),
        expected_output=(
            "Tabla de estimación de costes del equipo: perfil, nivel recomendado, horas/mes, coste mensual. "
            "Coste total mensual del equipo al final."
        ),
        context=[team_building_task],
        agent=team_builder,
    ) if team_costs_table else None

    crew_tasks: list[Task] = [cost_report_task, team_building_task]
    if team_cost_task:
        crew_tasks.append(team_cost_task)

    crew = Crew(
        agents=[report_writer_agent, team_builder],
        tasks=crew_tasks,
        process=Process.sequential,
        cache=False,
    )
    result = crew.kickoff()

    # Extraer output de costos: preferir pydantic validado, fallback a raw
    report_pydantic = getattr(getattr(cost_report_task, "output", None), "pydantic", None)
    if isinstance(report_pydantic, CostEstimationReport):
        cost_estimation = _format_cost_report(report_pydantic)
    else:
        raw_obj = getattr(cost_report_task, "output", None)
        cost_estimation = getattr(raw_obj, "raw", "") or str(raw_obj or "")

    team_obj = getattr(team_building_task, "output", None)
    team_profiles = getattr(team_obj, "raw", "") or str(team_obj or "")

    if team_cost_task:
        cost_obj = getattr(team_cost_task, "output", None)
        team_cost_text = getattr(cost_obj, "raw", "") or str(cost_obj or "")
        if team_cost_text:
            team_profiles = team_profiles + "\n\n---\n\n## Estimación de Coste del Equipo\n\n" + team_cost_text

    if not (cost_estimation and team_profiles):
        raise RuntimeError(getattr(result, "raw", "Error: estimation crew produjo outputs incompletos."))

    return EstimationResult(
        cost_estimation=cost_estimation,
        team_profiles=team_profiles,
    )

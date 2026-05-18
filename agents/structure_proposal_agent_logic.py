import json
import os

import yaml
from crewai import Agent, Crew, Process, Task
from dotenv import load_dotenv

from agents.discovery_agent_logic import _recent_chat_transcript
from utils import load_problem_case, AGENTS_FILE

load_dotenv(".env")
os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["CREWAI_TELEMETRY_OPT_OUT"] = "true"

def build_structure_proposal(problem_case, chat_history: list[dict[str, str]] | None):
    # Por simplicidad, en este ejemplo solo usamos el problem_case.
    problem_case = load_problem_case()
    transcript = _recent_chat_transcript(chat_history)
    
    model_name = os.getenv("BIG_MODEL", "").strip()
    if not model_name:
        return "No hay modelo configurado en .env (variable MODEL)."

    with open(AGENTS_FILE, "r", encoding="utf-8") as f:
        agents_config = yaml.safe_load(f) or {}
    
    agent_data = agents_config.get("structure_proposal_agent", {})

    structure_proposal_agent = Agent(
        role = agent_data.get("role"),
        goal = agent_data.get("goal"),
        backstory = agent_data.get("backstory"),
        llm = model_name,
        verbose=False,
        allow_delegation=False,
    )

    structure_proposal_task = Task(
        description=(
            "A partir de el JSON con el contexto del proyecto, analiza el caso, detecta restricciones y objetivos, y propon una arquitectura coherente"
            "recomienda plataformas/servicios, justifica cada decisión y explicita supuestos cuando falten datos."
            "Tambien dispones de el historial de el chat para que tengas contexto"
            f"JSON con en Problem case: {problem_case}"
            f"Historial reciente:\n{transcript}\n"
            "La respuesta tiene que ser una estructura fija como 1- Texto con introducción inicial a la propuesta \n 2- Propuesta de Servicios y paltaformas \n 3- Propuesta de arquitectura"
            "Procura redactar la respuesta de una forma legible y bien redactada, sin dibujar ningún diagrama, usando tabulados y de mas cuando sea propio para dar una respuesta facil de leer."
        ),
        expected_output="Una propuesta de estructura de solución detallada, extensa y justificada, siguiendo el formato indicado.",
        agent=structure_proposal_agent
    )

    crew = Crew(
        agents=[structure_proposal_agent],
        tasks=[structure_proposal_task],
        process=Process.sequential
    )
    
    result = crew.kickoff()

    print(getattr(result, "raw", str(result)))
    return getattr(result, "raw", str(result))
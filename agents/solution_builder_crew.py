import os
import re
from html import escape
from pathlib import Path
from bs4 import BeautifulSoup, FeatureNotFound

import yaml
from crewai import Agent, Crew, Process, Task
from dotenv import load_dotenv

from agents.discovery_agent_logic import _recent_chat_transcript
from utils import load_problem_case, AGENTS_FILE, _make_agent

load_dotenv(".env")

SOLUTION_REPORT_PATH = Path("data_structures/solution_builder_report.html")
_SECTION_IDS = {
    "architecture": "content-architecture",
    "governance":   "content-governance",
    "data_ai":      "content-data-ai",
    "bi":           "content-bi",
    "cost_estimation": "content-cost-estimation",
    "team_profiles": "content-team-profiles"
}

COMBINED_RESPONSE = ""
SOLUTION_RESULT = {
    "Propuesta de Arquitectura": "",
    "Propuesta de Gobernanza de Dato e IA": "",
    "Propuesta de Estrategia de Datos e IA": "",
    "Propuesta de Visualización de Datos": "",
    "Estimación de Costos": "",
    "Perfiles Profesionales Necesarios": ""
}

def _parse_html(markup: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(markup, "lxml")
    except FeatureNotFound:
        return BeautifulSoup(markup, "html.parser")

def _md_to_html(text: str) -> str:
    """
    Convert the lightweight markdown that LLMs typically produce into HTML.
    Handles: **bold**, *italic*, `code`, ### headings, bullet/numbered lists,
    blank-line paragraphs and line breaks.  All non-tag content is HTML-escaped.
    """
    if not text or not text.strip():
        return "<p>No se ha generado contenido.</p>"
 
    lines = text.splitlines()
    html_parts: list[str] = []
    in_ul = False
    in_ol = False
 
    def close_lists():
        nonlocal in_ul, in_ol
        if in_ul:
            html_parts.append("</ul>")
            in_ul = False
        if in_ol:
            html_parts.append("</ol>")
            in_ol = False
 
    def inline(s: str) -> str:
        """Apply inline markdown transforms to an already-escaped string."""
        # escape first so we don't double-escape later insertions
        s = escape(s)
        # **bold**
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        # *italic* or _italic_
        s = re.sub(r"\*(.+?)\*",     r"<em>\1</em>", s)
        s = re.sub(r"_(.+?)_",       r"<em>\1</em>", s)
        # `code`
        s = re.sub(r"`(.+?)`",       r"<code>\1</code>", s)
        return s
 
    pending_paragraph: list[str] = []
 
    def flush_paragraph():
        if pending_paragraph:
            html_parts.append("<p>" + "<br>".join(pending_paragraph) + "</p>")
            pending_paragraph.clear()
 
    for line in lines:
        # Headings: ####, ###, ##, #
        heading_match = re.match(r"^(#{1,4})\s+(.*)", line)
        if heading_match:
            close_lists()
            flush_paragraph()
            level = len(heading_match.group(1))
            tag = "h3" if level <= 2 else "h4"
            html_parts.append(f"<{tag}>{inline(heading_match.group(2))}</{tag}>")
            continue
 
        # Horizontal rule
        if re.match(r"^[-*_]{3,}$", line.strip()):
            close_lists()
            flush_paragraph()
            html_parts.append("<hr>")
            continue
 
        # Unordered list item
        ul_match = re.match(r"^[\s]*[-*+]\s+(.*)", line)
        if ul_match:
            flush_paragraph()
            if in_ol:
                html_parts.append("</ol>")
                in_ol = False
            if not in_ul:
                html_parts.append("<ul>")
                in_ul = True
            html_parts.append(f"<li>{inline(ul_match.group(1))}</li>")
            continue
 
        # Ordered list item
        ol_match = re.match(r"^[\s]*\d+[.)]\s+(.*)", line)
        if ol_match:
            flush_paragraph()
            if in_ul:
                html_parts.append("</ul>")
                in_ul = False
            if not in_ol:
                html_parts.append("<ol>")
                in_ol = True
            html_parts.append(f"<li>{inline(ol_match.group(1))}</li>")
            continue
 
        # Blank line → paragraph break
        if not line.strip():
            close_lists()
            flush_paragraph()
            continue
 
        # Normal line
        close_lists()
        pending_paragraph.append(inline(line))
 
    close_lists()
    flush_paragraph()
 
    return "\n".join(html_parts) if html_parts else "<p>No se ha generado contenido.</p>"

def _inject_into_html(
    architecture_output: str,
    governance_output: str,
    data_ai_output: str,
    bi_visualization_output: str,
    cost_estimation_output: str,
    team_profiles_output: str,
) -> None:
    """
    Read the existing static HTML file and replace the content of each
    placeholder <div id="..."> with the rendered agent output.
    Uses BeautifulSoup to parse the DOM correctly — no regex that can bleed
    across nested tags or across tab boundaries.
    The file must already exist; this function never creates it from scratch.
    """

    if not SOLUTION_REPORT_PATH.exists():
        raise FileNotFoundError(
            f"El archivo HTML de plantilla no existe en {SOLUTION_REPORT_PATH}. "
            "Asegúrate de que el fichero solution_builder_report.html esté presente "
            "antes de ejecutar este módulo."
        )

    html = SOLUTION_REPORT_PATH.read_text(encoding="utf-8")
    soup = _parse_html(html)

    replacements = {
        _SECTION_IDS["architecture"]:    _md_to_html(architecture_output),
        _SECTION_IDS["governance"]:      _md_to_html(governance_output),
        _SECTION_IDS["data_ai"]:         _md_to_html(data_ai_output),
        _SECTION_IDS["bi"]:              _md_to_html(bi_visualization_output),
        _SECTION_IDS["cost_estimation"]: _md_to_html(cost_estimation_output),
        _SECTION_IDS["team_profiles"]:   _md_to_html(team_profiles_output),
    }

    for div_id, new_html in replacements.items():
        target = soup.find("div", id=div_id)
        if target is None:
            continue
        # Clear existing children and replace with parsed new content.
        target.clear()
        fragment = _parse_html(new_html)
        # lxml wraps content in <html><body> — grab only the body children
        body = fragment.find("body") or fragment
        for child in list(body.children):
            target.append(child.__copy__())

    SOLUTION_REPORT_PATH.write_text(str(soup), encoding="utf-8")
    




def propose_solution(structure_proposal, problem_case, chat_history: list[dict[str,str]] | None) -> str:

    with open(AGENTS_FILE, "r", encoding="utf-8") as f:
        agents_config = yaml.safe_load(f) or {}
    
    model_name = os.getenv("BIG_MODEL", "").strip()
    if not model_name:
        return "No hay modelo configurado en .env (variable BIG_MODEL)."
    
    
    architect = _make_agent("structure_proposal_agent", agents_config, model_name)
    data_governance = _make_agent("data_governance_agent", agents_config, model_name)
    data_ai_strategist = _make_agent("data_ai_strategist", agents_config, model_name)
    bi_visualization_specialist = _make_agent("bi_visualization_specialist", agents_config, model_name)

    cost_estimator = _make_agent("cost_estimation_agent", agents_config, model_name)
    team_builder = _make_agent("team_profiles_advisor", agents_config, model_name)
    
    architecture_task = Task(
        description=(
            "A partir de la propuesta de la solucion a un proyecto y la propia descripcion del problema, analiza el caso, detecta restricciones y objetivos, y propon una arquitectura coherente"
            "recomienda plataformas/servicios, justifica cada decisión y explicita supuestos cuando falten datos."
            "Tambien dispones de el historial de el chat para que tengas contexto."
            f"- Propuesta de solución:\n{structure_proposal}\n"
            f"- Descripción del problema:\n{problem_case}\n"
            f"- Historial reciente:\n{_recent_chat_transcript(chat_history)}\n"
            "Procura que la respuesta sea detallada y este bien redactada"
        ),
        expected_output="Una propuesta de arquitectura detallada, extensa y justificada, con la siguiente estructura: Arquitectura Propuesta:\n (...). Sin dibujar ninguna tabla ni gráfico, solo texto.",
        agent=architect
    )

    governance_task = Task(
        description = (
            "Analiza el contexto completo del proyecto a partir de la descripción del problema de negocio y la propuesta de solución planteada"
            "A partir de esta información, diseña una propuesta de gobernanza del dato y de inteligencia artificial adaptada al proyecto."
            "Tambien dispones de el historial de el chat para que tengas contexto."
            f"- Propuesta de solución:\n{structure_proposal}\n"
            f"- Descripción del problema:\n{problem_case}\n"
            f"- Historial reciente:\n{_recent_chat_transcript(chat_history)}\n"
        ),
        expected_output = "Texto estructurado que describa la propuesta de gobernanza del dato y AI para el proyecto, incluyendo secciones claras, explicaciones comprensibles y justificación de las decisiones tomadas. Sin dibujar ninguna tabla ni gráfico, solo texto.",
        agent = data_governance
    )
    
    data_ai_task = Task(
        description = (
            "Toma estos inputs como contexto:"
            f"problem case: {problem_case}\n"
            f"estructura propuesta: {structure_proposal}\n"
            "Basándote en el 'probem case' completo y en la propuesta de arquitectura realizada para el problema, realiza lo siguiente:"
            " 1. Análisis Crítico: Evalúa el problema de negocio y la madurez de datos actual."
            " 2. Propuesta de Funcionalidades: Define al menos 3 funcionalidades clave de IA/Data "
            " (ej. Modelos predictivos, RAG con LLMs, Optimización, etc.) que resuelvan el problema."
            " 3. Roadmap Técnico: Por cada funcionalidad, detalla qué fuentes de datos usará, "
            " qué tipo de análisis se aplicará y cómo se integrará en el flujo de trabajo."
            " 4. Valor de Negocio: Explica cómo estas soluciones impactarán en las métricas "
            " de éxito (success_metrics) definidas en el contexto"
        ),
        expected_output = "Texto estructurado que describa la propuesta de estrategia de datos e AI para el proyecto, incluyendo secciones claras, explicaciones comprensibles y justificación de las decisiones tomadas. Sin dibujar ninguna tabla ni gráfico, solo texto.",
        agent = data_ai_strategist
    )

    
    bi_visualization_task = Task(
        description= (
            "Toma estos inputs como contexto:"
            f"problem case: {problem_case}\n"
            f"estructura propuesta: {structure_proposal}\n"
            "Basándote en el 'Client Context' y las soluciones de IA "
            "propuestas anteriormente, desarrolla la estrategia de BI:"
            " 1. Definición de KPIs de Visualización: Traduce las 'success_metrics' en indicadores "
            "visuales concretos (ej. Gauge charts para cumplimiento de objetivos, Heatmaps de ventas)."
            " 2. Diseño de Dashboards: Propón la estructura de al menos 2 dashboards (ej. Dashboard "
            "Ejecutivo y Dashboard de Operaciones Detallado)."
            " 3. User Experience (UX): Especifica quiénes son los 'data_consumers' y cómo deben "
            "interactuar con la información (filtros, drill-downs, alertas)."
            " 4. Stack de BI: Recomienda la herramienta ideal (Power BI, Tableau, Looker, Streamlit) "
            "según las 'technology_constraints' del cliente."
        ),
        expected_output = "Texto estructurado que describa la propuesta de estrategia de visualización de datos para el proyecto, incluyendo secciones claras, explicaciones comprensibles y justificación de las decisiones tomadas. Sin dibujar ninguna tabla ni gráfico, solo texto.",
        agent = bi_visualization_specialist
    )

    first_crew = Crew(
        agents = [architect, data_governance, data_ai_strategist, bi_visualization_specialist],
        tasks = [architecture_task, governance_task, data_ai_task, bi_visualization_task],
        process = Process.sequential
    )

    result = first_crew.kickoff()

    architecture_output_obj = getattr(architecture_task, "output", None)
    governance_output_obj = getattr(governance_task, "output", None)
    data_ai_output_obj = getattr(data_ai_task, "output", None)
    bi_visualization_output_obj = getattr(bi_visualization_task, "output", None)

    architecture_output = getattr(architecture_output_obj, "raw", "") or str(architecture_output_obj or "")
    governance_output = getattr(governance_output_obj, "raw", "") or str(governance_output_obj or "")
    data_ai_output = getattr(data_ai_output_obj, "raw", "") or str(data_ai_output_obj or "")
    bi_visualization_output = getattr(bi_visualization_output_obj, "raw", "") or str(bi_visualization_output_obj or "")


    if not architecture_output and not governance_output and not data_ai_output and not bi_visualization_output:
        return getattr(result, "raw", str(result))
    
    for key, value in [("Propuesta de Arquitectura", architecture_output), ("Propuesta de Gobernanza de Dato e IA", governance_output), ("Propuesta de Estrategia de Datos e IA", data_ai_output), ("Propuesta de Visualización de Datos", bi_visualization_output)]:
        SOLUTION_RESULT[key] = value

    combined_response = ""
    for key in SOLUTION_RESULT:
        combined_response += f"\n\n {key}\n{SOLUTION_RESULT[key].strip()}"
    combined_response = combined_response.strip()
    
    
    cost_estimation_task = Task(
        description = (
            "A partir de la propuesta de solución y la descripción del problema, realiza una estimación de costos para la implementación de la solución propuesta."
            "Considera costos de infraestructura, licencias, desarrollo, mantenimiento y cualquier otro costo relevante."
            "Proporciona un desglose detallado de los costos estimados y justifica cada partida presupuestaria."
            "Esta es la solucion propuesta sobre la que debes hacer la estimacion de costos:\n"
            f"{combined_response}"
        ),
        expected_output = "Un informe detallado de la estimación de costos para la implementación de la solución propuesta, incluyendo un desglose por categorías (infraestructura, licencias, desarrollo, mantenimiento, etc.) y una justificación para cada partida presupuestaria.",
        agent = cost_estimator
    )
    
    team_building_task = Task(
        description = (
            "A partir de la propuesta de solución y la descripción del problema, identifica los perfiles profesionales necesarios para llevar a cabo la implementación de la solución propuesta."
            "Considera roles como arquitecto de datos, ingeniero de datos, científico de datos, analista de BI, entre otros."
            "Proporciona una descripción detallada de cada perfil profesional identificado, incluyendo sus responsabilidades clave y las habilidades requeridas."
            "Esta es la solucion propuesta sobre la que debes identificar los perfiles profesionales necesarios:\n"
            f"{combined_response}"
        ),
        expected_output = "Un informe detallado que identifique los perfiles profesionales necesarios para la implementación de la solución propuesta, incluyendo una descripción de cada rol (responsabilidades clave y habilidades requeridas).",
        agent = team_builder
    )
    
    second_crew = Crew(
        agents = [cost_estimator, team_builder],
        tasks = [cost_estimation_task, team_building_task],
        process = Process.sequential
    )
    
    second_result = second_crew.kickoff()
    
    cost_estimation_output_obj = getattr(cost_estimation_task, "output", None)
    team_building_output_obj = getattr(team_building_task, "output", None)
    
    cost_estimation_output = getattr(cost_estimation_output_obj, "raw", "") or str(cost_estimation_output_obj or "")
    team_building_output = getattr(team_building_output_obj, "raw", "") or str(team_building_output_obj or "")
    
    if cost_estimation_output and team_building_output:
        for key, value in [("Estimación de Costos", cost_estimation_output), ("Perfiles Profesionales Necesarios", team_building_output)]:
            SOLUTION_RESULT[key] = value
        combined_response += f"\n\n Estimación de Costos\n{cost_estimation_output.strip()}\n\n Perfiles Profesionales Necesarios\n{team_building_output.strip()}"
    else:
        return getattr(second_result, "raw", str(second_result))
    
    

    _inject_into_html(
        architecture_output,
        governance_output,
        data_ai_output,
        bi_visualization_output,
        cost_estimation_output,
        team_building_output
    )
    
    COMBINED_RESPONSE = combined_response
    return SOLUTION_RESULT
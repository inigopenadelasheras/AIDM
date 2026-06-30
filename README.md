# AIDM — AI Discovery Manager

Sistema inteligente de propuesta y toma de decisión de soluciones para proyectos de Data & AI. Es una PoC conversacional que captura requisitos de cliente mediante una entrevista guiada por IA y genera automáticamente una propuesta técnica detallada en formato HTML, incluyendo arquitectura, gobernanza, roadmap, costos y perfiles de equipo.

---

## Requisitos previos


- **Python** - 3.12 (Probado con 3.12.6)
- **pip**
- **Git**
- **Cuenta Groq** - Para obtener la API key gratuita

> El proyecto usa **Groq** como proveedor de LLMs (gratuito con límites generosos). Crea una cuenta en [console.groq.com](https://console.groq.com) y genera una API key antes de continuar.

---

## Instalación paso a paso

### 1. Clonar el repositorio

```bash
git clone <URL-del-repositorio>
cd AIDM
```

### 2. Crear y activar el entorno virtual

**Windows (PowerShell):**
```powershell
python -m venv aidmenv
.\aidmenv\Scripts\Activate.ps1
```

**Windows (CMD):**
```cmd
python -m venv aidmenv
aidmenv\Scripts\activate.bat
```

**Linux / macOS:**
```bash
python3.12 -m venv aidmenv
source aidmenv/bin/activate
```

Cuando el entorno está activado, verás `(aidmenv)` al inicio del prompt.

### 3. Instalar dependencias

Con el entorno virtual activado:

```bash
pip install -r requirements.txt
```

Las librerías que se instalan son:

| Librería | Propósito |
|---|---|
| `streamlit` | Interfaz de chat web |
| `crewai` | Orquestación de equipos multi-agente |
| `langgraph` | Grafo de flujo de agentes (LangGraph) |
| `litellm >= 1.67.0` | Capa de abstracción para LLMs (Groq, OpenAI, etc.) |
| `crewai-tools` | Herramientas auxiliares de CrewAI |
| `python-dotenv` | Carga de variables de entorno desde `.env` |
| `pydantic` | Validación de schemas de datos |
| `beautifulsoup4` | Inyección de contenido en el reporte HTML |
| `lxml` | Parser HTML para BeautifulSoup |
| `pyyaml` | Lectura del fichero `agents.yaml` |
| `mcp` | Protocolo de contexto de modelos |

> **Nota sobre `lxml`:** En algunos sistemas puede requerir compiladores C. Si la instalación falla, prueba: `pip install lxml --only-binary :all:`

---

## Configuración del entorno (.env)

En la raíz del proyecto, crea un fichero llamado **`.env`** con el siguiente contenido:

```env
# ── Modelos ─────────────────────────────────────────────────────────────────
BIG_MODEL=groq/meta-llama/llama-4-scout-17b-16e-instruct
REASONING_MODEL=groq/openai/gpt-oss-120b
REASONING_RIGOROUS_MODEL=groq/llama-3.3-70b-versatile
SMALL_REASONING_MODEL=groq/openai/gpt-oss-20b

# ── API Keys ─────────────────────────────────────────────────────────────────
GROQ_API_KEY=gsk_TU_CLAVE_AQUI
```

**Cómo obtener la `GROQ_API_KEY`:**

1. Ve a [console.groq.com](https://console.groq.com) y crea una cuenta (gratuita).
2. En el menú lateral, haz clic en **API Keys**.
3. Haz clic en **Create API Key**, ponle un nombre y copia la clave.
4. Pega la clave en el `.env` sustituyendo `gsk_TU_CLAVE_AQUI`.

> **Importante:** Nunca subas el fichero `.env` a un repositorio público. Contiene credenciales privadas.

---

## Preparar el caso de problema antes de cada sesión

El fichero `data_structures/problem_case.json` actúa como estado persistente de la entrevista. **Antes de empezar un nuevo discovery, hay que vaciar el anterior.**

Reemplaza el contenido de `data_structures/problem_case.json` con la plantilla en blanco `data_structures/problem_case_recovery.json`.


---

## Ejecutar la aplicación

Con el entorno virtual activado y el `.env` configurado, lanza la interfaz de chat:

```bash
streamlit run interface.py
```

Streamlit abrirá automáticamente el navegador en `http://localhost:8501`. Si no se abre, accede tú directamente a esa URL.

---

## Flujo de uso

```
Usuario escribe el primer mensaje describiendo su proyecto
         │
         ▼
  Agente Discovery (LLM) realiza preguntas iterativas
  y va rellenando problem_case.json campo a campo
         │
         ▼ (cuando todos los campos están completos)
  Agente Structure Proposal — propuesta arquitectónica inicial
         │
         ▼
  Solution Building Crew — 4 agentes en paralelo:
    · Arquitecto de Datos
    · Data Governance
    · Data & AI Strategist
    · BI Specialist
         │
         ▼
  Roadmap Builder — 7 agentes secuenciales:
    Fuentes → Ingesta (ADF) → Almacenamiento (Medallion)
    → ETL → Modelado → ML/MLOps → Power BI
         │
         ▼
  Resume Agent — resumen ejecutivo
         │
         ▼
  Reporte HTML generado → se abre automáticamente en el navegador
```

Al finalizar el discovery, el sistema genera la propuesta técnica y abre automáticamente el fichero `data_structures/solution_builder_report.html` en el navegador.

---

## Estructura del proyecto

```
AIDM/
├── interface.py                        # Frontend Streamlit (punto de entrada)
├── graph.py                            # Grafo LangGraph (orquestación del flujo)
├── utils.py                            # Utilidades, schemas Pydantic, herramientas JSON/HTML
├── requirements.txt                    # Dependencias Python
├── .env                                # Variables de entorno (NO subir a git)
│
├── agents/
│   ├── discovery_agent_logic.py        # Agente de entrevista iterativa
│   ├── structure_proposal_agent_logic.py # Propuesta arquitectónica inicial
│   ├── solution_builder_crew.py        # Crew de 4 agentes (propuesta técnica)
│   ├── proposal_crew.py                # Sub-crew de la propuesta
│   ├── estimation_crew.py              # Sub-crew de estimación de costos
│   └── roadmap_builder.py              # Crew de 7 agentes (roadmap técnico)
│
├── data_structures/
│   ├── agents.yaml                     # Roles, goals y backstories de los 15 agentes
│   ├── problem_case.json               # Estado de la entrevista (resetear entre sesiones)
│   └── solution_builder_report.html    # Template HTML del reporte de salida
│
└── bd/
    └── costes_perfil.csv               # Tabla de costos por hora y perfil (Junior/Middle/Senior)
```

---

## Mejoras opcionales

### Infracost CLI (precios cloud reales)

El agente de estimación de costos puede enriquecerse con precios reales de Azure/AWS/GCP usando el CLI de Infracost. **Sin él, el sistema funciona igualmente** — el LLM estima los costos por cuenta propia.

Si quieres activar los precios reales:

1. Descarga el CLI desde [infracost.io/docs/#quick-start](https://www.infracost.io/docs/#quick-start) y ponlo en el PATH, **o** coloca el binario `infracost.exe` directamente en la raíz del proyecto.
2. Añade tu clave al `.env`:
   ```env
   INFRACOST_API_KEY=ico-TU_CLAVE_AQUI
   ```
3. Regístrate en [dashboard.infracost.io](https://dashboard.infracost.io) para obtener la clave gratuita.

Cuando el binario está disponible, el sistema genera automáticamente Terraform HCL desde la propuesta y ejecuta `infracost breakdown` para obtener precios reales antes de que el LLM redacte la sección de costos.

---

## Limitaciones conocidas

- **Una sesión por discovery:** Una vez completado el discovery, el chat queda bloqueado. Para un nuevo cliente hay que: (1) resetear `problem_case.json` a la plantilla vacía y (2) reiniciar la aplicación (`Ctrl+C` + `streamlit run interface.py`).
- **Los modelos de Groq tienen límites de tokens por minuto** en el plan gratuito. Si aparecen errores `RateLimitError`, espera unos segundos y vuelve a intentarlo.
- **El reporte HTML se sobreescribe** en cada ejecución. Si quieres conservar una propuesta, copia el fichero `solution_builder_report.html` antes de lanzar un nuevo discovery.

---

## Resolución de problemas comunes

| Síntoma | Causa probable | Solución |
|---|---|---|
| `ModuleNotFoundError` al arrancar | Entorno virtual no activado o dependencias no instaladas | Activa el entorno con `Activate.ps1` y ejecuta `pip install -r requirements.txt` |
| `GROQ_API_KEY not found` o error de autenticación | Fichero `.env` ausente o clave incorrecta | Revisa que existe `.env` en la raíz y que la clave empieza por `gsk_` |
| El chat no responde o da error 500 | Modelo no disponible en Groq o rate limit | Espera unos segundos; comprueba el estado en [status.groq.com](https://status.groq.com) |
| El HTML no se abre al finalizar | El navegador por defecto no está configurado en el sistema | Abre manualmente `data_structures/solution_builder_report.html` desde el explorador de archivos |
| `lxml` falla al instalar | Faltan compiladores C en el sistema | Usa `pip install lxml --only-binary :all:` |

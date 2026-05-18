import os
import webbrowser

import streamlit as st

from graph import run_graph

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="AIDM - Discovery Agent",
    page_icon="🧠",
    layout="centered",
)

# ── Session state ──────────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "Describe la estructura y los requisitos de tu proyecto de DATA & AI 👇"}
    ]

if "solution_completed" not in st.session_state:
    st.session_state.solution_completed = False

# ── Header ─────────────────────────────────────────────────────────────────────
st.markdown("### 🧠 AIDM Discovery Agent")
st.caption("Primera PoC - Demo conversacional para captura de requisitos de proyectos DATA & AI.")
st.divider()

# ── Chat history ───────────────────────────────────────────────────────────────
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# ── Blocked state ──────────────────────────────────────────────────────────────
if st.session_state.solution_completed:
    st.success("✅ Discovery completado. La propuesta de solución ya fue generada y enviada al navegador.")
    st.info("Inicia una nueva sesión para comenzar un nuevo discovery.")
    st.stop()

# ── User input ─────────────────────────────────────────────────────────────────
prompt = st.chat_input("Describe tu proyecto de DATA & AI")

if not prompt:
    st.stop()

# ── User message ───────────────────────────────────────────────────────────────
st.session_state.messages.append({"role": "user", "content": prompt})
with st.chat_message("user"):
    st.markdown(prompt)

# ── Agent execution ────────────────────────────────────────────────────────────
# El spinner cubre toda la ejecución del grafo. Si este turno completa el
# discovery y lanza los 6 agentes, el usuario ve el spinner durante todo
# ese tiempo. Si es un turno normal de discovery, el spinner desaparece
# rápido y se muestra la respuesta en el chat.
response: dict = {}
assistant_response = ""

with st.spinner("Procesando..."):
    try:
        raw_response = run_graph(prompt, chat_history=st.session_state.messages)
        response = raw_response if isinstance(raw_response, dict) else {"assistant_response": str(raw_response)}
        assistant_response = response.get("assistant_response", "")
    except Exception as e:
        assistant_response = (
            "⚠️ No se pudo ejecutar el agente. "
            "Revisa la configuración del modelo (MODEL y API KEY) en `.env`.\n\n"
            f"**Detalle:** {e}"
        )

completion_reached = response.get("completion_reached", False)

# ── Turno normal de discovery: mostrar respuesta en el chat ───────────────────
if not completion_reached:
    with st.chat_message("assistant"):
        st.markdown(assistant_response)
    st.session_state.messages.append({"role": "assistant", "content": assistant_response})
    st.stop()

# ── Fase de solución: no mostrar el texto, abrir el HTML ─────────────────────
st.divider()
st.success(
    "✅ Discovery completado. La propuesta de solución se ha abierto en el navegador."
)

path = os.path.abspath("data_structures/solution_builder_report.html")
webbrowser.open(f"file://{path}")

st.session_state.solution_completed = True
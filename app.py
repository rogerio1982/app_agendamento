from flask import Flask, request, jsonify, render_template
import requests
import sqlite3
import os
from datetime import datetime, timedelta

from langchain_openai import ChatOpenAI
from langchain.agents import initialize_agent, AgentType
from langchain.memory import ConversationBufferMemory
from langchain.tools import StructuredTool
from pydantic.v1 import BaseModel, Field

# =====================
# CONFIG
# =====================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

DATABASE = "clinica.db"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

app = Flask(__name__)

llm = ChatOpenAI(
    api_key=OPENAI_API_KEY,
    model="gpt-4o-mini",
    temperature=0
)

# =====================
# DATABASE
# =====================

def conectar_db():
    return sqlite3.connect(DATABASE)

def criar_tabelas():
    conn = conectar_db()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS consultas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT,
            nome TEXT,
            telefone TEXT,
            data TEXT,
            horario TEXT,
            tipo TEXT,
            status TEXT
        )
    """)
    conn.commit()
    conn.close()

# =====================
# AGENDA (REGRAS REAIS)
# =====================

def eh_dia_util(data: str) -> bool:
    return datetime.strptime(data, "%d/%m/%Y").weekday() < 5

def gerar_horarios():
    blocos = [("08:00", "12:00"), ("14:00", "18:00")]
    horarios = []

    for inicio, fim in blocos:
        atual = datetime.strptime(inicio, "%H:%M")
        fim = datetime.strptime(fim, "%H:%M")
        while atual < fim:
            horarios.append(atual.strftime("%H:%M"))
            atual += timedelta(hours=1)

    return horarios

def horarios_disponiveis(data: str):
    try:
        if not eh_dia_util(data):
            return []
    except ValueError:
        return []

    conn = conectar_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT horario FROM consultas
        WHERE data = ? AND status = 'agendada'
    """, (data,))
    ocupados = [r[0] for r in cursor.fetchall()]
    conn.close()

    return [h for h in gerar_horarios() if h not in ocupados]

# =====================
# TOOLS (SEM INTELIGÊNCIA)
# =====================

class VerHorariosInput(BaseModel):
    data: str = Field(description="Data no formato DD/MM/AAAA")

def ver_horarios(data: str) -> str:
    horarios = horarios_disponiveis(data)
    if not horarios:
        return "Não há horários disponíveis para essa data."
    return "Horários disponíveis:\n" + "\n".join(horarios)

class AgendarConsultaInput(BaseModel):
    chat_id: str
    nome: str
    telefone: str
    data: str
    horario: str
    tipo: str

def agendar_consulta(
    chat_id: str,
    nome: str,
    telefone: str,
    data: str,
    horario: str,
    tipo: str
) -> str:

    if horario not in horarios_disponiveis(data):
        return "Esse horário não está disponível. Por favor, escolha outro."

    conn = conectar_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO consultas
        (chat_id, nome, telefone, data, horario, tipo, status)
        VALUES (?, ?, ?, ?, ?, ?, 'agendada')
    """, (chat_id, nome, telefone, data, horario, tipo))
    conn.commit()
    conn.close()

    return (
        "✅ Consulta agendada com sucesso!\n\n"
        f"📌 Nome: {nome}\n"
        f"📞 Telefone: {telefone}\n"
        f"📅 Data: {data}\n"
        f"⏰ Horário: {horario}\n"
        f"💻 Tipo: {tipo}"
    )

tools = [
    StructuredTool.from_function(
        name="VerHorarios",
        func=ver_horarios,
        args_schema=VerHorariosInput,
        description="Consulta horários disponíveis para uma data."
    ),
    StructuredTool.from_function(
        name="AgendarConsulta",
        func=agendar_consulta,
        args_schema=AgendarConsultaInput,
        description="Agenda uma consulta quando todos os dados estiverem completos."
    )
]

# =====================
# AGENTS (1 por chat)
# =====================

agents = {}

def get_agent(chat_id: str):
    if chat_id not in agents:
        memory = ConversationBufferMemory(
            memory_key="chat_history",
            return_messages=True
        )
        agents[chat_id] = initialize_agent(
            tools=tools,
            llm=llm,
            agent=AgentType.STRUCTURED_CHAT_ZERO_SHOT_REACT_DESCRIPTION,
            memory=memory,
            verbose=True
        )
    return agents[chat_id]

# =====================
# TELEGRAM
# =====================

def enviar_mensagem(chat_id, texto):
    requests.post(
        f"{TELEGRAM_API_URL}/sendMessage",
        json={"chat_id": chat_id, "text": texto}
    )

# =====================
# WEBHOOK
# =====================

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    if "message" not in data:
        return jsonify({"status": "ignored"})

    chat_id = str(data["message"]["chat"]["id"])
    mensagem = data["message"].get("text", "")

    agent = get_agent(chat_id)

    resposta = agent.run(f"""
Você é um **atendente virtual de uma clínica de psicologia**.

### Regras obrigatórias
- Nunca faça diagnósticos.
- Apenas informações e agendamento.
- Atendimento: **segunda a sexta**, **08–12 e 14–18**.
- Sempre confirme os dados antes de agendar.
- Não repita perguntas já respondidas.
- Use as tools para ações concretas.

### Ordem dos dados
1. Nome completo
2. Telefone
3. Data (DD/MM/AAAA)
4. Horário (HH:MM)
5. Tipo (online ou presencial)

chat_id: {chat_id}
Mensagem do paciente: {mensagem}
""")

    enviar_mensagem(chat_id, resposta)
    return jsonify({"status": "ok"})

# =====================
# DASHBOARD
# =====================

@app.route("/dashboard")
def dashboard():
    conn = conectar_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT nome, telefone, data, horario, tipo
        FROM consultas
        WHERE status = 'agendada'
        ORDER BY data, horario
    """)
    consultas = cursor.fetchall()
    conn.close()

    return render_template("dashboard.html", consultas=consultas)

# =====================
# INIT
# =====================

if __name__ == "__main__":
    criar_tabelas()
    app.run(host="0.0.0.0", port=5000, debug=True)

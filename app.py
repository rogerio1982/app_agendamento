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

def reset_agent(chat_id: str):
    agents.pop(chat_id, None)

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
    #mensagem = data["message"].get("text", "")
    mensagem = data["message"].get("text", "").strip().lower()


    # 🔄 RESET EXPLÍCITO DO AGENT
    if mensagem.lower() == "/reset":
        reset_agent(chat_id)
        enviar_mensagem(chat_id, "🔄 Atendimento reiniciado. Pode começar novamente.")
        return jsonify({"status": "reset"})
        agent = get_agent(chat_id)

    resposta = agent.run(f"""
Você é um ATENDENTE VIRTUAL de uma clínica de psicologia.
Seu papel é exclusivamente administrativo e assistencial, nunca clínico.

━━━━━━━━━━━━━━━━━━━━━━
🎯 OBJETIVO PRINCIPAL
━━━━━━━━━━━━━━━━━━━━━━
Atender pacientes via chat, fornecer informações institucionais básicas
e realizar o agendamento de consultas, seguindo regras estritas de ética,
clareza e confirmação de dados.

━━━━━━━━━━━━━━━━━━━━━━
🚫 LIMITES E ÉTICA
━━━━━━━━━━━━━━━━━━━━━━
1. NUNCA faça diagnósticos, avaliações, orientações clínicas ou psicológicas.
2. NÃO ofereça conselhos terapêuticos, mesmo que o paciente peça.
3. NÃO substitua profissionais de saúde.
4. Seu papel é apenas:
   - Informar horários de atendimento
   - Coletar dados
   - Confirmar informações
   - Agendar consultas
5. Em caso de pedidos clínicos, responda educadamente que o atendimento clínico
   ocorre apenas durante a consulta com o profissional.

━━━━━━━━━━━━━━━━━━━━━━
🕒 HORÁRIO DE ATENDIMENTO
━━━━━━━━━━━━━━━━━━━━━━
- Atendimento somente de SEGUNDA a SEXTA
- Horários disponíveis:
  • 08:00 às 12:00
  • 14:00 às 18:00
- Não ofereça horários fora desse período.
- Se o paciente pedir fins de semana ou fora do horário, informe que não há atendimento.

━━━━━━━━━━━━━━━━━━━━━━
📋 DADOS OBRIGATÓRIOS PARA AGENDAMENTO
━━━━━━━━━━━━━━━━━━━━━━
Para agendar uma consulta, TODOS os dados abaixo são obrigatórios:

1. Nome completo do paciente
2. Telefone para contato
3. Data da consulta (formato DD/MM/AAAA)
4. Tipo de consulta:
   - Particular
   - Convêncio
5. Horário da consulta (formato HH:MM)

❗ Nunca tente agendar sem TODOS os dados.
❗ Nunca invente ou deduza dados.
❗ Se algum dado faltar, peça SOMENTE o que estiver faltando.

━━━━━━━━━━━━━━━━━━━━━━
🔁 FLUXO DE ATENDIMENTO
━━━━━━━━━━━━━━━━━━━━━━
1. Em mensagens iniciais como "oi", "olá", "bom dia":
   - Cumprimente o paciente
   - Informe os dias e horários de atendimento
   - Explique quais dados são necessários para o agendamento (na ordem correta)

2. Durante a conversa:
   - Mantenha um tom educado, humano e profissional
   - Seja claro e objetivo
   - Evite linguagem técnica ou jargões
   - Não repita perguntas já respondidas

3. Se o paciente informar apenas o dia da semana (ex: "quarta"):
   - Use a PRÓXIMA data correspondente
   - Sempre confirme a data antes de agendar

━━━━━━━━━━━━━━━━━━━━━━
✅ CONFIRMAÇÃO OBRIGATÓRIA
━━━━━━━━━━━━━━━━━━━━━━
Antes de realizar o agendamento:
- Repita TODOS os dados coletados
- Peça uma confirmação explícita (ex: "Posso confirmar o agendamento?")
- Somente prossiga após uma resposta clara como:
  "sim", "confirmo", "pode agendar"

━━━━━━━━━━━━━━━━━━━━━━
🧰 USO DE TOOLS (OBRIGATÓRIO)
━━━━━━━━━━━━━━━━━━━━━━
Você TEM acesso às seguintes ferramentas e DEVE usá-las:

1. VerHorarios(data: str)
   - Use para consultar horários disponíveis
   - Nunca invente disponibilidade

2. AgendarConsulta(chat_id, nome, telefone, data, horario, tipo)
   - Use SOMENTE após:
     • Todos os dados completos
     • Confirmação explícita do paciente

❗ Nunca descreva o funcionamento interno das tools.
❗ Sempre use as tools para ações concretas.

━━━━━━━━━━━━━━━━━━━━━━
📌 CONTEXTO ATUAL
━━━━━━━━━━━━━━━━━━━━━━
chat_id do paciente: {chat_id}

Mensagem do paciente:
{mensagem}

━━━━━━━━━━━━━━━━━━━━━━
🗂️ DADOS JÁ INFORMADOS (se houver)
━━━━━━━━━━━━━━━━━━━━━━
Utilize a memória da conversa para evitar repetir perguntas
e manter o contexto corretamente.

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

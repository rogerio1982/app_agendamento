# App Agenda (app.py)

Bot de Telegram para clínica de psicologia, com agendamento de consultas e painel simples de visualização.

## O que o app.py faz

- Recebe mensagens do Telegram via webhook.
- Usa LangChain + OpenAI para conduzir o diálogo e chamar tools.
- Valida regras de agenda (segunda a sexta, 08:00–12:00 e 14:00–18:00).
- Persiste consultas em SQLite (clinica.db).
- Exibe um dashboard com as consultas agendadas.

## Endpoints

- `POST /webhook`: recebe mensagens do Telegram.
- `GET /dashboard`: lista consultas agendadas.
- `GET /`: health check simples.

## Variáveis de ambiente

- `TELEGRAM_BOT_TOKEN`
- `OPENAI_API_KEY`

## Banco de dados

- SQLite local: `clinica.db`
- Tabela: `consultas` (id, chat_id, nome, telefone, data, horario, tipo, status)

## Regras de agenda

- Segunda a sexta
- Horários: 08:00–12:00 e 14:00–18:00

## Execução local

```bash
pip install -r requirements.txt
python app.py
```

Acesse o dashboard em: http://localhost:5000/dashboard

## Docker

```bash
docker build -t app_atendimento .
docker run --rm -p 5000:5000 --env-file .env app_atendimento
```

## Estrutura

- app.py
- templates/dashboard.html
- requirements.txt
- Dockerfile

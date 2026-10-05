"""Configurações do agente, lidas de variáveis de ambiente (.env)."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent.parent

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Ordem de tentativa: se um modelo falhar (ex.: 429 por pool lotado), passa para o próximo.
MODELS = [
    m.strip()
    for m in os.getenv(
        "OPENROUTER_MODELS",
        "openrouter/free,z-ai/glm-5.2:free,nvidia/nemotron-3.5-lightning:free,google/gemma-4-26b-a4b-it:free",
    ).split(",")
    if m.strip()
]

DB_PATH = Path(os.getenv("CINEDATA_DB_PATH", ROOT_DIR / "cinerocket.db"))

# Limites de segurança
MAX_ROWS = int(os.getenv("MAX_ROWS", "50"))  # linhas devolvidas ao LLM por consulta
QUERY_TIMEOUT_S = float(os.getenv("QUERY_TIMEOUT_S", "60"))
MAX_AGENT_STEPS = int(os.getenv("MAX_AGENT_STEPS", "5"))  # chamadas ao LLM por pergunta

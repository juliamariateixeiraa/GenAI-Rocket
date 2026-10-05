"""Agente Text-to-SQL: LLM (OpenRouter) + ferramenta run_sql sobre a camada Gold."""

import json
import logging
from dataclasses import dataclass, field

from openai import APIConnectionError, APIStatusError, OpenAI

from cinedata import config
from cinedata.cache import AnswerCache
from cinedata.db import CineDB, QueryResult, UnsafeQueryError
from cinedata.prompts import SYSTEM_PROMPT

log = logging.getLogger(__name__)

RUN_SQL_TOOL = {
    "type": "function",
    "function": {
        "name": "run_sql",
        "description": "Executa UMA consulta SQL SELECT (SQLite, somente leitura) na camada Gold "
        "do CineData e retorna colunas e linhas.",
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "Consulta SELECT válida para SQLite."},
            },
            "required": ["sql"],
        },
    },
}


class QuotaExceededError(RuntimeError):
    """Cota diária de modelos gratuitos do OpenRouter atingida."""


class AllModelsFailedError(RuntimeError):
    """Nenhum modelo da lista de fallback respondeu."""


@dataclass
class AgentAnswer:
    question: str
    answer: str
    queries: list[str] = field(default_factory=list)
    model: str | None = None
    llm_calls: int = 0
    cached: bool = False
    result: QueryResult | None = None  # resultado da última consulta bem-sucedida (para gráficos)


class CineDataAgent:
    def __init__(self, db: CineDB | None = None, models: list[str] | None = None,
                 use_cache: bool = True, memory: bool = True):
        if not config.OPENROUTER_API_KEY:
            raise RuntimeError("Defina OPENROUTER_API_KEY no arquivo .env (veja .env.example).")
        # max_retries=0: re-tentativas automáticas gastariam a cota diária (requests com erro contam).
        self.client = OpenAI(base_url=config.OPENROUTER_BASE_URL,
                             api_key=config.OPENROUTER_API_KEY, max_retries=0, timeout=90)
        self.db = db or CineDB()
        self.models = models or config.MODELS
        self._model_idx = 0
        self.cache = AnswerCache() if use_cache else None
        self.memory = memory
        self.history: list[dict] = []

    # ---------- LLM ----------
    def _chat(self, messages: list[dict]):
        """Chama o modelo atual; em falha transitória, passa para o próximo da lista."""
        last_error = None
        while self._model_idx < len(self.models):
            model = self.models[self._model_idx]
            try:
                resp = self.client.chat.completions.create(
                    model=model, messages=messages, tools=[RUN_SQL_TOOL], temperature=0,
                )
                if not resp.choices:
                    raise AllModelsFailedError(f"{model} retornou resposta vazia")
                return resp, model
            except APIStatusError as exc:
                body = str(exc).lower()
                if exc.status_code == 429 and "per-day" in body:
                    raise QuotaExceededError(
                        "Cota diária de modelos gratuitos atingida (reseta 21h, horário de Brasília)."
                    ) from exc
                if exc.status_code in (401, 402):
                    raise
                last_error = exc
            except (APIConnectionError, AllModelsFailedError) as exc:
                last_error = exc
            log.warning("Modelo %s falhou (%s); tentando o próximo.", model, last_error)
            self._model_idx += 1
        self._model_idx = 0  # na próxima pergunta, recomeça pelo modelo preferido
        raise AllModelsFailedError(f"Todos os modelos falharam. Último erro: {last_error}")

    # ---------- Ferramenta ----------
    def _run_sql(self, sql: str, out: AgentAnswer) -> str:
        try:
            result = self.db.run(sql)
            out.result = result
            return json.dumps(result.to_payload(), ensure_ascii=False, default=str)
        except (UnsafeQueryError, TimeoutError) as exc:
            return json.dumps({"error": f"Consulta bloqueada: {exc}"}, ensure_ascii=False)
        except Exception as exc:  # erro de SQL: devolve ao LLM para ele corrigir
            return json.dumps({"error": f"Erro SQL: {exc}"}, ensure_ascii=False)

    # ---------- Loop do agente ----------
    def ask(self, question: str) -> AgentAnswer:
        question = question.strip()
        # Cache só vale para perguntas sem contexto anterior (com memória, a resposta pode depender dele).
        if self.cache and not self.history:
            hit = self.cache.get(question)
            if hit:
                return AgentAnswer(question, hit["answer"], hit["queries"], hit.get("model"), 0, True)

        messages = [{"role": "system", "content": SYSTEM_PROMPT}, *self.history,
                     {"role": "user", "content": question}]
        out = AgentAnswer(question, "")

        for _ in range(config.MAX_AGENT_STEPS):
            resp, out.model = self._chat(messages)
            out.llm_calls += 1
            msg = resp.choices[0].message
            if not msg.tool_calls:
                out.answer = (msg.content or "").strip()
                break
            messages.append(msg.model_dump(exclude_none=True))
            for call in msg.tool_calls:
                try:
                    sql = json.loads(call.function.arguments or "{}").get("sql", "")
                except json.JSONDecodeError:
                    sql = ""
                out.queries.append(sql)
                log.info("SQL: %s", sql)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": self._run_sql(sql, out)})
        else:
            out.answer = "Não consegui chegar a uma resposta dentro do limite de passos. Tente reformular."

        if not out.answer:
            out.answer = "O modelo não retornou uma resposta. Tente novamente."

        if self.memory:
            sql_note = f"\n\n[SQL usado: {out.queries[-1]}]" if out.queries else ""
            self.history += [{"role": "user", "content": question},
                             {"role": "assistant", "content": out.answer + sql_note}]
            self.history = self.history[-8:]  # últimas 4 trocas
        if self.cache and out.queries:
            self.cache.set(question, {"answer": out.answer, "queries": out.queries, "model": out.model})
        return out

    def reset(self):
        self.history.clear()

"""Acesso somente-leitura à camada Gold (SQLite) com guardrails."""

import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from cinedata import config


class UnsafeQueryError(ValueError):
    """Consulta rejeitada pelos guardrails (não é um SELECT único)."""


_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|vacuum|reindex|truncate)\b",
    re.IGNORECASE,
)


def validate_sql(sql: str) -> str:
    """Garante que a consulta é um único SELECT/WITH. Retorna o SQL normalizado."""
    cleaned = sql.strip().rstrip(";").strip()
    if not cleaned:
        raise UnsafeQueryError("Consulta vazia.")
    if ";" in cleaned:
        raise UnsafeQueryError("Apenas uma instrução por consulta é permitida.")
    if not re.match(r"^(select|with)\b", cleaned, re.IGNORECASE):
        raise UnsafeQueryError("Apenas consultas de leitura (SELECT/WITH) são permitidas.")
    # Remove literais de string antes de procurar palavras proibidas (ex.: título 'Drop Dead').
    without_literals = re.sub(r"'(?:[^']|'')*'", "''", cleaned)
    if _FORBIDDEN.search(without_literals):
        raise UnsafeQueryError("A consulta contém comandos de escrita/administração.")
    return cleaned


def _authorizer(action, *_):
    # Segunda barreira, no próprio SQLite: só leitura e funções.
    allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}
    # SQLITE_RECURSIVE (CTE recursiva) = 33
    allowed.add(getattr(sqlite3, "SQLITE_RECURSIVE", 33))
    return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple]
    truncated: bool = False
    elapsed_s: float = 0.0
    extra: dict = field(default_factory=dict)

    def to_payload(self) -> dict:
        return {
            "columns": self.columns,
            "rows": [list(r) for r in self.rows],
            "row_count": len(self.rows),
            "truncated": self.truncated,
        }


class CineDB:
    def __init__(self, path: Path | str = config.DB_PATH):
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(
                f"Banco não encontrado em {path}. Baixe o cinerocket.db e coloque na raiz do projeto."
            )
        # mode=ro: o arquivo é aberto em modo somente-leitura pelo próprio SQLite.
        self.conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
        self.conn.set_authorizer(_authorizer)

    def run(self, sql: str, max_rows: int = config.MAX_ROWS) -> QueryResult:
        sql = validate_sql(sql)
        deadline = time.monotonic() + config.QUERY_TIMEOUT_S
        # Interrompe consultas que passem do tempo limite (retornar != 0 aborta).
        self.conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 10_000)
        start = time.monotonic()
        try:
            cur = self.conn.execute(sql)
            rows = cur.fetchmany(max_rows + 1)
        except sqlite3.OperationalError as exc:
            if "interrupted" in str(exc):
                raise TimeoutError(f"Consulta excedeu {config.QUERY_TIMEOUT_S:.0f}s.") from exc
            raise
        finally:
            self.conn.set_progress_handler(None, 0)
        columns = [d[0] for d in cur.description or []]
        truncated = len(rows) > max_rows
        return QueryResult(columns, rows[:max_rows], truncated, time.monotonic() - start)

    def close(self):
        self.conn.close()

"""Avaliação do agente contra respostas esperadas (SQL de referência).

    python -m eval.run_eval --reference        # só executa o SQL de referência (0 chamadas ao LLM)
    python -m eval.run_eval --limit 3          # roda o agente nas 3 primeiras perguntas e compara

Critério: o primeiro valor (1ª coluna da 1ª linha) do resultado de referência deve aparecer
na resposta do agente ou no resultado do SQL gerado por ele.
"""

import argparse
import json
from pathlib import Path

from cinedata.db import CineDB

QUESTIONS = json.loads((Path(__file__).parent / "questions.json").read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", action="store_true", help="Só mostra o resultado esperado.")
    parser.add_argument("--limit", type=int, default=len(QUESTIONS))
    args = parser.parse_args()

    db = CineDB()
    agent = None
    if not args.reference:
        from cinedata.agent import CineDataAgent, QuotaExceededError
        agent = CineDataAgent(db=db, memory=False)

    hits = 0
    items = QUESTIONS[: args.limit]
    for i, item in enumerate(items, 1):
        expected = db.run(item["sql"], max_rows=3)
        top = str(expected.rows[0][0]) if expected.rows else ""
        print(f"\n[{i}] {item['pergunta']}\n    esperado (top): {expected.rows[:3]}")
        if agent is None:
            continue
        try:
            ans = agent.ask(item["pergunta"])
        except QuotaExceededError as exc:
            print(f"    {exc}")
            break
        found_in_sql = any(top in str(db.run(q).rows) for q in ans.queries if q)
        ok = top.lower() in ans.answer.lower() or found_in_sql
        hits += ok
        print(f"    agente: {'OK' if ok else 'DIVERGENTE'} ({ans.model}, {ans.llm_calls} chamadas)")
    if agent:
        print(f"\nAcertos: {hits}/{len(items)}")


if __name__ == "__main__":
    main()

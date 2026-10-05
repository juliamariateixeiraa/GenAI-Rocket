"""CLI do CineData Analyst.

Uso:
    python main.py                      # modo conversa (com memória)
    python main.py "Top 10 filmes com maior receita em R$"   # pergunta única
"""

import argparse
import logging
import sys

from cinedata.agent import AllModelsFailedError, CineDataAgent, QuotaExceededError


def print_answer(ans, show_sql: bool):
    print()
    print(ans.answer)
    if show_sql and ans.queries:
        print("\n--- SQL executado ---")
        for q in ans.queries:
            print(q)
    origem = "cache" if ans.cached else f"{ans.model}, {ans.llm_calls} chamada(s) ao LLM"
    print(f"\n({origem})\n")


def main():
    parser = argparse.ArgumentParser(description="Agente Text-to-SQL do catálogo CineData.")
    parser.add_argument("pergunta", nargs="*", help="Pergunta em linguagem natural.")
    parser.add_argument("--no-sql", action="store_true", help="Não mostra o SQL executado.")
    parser.add_argument("--no-cache", action="store_true", help="Ignora o cache de respostas.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Mostra logs (fallback de modelos etc.).")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="[%(levelname)s] %(message)s")

    try:
        agent = CineDataAgent(use_cache=not args.no_cache)
    except (RuntimeError, FileNotFoundError) as exc:
        sys.exit(f"Erro: {exc}")

    def ask(q: str) -> bool:
        try:
            print_answer(agent.ask(q), not args.no_sql)
        except QuotaExceededError as exc:
            print(f"\n{exc}\n")
            return False
        except AllModelsFailedError as exc:
            print(f"\n{exc}\n")
        return True

    if args.pergunta:
        ask(" ".join(args.pergunta))
        return

    print("CineData Analyst — pergunte sobre o catálogo de filmes. ('/nova' limpa a memória, 'sair' encerra)\n")
    while True:
        try:
            q = input("Você: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q:
            continue
        if q.lower() in {"sair", "exit", "quit"}:
            break
        if q == "/nova":
            agent.reset()
            print("Memória da conversa limpa.\n")
            continue
        if not ask(q):
            break


if __name__ == "__main__":
    main()

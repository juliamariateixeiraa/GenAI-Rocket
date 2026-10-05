import json
from pathlib import Path

import pytest

from cinedata.cache import normalize
from cinedata.db import CineDB, UnsafeQueryError, validate_sql

DB_EXISTS = Path("cinerocket.db").exists()


@pytest.mark.parametrize("sql", [
    "DELETE FROM dim_movies",
    "DROP TABLE dim_movies",
    "SELECT 1; DROP TABLE dim_movies",
    "UPDATE dim_movies SET titulo = 'x'",
    "PRAGMA table_info(dim_movies)",
    "ATTACH DATABASE 'x.db' AS x",
    "",
])
def test_rejects_unsafe_sql(sql):
    with pytest.raises(UnsafeQueryError):
        validate_sql(sql)


def test_accepts_select_with_keyword_inside_string():
    assert validate_sql("SELECT * FROM dim_movies WHERE titulo = 'Drop Dead';")


def test_normalize_ignores_case_accents_punctuation():
    assert normalize("Quantidade de filmes por GÊNERO?") == normalize("quantidade de filmes por genero")


@pytest.mark.skipif(not DB_EXISTS, reason="cinerocket.db ausente")
def test_select_runs_and_truncates():
    db = CineDB("cinerocket.db")
    result = db.run("SELECT titulo FROM dim_movies", max_rows=5)
    assert len(result.rows) == 5 and result.truncated


@pytest.mark.skipif(not DB_EXISTS, reason="cinerocket.db ausente")
def test_reference_queries_return_rows():
    db = CineDB("cinerocket.db")
    for item in json.loads(Path("eval/questions.json").read_text(encoding="utf-8")):
        assert db.run(item["sql"]).rows, item["pergunta"]

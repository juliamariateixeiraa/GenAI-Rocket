"""Cache de respostas em disco, para não gastar a cota diária com perguntas repetidas."""

import json
import re
import unicodedata
from pathlib import Path

from cinedata import config

DEFAULT_PATH = config.ROOT_DIR / ".cache" / "answers.json"


def normalize(question: str) -> str:
    text = unicodedata.normalize("NFKD", question.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^\w\s]", "", re.sub(r"\s+", " ", text)).strip()


class AnswerCache:
    def __init__(self, path: Path = DEFAULT_PATH):
        self.path = path
        try:
            self._data = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            self._data = {}

    def get(self, question: str) -> dict | None:
        return self._data.get(normalize(question))

    def set(self, question: str, value: dict):
        self._data[normalize(question)] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")

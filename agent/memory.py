import json
from pathlib import Path

MEMORY_DIR = Path(".memory")
MEMORY_DIR.mkdir(exist_ok=True)


def append_memory(user_id: str, message: dict) -> None:
    path = MEMORY_DIR / f"{user_id}.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(message, default=str) + "\n")


def load_memory(user_id: str) -> list[dict]:
    path = MEMORY_DIR / f"{user_id}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

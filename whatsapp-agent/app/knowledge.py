from pathlib import Path


def load_knowledge(knowledge_dir: Path) -> str:
    if not knowledge_dir.exists():
        return ""

    chunks: list[str] = []
    for path in sorted(knowledge_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8").strip()
        if text:
            chunks.append(f"# {path.stem.replace('_', ' ').title()}\n{text}")
    return "\n\n".join(chunks)

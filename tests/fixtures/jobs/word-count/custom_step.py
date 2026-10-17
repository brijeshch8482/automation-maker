"""Word Count: words, lines and characters of the selected text file."""

from engine.custom_api import CustomContext


def count(text: str) -> dict[str, int]:
    return {
        "words": len(text.split()),
        "lines": len(text.splitlines()),
        "characters": len(text),
    }


def run(ctx: CustomContext):
    text = ctx.read_bytes(ctx.input("text_file")).decode("utf-8", errors="replace")
    numbers = count(text)
    report = "\n".join(f"{name.capitalize()}: {value}" for name, value in numbers.items())
    return ctx.document((report + "\n").encode("utf-8"), "txt")

#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "tomlkit>=0.14.0",
# ]
# ///

from __future__ import annotations

import argparse
import dataclasses
import os
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import tomlkit

MARKDOWN_TEMPLATE: str = "::: {module_path}\n"
MODULE_SYMBOL: str = '<code class="doc-symbol doc-symbol-toc doc-symbol-module"></code>'


class Args(argparse.Namespace):
    src: Path
    api_root: Path
    docs_dir: Path


@dataclasses.dataclass
class Nav:
    module: str = ""
    index: str | None = None
    children: dict[str, Nav] = dataclasses.field(default_factory=dict)

    def add(self, parts: Sequence[str], doc_path: Path) -> None:
        if not parts:
            self.index = os.fspath(doc_path)
            return
        child = self.children.setdefault(parts[0], type(self)(module=parts[0]))
        child.add(parts[1:], doc_path)

    def dump(self) -> Any:
        children: list[Any] = []
        if self.index is not None:
            children.append(self.index)
        for _, child in sorted(self.children.items()):
            children.append(child.dump())
        if len(children) == 1:
            return children[0]
        return {f"{MODULE_SYMBOL} {self.module}": children}


def is_public(part: str) -> bool:
    return not part.startswith("_") or (part.startswith("__") and part.endswith("__"))


def parse_args() -> Args:
    parser = argparse.ArgumentParser()
    parser.add_argument("src", nargs="?", default="src", type=Path)
    parser.add_argument("--api-root", default="reference/", type=Path)
    parser.add_argument("--docs-dir", default="docs/", type=Path)
    return parser.parse_args(namespace=Args())


def main() -> None:
    args = parse_args()
    nav = Nav()
    shutil.rmtree(args.docs_dir / args.api_root, ignore_errors=True)
    for path in sorted(args.src.rglob("*.py")):
        relative = path.relative_to(args.src)
        module_path = relative.with_suffix("")
        parts = tuple(module_path.parts)
        if not all(is_public(part) for part in parts):
            continue
        if parts[-1] == "__main__":
            continue
        doc_path = relative.with_suffix(".md")
        if parts[-1] == "__init__":
            parts = parts[:-1]
            doc_path = doc_path.with_name("README.md")
        doc_path = args.api_root / doc_path
        full_doc_path = args.docs_dir / doc_path
        full_doc_path.parent.mkdir(parents=True, exist_ok=True)
        full_doc_path.write_text(
            MARKDOWN_TEMPLATE.format(module_path=".".join(parts)),
            encoding="utf-8",
        )
        nav.add(parts, doc_path)
    print(tomlkit.dumps(nav.dump()))


if __name__ == "__main__":
    main()

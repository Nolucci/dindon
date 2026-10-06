"""Writes a JSON v2 document to a file, laid out as the contract wants it: every user, role, emoji and message on its own line (docs/import-des-donnees.md).

The file is written to a temporary name and renamed at the end: a reader of the folder never sees a file that is half written.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def _line(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def render(document: dict) -> str:
    parts = ['{\n"users":[\n' + ",\n".join(_line(u) for u in document["users"]) + "\n],",
             '"roles":[\n' + ",\n".join(_line(r) for r in document["roles"]) + "\n],",
             '"emojis":[\n' + ",\n".join(_line(e) for e in document["emojis"]) + "\n],",
             '"guild":' + _line(document["guild"]) + ",",
             '"channel":' + _line(document["channel"]) + ","]
    if "dateRange" in document:
        parts.append('"dateRange":' + _line(document["dateRange"]) + ",")
    parts += [f'"exportedAt":"{document["exportedAt"]}",', f'"schemaVersion":{document["schemaVersion"]},', f'"messageCount":{document["messageCount"]},',
              '"messages":[\n' + ",\n".join(_line(m) for m in document["messages"]) + "\n]\n}\n"]
    return "\n".join(parts)


def write_document(path: Path, document: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    temporary.write_text(render(document), encoding="utf-8")
    os.replace(temporary, path)
    return path

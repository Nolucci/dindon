"""A fake exporter, with the command line of the real one (the part that the watcher uses), for tests and demos.

It asks the fake Discord (tools/fake_discord.py, at $FAKE_DISCORD_URL) for the export instead of Discord, and writes the
file the way the real one does: empty while it works, written at the end, and an empty file when there is nothing to export.
"""
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def main(argv: list[str]) -> int:
    if not argv or argv[0] != "export":
        print("only 'export' is supported by the fake exporter", file=sys.stderr)
        return 2
    options: dict[str, str] = {}
    i = 1
    while i < len(argv):
        if argv[i].startswith("-") and i + 1 < len(argv) and not argv[i + 1].startswith("-"):
            options[argv[i]] = argv[i + 1]
            i += 2
        else:
            options[argv[i]] = ""
            i += 1
    channel, out = options.get("-c"), Path(options.get("-o", "."))
    token = os.environ.get("DISCORD_TOKEN", "")
    if os.environ.get("FAKE_EXPORTER_FAIL"):
        print("Failed to export channel (simulated)", file=sys.stderr)
        return 1
    query = {"channel": channel}
    for option in ("after", "before", "filter"):
        if f"--{option}" in options:
            query[option] = options[f"--{option}"]
    request = urllib.request.Request(f"{os.environ['FAKE_DISCORD_URL']}/_fake/export?{urllib.parse.urlencode(query)}", headers={"Authorization": token})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            text = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        print(f"Authentication token is invalid or channel unknown ({error.code}).", file=sys.stderr)
        return 1
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"export [{channel}].json"
    target.write_text("")  # empty while the export is running
    time.sleep(float(os.environ.get("FAKE_EXPORTER_DELAY", "0")))
    if '"messageCount":0' in text:
        print("Channel does not contain any messages within the specified period; an empty file will be created.")
        return 0
    target.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

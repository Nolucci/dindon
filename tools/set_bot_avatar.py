"""Sets the profile picture of the bot on Discord (PATCH /users/@me). Run it where the token is, for instance in the container:

    docker cp assets/bot-avatar.png dindon-app-1:/tmp/avatar.png
    docker exec dindon-app-1 python - < tools/set_bot_avatar.py

The token is read from the environment and never printed. Discord limits how often a bot may change its picture (a few times an hour)."""
import base64
import json
import os
import sys
import urllib.error
import urllib.request

PATH = os.environ.get("AVATAR", "/tmp/avatar.png")
token = os.environ["DISCORD_TOKEN"].removeprefix("Bot ")
api = os.environ.get("DINDON_DISCORD_API", "https://discord.com/api/v10").rstrip("/")
data = base64.b64encode(open(PATH, "rb").read()).decode()
request = urllib.request.Request(f"{api}/users/@me", method="PATCH", data=json.dumps({"avatar": f"data:image/png;base64,{data}"}).encode(),
                                 headers={"Authorization": f"Bot {token}", "Content-Type": "application/json", "User-Agent": "dindon"})
try:
    with urllib.request.urlopen(request, timeout=30) as response:
        answer = json.load(response)
    print("done: the bot", "has" if answer.get("avatar") else "has NOT", "a profile picture now")
except urllib.error.HTTPError as error:
    print("Discord refused:", error.code, error.read().decode()[:300].replace(token, "<token>"))
    sys.exit(1)

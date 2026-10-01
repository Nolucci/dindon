# JSON format

The JSON export is designed to be compact, consistent, and easy to process, both by programs (databases, scripts) and by AI models. For example, it makes it simple to gather everything that a given person has said.

- It is made of **lookup tables** (`users`, `roles`, `emojis`) followed by the `messages`. Messages refer to users, roles and emoji by **ID**, so nothing is repeated.
- Every user, role, emoji and message takes **exactly one line**, so the file can be processed line by line.
- Properties that are `null` or empty are **left out**. A missing property means "none", no information is lost.
- All timestamps are in **UTC**, in one fixed format (`2025-10-21T00:38:02.164Z`), so they can be compared and sorted as text.
- Emoji and other special characters are written as actual characters (🌹), not as escape sequences (`🌹`).
- All IDs are **strings**, because Discord IDs are too large for some tools (JavaScript, for instance) to handle as numbers.

Two files describe the format without any data in them:

- [JSON-format.template.json](JSON-format.template.json) - the layout to read at a glance. The first entry of `users` and of `messages` is the minimal one (only the properties that are always there), the second one has every possible property.
- [JSON-format.schema.json](JSON-format.schema.json) - the same thing as a [JSON Schema](https://json-schema.org), to validate a file or to generate code and tables from it.

## Layout

The example is shown with one object per line, exactly as in the file:

```json
{
"users":[
{"id":"1080169429545001041","name":"__basile__","discriminator":"0000","globalName":"Basile","nickname":"Basile✊🌹","color":"#FF0000","isBot":false,"roleIds":["100","101"],"avatarUrl":"https://..."},
{"id":"2","name":"bob","discriminator":"0000","isBot":false,"avatarUrl":"https://..."}
],
"roles":[
{"id":"100","name":"Admin","color":"#FF0000","position":5},
{"id":"101","name":"Citoyen","position":1}
],
"emojis":[
{"name":"🌹","code":"rose","isAnimated":false,"imageUrl":"https://..."}
],
"guild":{"id":"10","name":"My server","iconUrl":"https://..."},
"channel":{"id":"20","type":"GuildTextChat","categoryId":"15","category":"Politics","name":"economy"},
"exportedAt":"2026-10-01T11:54:53.679Z",
"schemaVersion":2,
"messageCount":2,
"messages":[
{"id":"1429961890758529115","type":"Default","timestamp":"2025-10-20T22:38:02.164Z","content":"Hello 🌹","authorId":"1080169429545001041","inlineEmojis":["🌹"]},
{"id":"1429961890758529116","type":"Reply","timestamp":"2025-10-20T22:40:00.000Z","content":"See this @alice","authorId":"2","mentionedUserIds":["3"],"reference":{"type":"Default","messageId":"1429961890758529115","channelId":"20","guildId":"10","authorId":"1080169429545001041","content":"Hello 🌹"}}
]
}
```

## Top-level properties

These are always present, in this order, except for `dateRange`:

- `users` - everyone who appears in the export: authors, mentioned users, people who reacted, users of interactions, and authors of replied-to messages. Listed in order of appearance.
- `roles` - the roles of those users, from the most to the least important.
- `emojis` - the emoji used by the messages (inline, in reactions, in polls).
- `guild`, `channel` - where the messages come from. `channel.category` is the parent of the channel (its category or, for a thread or forum post, the channel it belongs to).
- `dateRange` - only present if a date limit (`after` and/or `before`) was set.
- `exportedAt` - when the export was made.
- `schemaVersion` - version of this layout, currently `2`. It is increased whenever the layout changes in a way that affects how it is read.
- `messageCount` - number of messages in the file.
- `messages` - the messages, in chronological order (or reversed, if requested).

If the output is split into partitions, each file is a complete document with the tables of its own messages.

## Users

Their `id` never changes, unlike their names and nicknames, so that is what to use to identify someone.

| Property | Meaning |
| --- | --- |
| `id` | Unique ID of the account. |
| `name` | Username, unique on Discord. |
| `discriminator` | Legacy discriminator, `0000` for accounts that don't have one. |
| `globalName` | Display name chosen by the user. Only present if it differs from `name`. |
| `nickname` | Nickname that the user has in this server. Only present if they set one. |
| `color` | Color of the user in this server, from their roles. |
| `isBot` | Whether the account is a bot. |
| `roleIds` | IDs of the roles of the user, from the most to the least important. |
| `avatarUrl` | Avatar of the user (their server avatar, if they have one). |

The name that Discord displays next to a message is `nickname`, otherwise `globalName`, otherwise `name`.

## Roles

`id`, `name`, `color` (if the role has one) and `position` (the higher, the more important).

## Emoji

Messages refer to an emoji by its `id` if it has one (custom emoji), or by its `name` otherwise (standard emoji, where the name is the character itself).

`id` (custom emoji only), `name`, `code` (e.g. `rose`; left out for custom emoji, where it is the same as the name), `isAnimated`, `imageUrl`.

## Messages

Each message always has `id`, `type`, `timestamp`, `content` and `authorId`. These properties are only present when they have a value:

| Property | Meaning |
| --- | --- |
| `timestampEdited` | When the message was last edited. |
| `callEndedTimestamp` | When the call ended, for call messages. |
| `isPinned` | Only present (as `true`) if the message is pinned. |
| `attachments` | Files: `id`, `url`, `fileName`, `fileSizeBytes`. |
| `embeds` | Rich previews (links, videos, etc.). |
| `stickers` | Stickers: `id`, `name`, `format`, `sourceUrl`. |
| `poll` | `question`, `answers` (`id`, `text`, `emoji`, `votes`), `expiresAt`, `allowsMultipleAnswers`, `isFinalized`. |
| `reactions` | Each one has the `emoji`, its `count`, and the `userIds` of the people who reacted. |
| `mentionedUserIds` | IDs of the users that the message mentions. |
| `reference` | The message that this one replies to or forwards: `type`, `messageId`, `channelId`, `guildId`. For replies, it also has the `authorId` and the `content` of that message, which is useful when it is not a part of the export (for example, when only the messages of one person were exported). |
| `forwardedMessage` | Content of a forwarded message. |
| `interaction` | For responses to commands: `id`, `name` and the `userId` of the person who used it. |
| `inlineEmojis` | The emoji used in the text of the message. |

`type` is the kind of message: `Default`, `Reply`, `ChannelPinnedMessage`, `ChatInputCommand`, etc.

## Processing the file

All messages of one person, with [jq](https://jqlang.github.io/jq/):

```console
jq -c --arg id "1080169429545001041" '.messages[] | select(.authorId == $id)' export.json
```

Number of messages and what was said, per person:

```console
jq -c '(.users | INDEX(.id)) as $u
  | .messages | group_by(.authorId)[]
  | {authorId: .[0].authorId, name: ($u[.[0].authorId] | .nickname // .globalName // .name), messageCount: length, contents: map(.content)}' export.json
```

Turn the file into [JSON Lines](https://jsonlines.org) (one message per line), which most databases can import directly, using only standard tools:

```console
sed -n '/^"messages":\[$/,/^\]$/p' export.json | sed '1d;$d' | sed 's/,$//' > messages.jsonl
```

Do the same with Python:

```python
import json
from collections import defaultdict

with open("export.json", encoding="utf-8") as f:
    export = json.load(f)

users = {u["id"]: u for u in export["users"]}
said = defaultdict(list)
for message in export["messages"]:
    said[message["authorId"]].append(message["content"])

for user_id, contents in said.items():
    user = users[user_id]
    print(user.get("nickname") or user.get("globalName") or user["name"], len(contents))
```

> **Note**:
> The file is assembled when the export is done, because the tables at the start are only known by then. While an export is in progress, the output file stays empty.
>
> The setting that normalizes timestamps to UTC doesn't matter for JSON, which is always in UTC.

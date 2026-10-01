"""Builds an invented Discord server and writes it as JSON v2 exports (one file per channel).

Everything here is made up: names, roles inspired by the kinds of roles that servers use, and short
messages in French about several themes. Nothing comes from a real server. It is used to develop the
interface, to test without Discord, and to reproduce the measures on a large server.

    python tools/make_demo_server.py --out demo/ --people 60 --messages 8000       # a small server
    python tools/make_demo_server.py --out big/  --people 400 --messages 500000    # the measure of 500,000 messages

The same `World` is used by the fake Discord server (tools/fake_discord.py) to produce live exchanges.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

DISCORD_EPOCH_MS = 1_420_070_400_000

# ---------------------------------------------------------------------------------------------
# What people say: statements for and against, by theme. Invented, short, informal.
# ---------------------------------------------------------------------------------------------

THEMES: dict[str, dict[str, list[str]]] = {
    "economie": {
        "pour": [
            "il faut augmenter le SMIC, les gens n'arrivent plus à vivre",
            "les services essentiels devraient rester publics, point",
            "on devrait nationaliser l'énergie, c'est stratégique",
            "plus d'impôt sur les très hauts revenus, ça me paraît juste",
            "la retraite à 60 ans c'était une bonne chose",
            "il faut réguler les prix de l'énergie et de l'alimentaire",
        ],
        "contre": [
            "le SMIC trop haut détruit des emplois dans les petites boîtes",
            "les entreprises publiques coûtent cher et marchent moins bien que le privé",
            "baisser les impôts de production, c'est la seule façon de relancer l'industrie",
            "il faut travailler plus longtemps, les comptes ne tiennent pas sinon",
            "moins de réglementation et plus de liberté d'entreprendre",
            "la dette c'est le vrai problème, il faut réduire les dépenses",
        ],
    },
    "europe": {
        "pour": [
            "l'Europe nous protège, seuls on ne pèse rien face aux grandes puissances",
            "je suis pour plus d'intégration européenne, une vraie défense commune",
            "l'euro nous a protégés pendant les crises, quoi qu'on en dise",
            "les règles européennes sur l'environnement sont une bonne chose",
        ],
        "contre": [
            "il faut sortir de l'Union européenne, on n'est plus souverains",
            "Bruxelles décide de tout et personne ne les a élus",
            "l'euro nous a ruinés, retour à une monnaie nationale",
            "la France doit pouvoir désobéir aux traités quand l'intérêt national l'exige",
        ],
    },
    "immigration": {
        "pour": [
            "la France s'est construite par l'immigration, faut arrêter de l'oublier",
            "il faut régulariser les travailleurs sans papiers qui sont déjà là",
            "le multiculturalisme est une richesse, pas un danger",
            "accueillir les réfugiés c'est un devoir, point final",
        ],
        "contre": [
            "il faut réduire l'immigration, on n'arrive plus à intégrer",
            "l'assimilation doit être la règle, pas le communautarisme",
            "des quotas d'immigration votés chaque année par le Parlement",
            "on doit être plus ferme sur les expulsions",
        ],
    },
    "ecologie": {
        "pour": [
            "il faut sortir du productivisme, la planète n'a pas de plan B",
            "plus d'éoliennes et de solaire, et vite",
            "la sobriété énergétique doit devenir une priorité nationale",
            "taxer le kérosène, ce n'est que justice",
        ],
        "contre": [
            "le nucléaire est la seule vraie réponse au climat, stop aux éoliennes",
            "l'écologie punitive ne passera pas, les gens n'en peuvent plus",
            "la décroissance c'est un luxe de gens aisés",
            "il faut miser sur l'innovation, pas sur les interdictions",
        ],
    },
    "laicite": {
        "pour": [
            "la laïcité c'est la neutralité de l'État, pas la chasse aux croyants",
            "chacun doit pouvoir pratiquer sa religion librement",
            "séparer strictement les religions de l'école publique, c'est le principe",
        ],
        "contre": [
            "nos racines chrétiennes ont leur place dans l'espace public",
            "la laïcité est devenue un outil contre une seule religion",
            "il faut plus de place pour les valeurs spirituelles dans la vie publique",
        ],
    },
    "securite": {
        "pour": [
            "il faut plus de moyens pour la police et la justice",
            "des peines plus lourdes pour les récidivistes, sans exception",
            "la vidéosurveillance a fait ses preuves, il en faut davantage",
        ],
        "contre": [
            "la surveillance de masse est une menace pour nos libertés",
            "la prison ne règle rien, il faut miser sur la prévention",
            "les lois sécuritaires finissent toujours par être détournées",
        ],
    },
    "institutions": {
        "pour": [
            "il faut une VIe République avec un vrai pouvoir au Parlement",
            "le référendum d'initiative citoyenne serait un vrai progrès démocratique",
            "supprimer le 49.3, c'est la base",
        ],
        "contre": [
            "un exécutif fort est nécessaire, l'instabilité serait pire",
            "le RIC finirait capté par les lobbies et les réseaux sociaux",
            "la Ve République a bien tenu, on n'a pas besoin de tout changer",
        ],
    },
    "defense": {
        "pour": [
            "il faut augmenter le budget de l'armée, la dissuasion c'est notre assurance",
            "la France doit rester une puissance qui compte dans le monde",
            "soutenir nos alliés, même si ça coûte cher",
        ],
        "contre": [
            "la diplomatie plutôt que les armes, toujours",
            "sortir de l'OTAN, on n'a pas à suivre Washington",
            "arrêtons d'intervenir partout, ça ne sert à rien",
        ],
    },
    "societe": {
        "pour": [
            "l'aide à mourir devrait être légalisée, avec des garde-fous",
            "l'égalité femmes-hommes avance encore trop lentement",
            "il faut faire évoluer les normes, la société change",
        ],
        "contre": [
            "attention à ne pas tout bouleverser, la famille reste un repère",
            "certaines traditions méritent d'être préservées",
            "le rythme des changements de société est trop rapide pour beaucoup de gens",
        ],
    },
    "technologie": {
        "pour": [
            "l'IA va changer l'industrie, il faut investir massivement",
            "le progrès technique a toujours fini par améliorer la vie",
        ],
        "contre": [
            "attention à la course technologique, on ne maîtrise plus rien",
            "il faut protéger le vivant avant de lancer n'importe quelle innovation",
        ],
    },
}

SMALL_TALK = [
    "mdr", "exact", "d'accord", "+1", "ah oui ?", "pas faux", "bonne question", "je vois",
    "intéressant, tu as une source ?", "c'est un peu plus compliqué que ça", "ouais", "haha",
    "on en parle ce soir en vocal ?", "bon courage à tous", "merci pour l'info", "sérieux ?",
    "j'ai lu un article là-dessus hier", "ça dépend vraiment des cas", "tu exagères un peu non ?",
]
OFF_TOPIC = [
    "quelqu'un a vu le match hier soir ?", "je recommande vraiment ce film", "quelle chaleur aujourd'hui",
    "vous jouez à quoi en ce moment ?", "j'ai testé une super recette de tarte aux poires",
    "le nouvel album est excellent", "bonne soirée à tous", "qui est dispo pour une partie ce week-end ?",
    "le train est encore en retard, évidemment", "bonjour tout le monde",
]
PREFIXES = ["", "", "", "franchement, ", "perso je pense que ", "pour moi ", "non mais ", "sérieux, ", "je crois que ", "à mon avis "]
SUFFIXES = ["", "", "", " non ?", " !", "...", " à mon avis.", " clairement."]
EMOJIS = [("👍", "thumbsup"), ("😂", "joy"), ("🤔", "thinking"), ("👎", "thumbsdown"), ("❤️", "heart"), ("🔥", "fire"), ("😮", "open_mouth")]

# Roles inspired by the kinds of names that servers use. The ideology ones match the names that the
# role rules of db/seed-axes.sql recognize.
IDEOLOGY_ROLES = [
    "Extrême-Gauche", "Gauche Radicale", "Communiste", "Socialiste", "Écosocialiste", "Keynésien", "Centre-Gauche",
    "Gaulliste", "Européiste", "Eurosceptique", "Protectionnisme", "Mondialiste", "Alter-Mondialiste", "Écologiste",
    "Animaliste", "Multiculturaliste", "Progressiste", "Féministe", "Égalitariste", "Survivaliste/Autarcique",
    "Républicain", "Patriote", "Démocrate", "Humaniste", "Antifasciste", "Pragmatique", "Autre voie", "Spiritualité",
]
# Which role a person is likely to take, given what they think (theme, stance) - only a tendency
ROLE_TENDENCY = {
    ("europe", 1): ["Européiste", "Mondialiste", "Démocrate"],
    ("europe", -1): ["Eurosceptique", "Gaulliste", "Patriote", "Protectionnisme"],
    ("economie", 1): ["Socialiste", "Communiste", "Égalitariste", "Keynésien"],
    ("economie", -1): ["Pragmatique", "Mondialiste"],
    ("immigration", 1): ["Multiculturaliste", "Humaniste", "Antifasciste"],
    ("immigration", -1): ["Patriote", "Républicain"],
    ("ecologie", 1): ["Écologiste", "Écosocialiste", "Animaliste"],
    ("societe", 1): ["Progressiste", "Féministe"],
}
STAFF_ROLES = ["Gardien de la démocratie", "Médiateur", "Animateur"]
NOTIF_ROLES = ["Ping Annonces", "Ping Débats", "Ping Vocal"]
AGE_ROLES = ["Entre 13 et 15 ans", "Entre 16 et 20 ans", "Entre 21 et 30 ans", "Entre 31 et 50 ans"]
GENDER_ROLES = ["Homme", "Femme"]
OTHER_ROLES = ["Dunes", "Plato"]

SYLLABLES = ["ka", "lo", "mi", "ra", "ve", "to", "ni", "sa", "bé", "lu", "do", "fi", "gar", "hel", "jo", "mar", "pi", "zo", "cla", "dan", "éli", "léo", "nor", "ber", "tho", "val", "xan"]
CATEGORIES = {"Politique": ["économie", "europe", "immigration", "écologie", "laïcité", "sécurité", "institutions", "défense"],
              "Société": ["société", "technologie", "actualité"], "Détente": ["général", "off-topic", "médias"]}
CHANNEL_THEME = {"économie": "economie", "europe": "europe", "immigration": "immigration", "écologie": "ecologie", "laïcité": "laicite",
                 "sécurité": "securite", "institutions": "institutions", "défense": "defense", "société": "societe", "technologie": "technologie"}

FANCY_BASE = 0x1D4D0  # mathematical bold script capital A; used to make some names look like real fancy names


def fancy(text: str) -> str:
    """Some real display names use letters from the 'mathematical' Unicode block."""
    out = []
    for ch in text:
        if "a" <= ch <= "z":
            out.append(chr(0x1D5EE + ord(ch) - ord("a")))
        elif "A" <= ch <= "Z":
            out.append(chr(0x1D5D4 + ord(ch) - ord("A")))
        else:
            out.append(ch)
    return "".join(out)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def snowflake_time(snowflake: int) -> datetime:
    return datetime.fromtimestamp(((snowflake >> 22) + DISCORD_EPOCH_MS) / 1000, tz=timezone.utc)


@dataclass
class Person:
    id: int
    name: str
    global_name: str | None
    nickname: str | None
    is_bot: bool
    role_ids: list[int]
    community: int
    activity: float
    stance: dict[str, int]
    color: str | None = None

    @property
    def display_name(self) -> str:
        return self.nickname or self.global_name or self.name


@dataclass
class Channel:
    id: int
    name: str
    category: str
    category_id: int
    theme: str | None
    messages: list[dict] = field(default_factory=list)
    parent_id: int | None = None  # set for a thread
    type: str = "GuildTextChat"

    @property
    def last_message_id(self) -> str | None:
        return self.messages[-1]["id"] if self.messages else None


class World:
    """An invented server: people with roles, channels, and messages that can be added over time."""

    def __init__(self, seed: int = 1, people: int = 60, channels: int | None = None):
        self.rng = random.Random(seed)
        self._counter = 0
        self.guild_id = self._flake(datetime(2023, 1, 1, tzinfo=timezone.utc))
        self.name = "Serveur de démonstration"
        self.roles: dict[str, dict] = {}
        self.custom_emoji = {"id": str(self._flake(datetime(2023, 1, 2, 9, tzinfo=timezone.utc))), "name": "kekw"}
        self.people: list[Person] = []
        self.channels: list[Channel] = []
        self.msg_index: dict[str, tuple[Channel, dict]] = {}
        self._make_roles()
        self._make_people(people)
        self._make_channels(channels)

    # --- identifiers ---------------------------------------------------------------------------

    def _flake(self, when: datetime) -> int:
        self._counter += 1
        return ((int(when.timestamp() * 1000) - DISCORD_EPOCH_MS) << 22) | (self._counter & 0xFFF)

    # --- setting the scene ---------------------------------------------------------------------

    def _make_roles(self) -> None:
        created = datetime(2023, 1, 2, tzinfo=timezone.utc)
        names = (STAFF_ROLES + ["━━━━━━━━━"] + IDEOLOGY_ROLES + ["─────────"] + AGE_ROLES + GENDER_ROLES
                 + NOTIF_ROLES + OTHER_ROLES + ["Membre"])
        for position, name in enumerate(reversed(names)):
            self.roles[name] = {"id": str(self._flake(created)), "name": name, "position": position + 1}
            if name in STAFF_ROLES:
                self.roles[name]["color"] = "#E74C3C"

    def _make_people(self, count: int) -> None:
        rng = self.rng
        themes = list(THEMES)
        communities = 5
        # Each community leans one way on some themes, so that groups exist in the data
        lean = {c: {t: rng.choice([-1, -1, 0, 1, 1]) for t in themes} for c in range(communities)}
        used = set()
        for i in range(count):
            while True:
                name = "".join(rng.choice(SYLLABLES) for _ in range(rng.choice([2, 3]))) + (str(rng.randint(1, 99)) if rng.random() < 0.4 else "")
                if name not in used:
                    used.add(name)
                    break
            community = rng.randrange(communities)
            stance = {t: (lean[community][t] if rng.random() < 0.75 else rng.choice([-1, 0, 1])) for t in themes}
            global_name = name.capitalize() if rng.random() < 0.7 else None
            if global_name and rng.random() < 0.12:
                global_name = fancy(global_name)
            nickname = (global_name or name).capitalize() + rng.choice(["✊", "🌹", "", "", ""]) if rng.random() < 0.3 else None
            role_names = ["Membre"]
            if rng.random() < 0.6:  # people who took ideology roles: a tendency from what they think, plus noise
                for (theme, polarity), candidates in ROLE_TENDENCY.items():
                    if stance[theme] == polarity and rng.random() < 0.6:
                        role_names.append(rng.choice(candidates))
                role_names += rng.sample(IDEOLOGY_ROLES, rng.choice([0, 0, 1, 2, 5]))
            if rng.random() < 0.7:
                role_names.append(rng.choice(AGE_ROLES))
            if rng.random() < 0.6:
                role_names.append(rng.choice(GENDER_ROLES))
            if rng.random() < 0.4:
                role_names.append(rng.choice(NOTIF_ROLES))
            if rng.random() < 0.03:
                role_names.append(rng.choice(STAFF_ROLES))
            role_names = sorted(set(role_names), key=lambda n: -self.roles[n]["position"])
            self.people.append(Person(
                id=self._flake(datetime(2023, 1, 3, tzinfo=timezone.utc) + timedelta(minutes=i)),
                name=name, global_name=global_name, nickname=nickname, is_bot=False,
                role_ids=[int(self.roles[n]["id"]) for n in role_names], community=community,
                activity=1.0 / (i + 1) ** 0.9, stance=stance,
                color="#E74C3C" if any(n in STAFF_ROLES for n in role_names) else None))
        self.rng.shuffle(self.people)  # the activity ranking must not follow the creation order
        self.bot = Person(id=self._flake(datetime(2023, 1, 2, 12, tzinfo=timezone.utc)), name="modbot", global_name=None,
                          nickname=None, is_bot=True, role_ids=[], community=-1, activity=0.0, stance={})

    def _make_channels(self, wanted: int | None) -> None:
        base = datetime(2023, 1, 2, 8, tzinfo=timezone.utc)
        pairs = [(cat, ch) for cat, chans in CATEGORIES.items() for ch in chans]
        category_ids = {cat: self._flake(base) for cat in CATEGORIES}
        for cat, ch in pairs:
            self.channels.append(Channel(self._flake(base), ch, cat, category_ids[cat], CHANNEL_THEME.get(ch)))
        extra = 0
        while wanted and len(self.channels) < wanted:  # more channels: numbered copies of the political ones
            extra += 1
            cat, ch = pairs[extra % 8]
            self.channels.append(Channel(self._flake(base), f"{ch}-{extra}", cat, category_ids[cat], CHANNEL_THEME.get(ch)))
        if wanted:
            self.channels = self.channels[:wanted]

    # --- messages ------------------------------------------------------------------------------

    def _statement(self, person: Person, theme: str | None) -> str:
        rng = self.rng
        if theme is None or rng.random() < 0.25:
            return rng.choice(OFF_TOPIC if theme is None else SMALL_TALK)
        stance = person.stance.get(theme, 0)
        if stance == 0 or rng.random() < 0.15:
            polarity = rng.choice(["pour", "contre"])
        else:
            polarity = "pour" if stance > 0 else "contre"
        text = rng.choice(THEMES[theme][polarity])
        prefix = rng.choice(PREFIXES)
        return (prefix + text if prefix else text) + rng.choice(SUFFIXES)

    def post(self, channel: Channel, author: Person, content: str, when: datetime, reply_to: dict | None = None,
             mention: list[Person] | None = None, reactors: list[tuple[str, list[Person]]] | None = None) -> dict:
        """Adds one message to a channel. `when` must not be earlier than the last message of the channel."""
        message: dict = {"id": str(self._flake(when)), "type": "Reply" if reply_to else "Default", "timestamp": iso(when),
                         "content": content, "authorId": str(author.id)}
        rng = self.rng
        if rng.random() < 0.03:
            message["timestampEdited"] = iso(when + timedelta(minutes=rng.randint(1, 30)))
        if rng.random() < 0.005:
            message["isPinned"] = True
        if rng.random() < 0.03:
            message["content"] += " 🔥"
            message["inlineEmojis"] = ["🔥"]
        if rng.random() < 0.02:
            message["attachments"] = [{"id": str(self._flake(when)), "url": f"https://example.invalid/files/{message['id']}.png",
                                       "fileName": "image.png", "fileSizeBytes": rng.randint(1_000, 500_000)}]
        if rng.random() < 0.02:
            message["embeds"] = [{"title": "Un article", "url": "https://example.invalid/article", "description": "Résumé de l'article"}]
        if mention:
            message["mentionedUserIds"] = [str(p.id) for p in mention]
        if reply_to:
            ref_author = reply_to["authorId"]
            message["reference"] = {"type": "Default", "messageId": reply_to["id"], "channelId": str(channel.id),
                                    "guildId": str(self.guild_id), "authorId": ref_author, "content": reply_to["content"]}
        if reactors:
            message["reactions"] = [{"emoji": e, "count": len(users), "userIds": [str(u.id) for u in users]} for e, users in reactors]
        channel.messages.append(message)
        self.msg_index[message["id"]] = (channel, message)
        return message

    def person_by_id(self, user_id: int | str) -> Person:
        user_id = int(user_id)
        if user_id == self.bot.id:
            return self.bot
        return next(p for p in self.people if p.id == user_id)

    def generate(self, messages: int, days: int = 120, end: datetime | None = None) -> None:
        """Fills the server with discussions: bursts of messages between a few people, with replies, mentions, reactions."""
        rng = self.rng
        end = end or datetime(2026, 9, 30, tzinfo=timezone.utc)
        start = end - timedelta(days=days)
        span = (end - start).total_seconds()
        weights = [p.activity for p in self.people]
        by_community: dict[int, list[Person]] = {}
        for p in self.people:
            by_community.setdefault(p.community, []).append(p)
        weights_of = {c: [p.activity for p in ps] for c, ps in by_community.items()}
        channel_weights = [3.0 if c.theme else 1.5 for c in self.channels]
        # Plan the discussions first, then play them in time order, so that message ids follow time
        plans: list[tuple[datetime, Channel, int, list[Person]]] = []
        total = 0
        while total < messages:
            when = start + timedelta(seconds=rng.random() ** 0.8 * span)  # a bit denser lately
            if 1 <= when.hour <= 6 and rng.random() < 0.8:
                continue
            channel = rng.choices(self.channels, channel_weights)[0]
            n = min(40, 1 + int(rng.expovariate(1 / 6)), messages - total)
            starter = rng.choices(self.people, weights)[0]
            members = {starter.id: starter}
            for _ in range(rng.randint(1, 5)):
                own = rng.random() < 0.8
                p = rng.choices(by_community[starter.community], weights_of[starter.community])[0] if own else rng.choices(self.people, weights)[0]
                members[p.id] = p
            plans.append((when, channel, n, list(members.values())))
            total += n
        plans.sort(key=lambda plan: plan[0])
        for when, channel, n, members in plans:
            self._conversation(channel, members, n, when)

    def _conversation(self, channel: Channel, members: list[Person], n: int, when: datetime) -> None:
        rng = self.rng
        recent: list[dict] = []
        now = when
        for i in range(n):
            author = rng.choices(members, [p.activity + 0.1 for p in members])[0] if i else members[0]
            reply_to = None
            mention = None
            if recent and rng.random() < 0.55:
                reply_to = recent[-1] if rng.random() < 0.7 else rng.choice(recent)
                if reply_to["authorId"] == str(author.id):
                    reply_to = None
            if reply_to is not None and rng.random() < 0.3:
                mention = [self.person_by_id(reply_to["authorId"])]
            elif rng.random() < 0.08 and len(members) > 1:
                mention = [rng.choice([m for m in members if m is not author])]
            content = self._statement(author, channel.theme)
            if mention:
                content = f"@{mention[0].display_name} {content}"
            reactors = None
            if rng.random() < 0.14:
                emoji = self.custom_emoji["id"] if rng.random() < 0.15 else rng.choice(EMOJIS)[0]
                reactors = [(emoji, rng.sample(members, rng.randint(1, len(members))))]
            now += timedelta(seconds=rng.randint(4, 240))
            if channel.messages and now <= parse_iso(channel.messages[-1]["timestamp"]):
                now = parse_iso(channel.messages[-1]["timestamp"]) + timedelta(milliseconds=rng.randint(1, 900))
            message = self.post(channel, author, content, now, reply_to, mention, reactors)
            recent.append(message)
            recent = recent[-6:]

    # --- JSON v2 export ------------------------------------------------------------------------

    def export_document(self, channel: Channel, after_id: int | None = None, before_id: int | None = None,
                        exported_at: datetime | None = None, with_reaction_users: bool = True) -> str:
        """The text of a JSON v2 file for one channel, laid out as the exporter does (one entry per line)."""
        exported_at = exported_at or datetime.now(timezone.utc)
        messages = [m for m in channel.messages
                    if (after_id is None or int(m["id"]) > after_id) and (before_id is None or int(m["id"]) < before_id)]
        user_ids: dict[int, None] = {}
        emoji_keys: dict[str, None] = {}
        for m in messages:
            for key in m.get("inlineEmojis", []):
                emoji_keys.setdefault(key)
            user_ids.setdefault(int(m["authorId"]))
            for u in m.get("mentionedUserIds", []):
                user_ids.setdefault(int(u))
            if "reference" in m and "authorId" in m["reference"]:
                user_ids.setdefault(int(m["reference"]["authorId"]))
            for r in m.get("reactions", []):
                emoji_keys.setdefault(r["emoji"])
                for u in r["userIds"]:
                    user_ids.setdefault(int(u))
        users, role_ids = [], {}
        for uid in user_ids:
            p = self.person_by_id(uid)
            u = {"id": str(p.id), "name": p.name, "discriminator": "0000"}
            if p.global_name:
                u["globalName"] = p.global_name
            if p.nickname:
                u["nickname"] = p.nickname
            if p.color:
                u["color"] = p.color
            u["isBot"] = p.is_bot
            if p.role_ids:
                u["roleIds"] = [str(r) for r in p.role_ids]
                role_ids.update(dict.fromkeys(p.role_ids))
            u["avatarUrl"] = f"https://example.invalid/avatars/{p.id}.png"
            users.append(u)
        by_id = {int(r["id"]): r for r in self.roles.values()}
        roles = [by_id[r] for r in sorted(role_ids, key=lambda r: -by_id[r]["position"])]
        emojis = []
        for key in emoji_keys:
            if key == self.custom_emoji["id"]:
                emojis.append({"id": key, "name": self.custom_emoji["name"], "isAnimated": False, "imageUrl": f"https://example.invalid/emoji/{key}.png"})
            else:
                emojis.append({"name": key, "code": dict(EMOJIS + [("🔥", "fire")]).get(key, ""), "isAnimated": False,
                               "imageUrl": f"https://example.invalid/emoji/{ord(key[0]):x}.svg"})
        out_messages = []
        for m in messages:
            if not with_reaction_users and "reactions" in m:
                m = {**m, "reactions": [{k: v for k, v in r.items() if k != "userIds"} for r in m["reactions"]]}
            out_messages.append(m)
        channel_obj = {"id": str(channel.id), "type": channel.type, "categoryId": str(channel.category_id),
                       "category": channel.category, "name": channel.name}
        dumps = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"))
        parts = [
            '{\n"users":[\n' + ",\n".join(dumps(u) for u in users) + "\n],",
            '"roles":[\n' + ",\n".join(dumps(r) for r in roles) + "\n],",
            '"emojis":[\n' + ",\n".join(dumps(e) for e in emojis) + "\n],",
            '"guild":' + dumps({"id": str(self.guild_id), "name": self.name}) + ",",
            '"channel":' + dumps(channel_obj) + ",",
        ]
        if after_id is not None or before_id is not None:
            date_range = {}
            if after_id is not None:
                date_range["after"] = iso(snowflake_time(after_id))
            if before_id is not None:
                date_range["before"] = iso(snowflake_time(before_id))
            parts.append('"dateRange":' + dumps(date_range) + ",")
        parts += [f'"exportedAt":"{iso(exported_at)}",', '"schemaVersion":2,', f'"messageCount":{len(out_messages)},',
                  '"messages":[\n' + ",\n".join(dumps(m) for m in out_messages) + "\n]\n}\n"]
        return "\n".join(parts)

    def channel_listing(self) -> list[dict]:
        """What `GET /guilds/{id}/channels` returns (the parts that matter)."""
        return [{"id": str(c.id), "type": 0, "name": c.name, "parent_id": str(c.category_id), "last_message_id": c.last_message_id}
                for c in self.channels]


def write_exports(world: World, out: Path, partition: int = 0) -> list[Path]:
    """Writes one file per channel (or several, if `partition` messages is set)."""
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for channel in world.channels:
        if not channel.messages:
            continue
        chunks = [channel.messages] if not partition else [channel.messages[i:i + partition] for i in range(0, len(channel.messages), partition)]
        for number, chunk in enumerate(chunks, 1):
            after = int(chunk[0]["id"]) - 1 if partition else None
            before = int(chunk[-1]["id"]) + 1 if partition else None
            path = out / f"{world.name} - {channel.category} - {channel.name} [{channel.id}]{f' part{number}' if partition else ''}.json"
            path.write_text(world.export_document(channel, after, before), encoding="utf-8")
            written.append(path)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True, help="folder for the JSON files (made if missing)")
    parser.add_argument("--people", type=int, default=60)
    parser.add_argument("--messages", type=int, default=8000)
    parser.add_argument("--channels", type=int, default=None, help="number of channels (default: 13)")
    parser.add_argument("--days", type=int, default=120)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--partition", type=int, default=0, help="split each channel into files of this many messages")
    args = parser.parse_args()
    world = World(seed=args.seed, people=args.people, channels=args.channels)
    world.generate(args.messages, days=args.days)
    files = write_exports(world, args.out, args.partition)
    total = sum(len(c.messages) for c in world.channels)
    size = sum(f.stat().st_size for f in files)
    print(f"{total} messages, {len(world.people)} people, {len(world.channels)} channels -> {len(files)} files, {size / 1e6:.1f} MB in {args.out}")


if __name__ == "__main__":
    main()

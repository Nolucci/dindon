"""Writes a generated axis review: a readable page with every axis and every ideology of the database, to be reviewed.

The page is generated from the database, so that it always says what the database says. Run it again
after changing the axes or the ideologies:

    pip install "psycopg[binary]"
    DATABASE_URL=postgresql://dindon:PASSWORD@127.0.0.1:5432/dindon python generate_axes_review.py
"""
import os
import pathlib
import psycopg

SPECTRUM = {
    "radical_left": "extrême gauche", "left": "gauche", "center": "centre", "right": "droite",
    "far_right": "extrême droite", "third_position": "troisième voie", "libertarian": "libertarien", "anarchist": "anarchiste",
}
KIND_TITLE = {"famille": "Familles politiques", "position": "Positions", "valeur": "Valeurs et attitudes"}


def fmt(value):
    return f"{float(value):+.1f}".replace(".", ",").replace("+0,0", "0").replace("-", "−")


def lean(low, high, negative, positive):
    if high <= -0.2:
        return f"vers {negative}"
    if low >= 0.2:
        return f"vers {positive}"
    if high <= 0.0:
        return f"neutre ou vers {negative}"
    if low >= 0.0:
        return f"neutre ou vers {positive}"
    return "plage large"


with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
    cur = conn.cursor()
    cur.execute("select id, code, name, question, negative_pole, positive_pole, definition, excludes, position, is_active, origin from axes order by position")
    axes = cur.fetchall()
    cur.execute("select axis_id, value, description from axis_anchors order by axis_id, value")
    anchors = {}
    for axis_id, value, description in cur.fetchall():
        anchors.setdefault(axis_id, {})[float(value)] = description
    cur.execute("select id, code, name, kind, spectrum, description, is_validated from ideologies order by case kind when 'famille' then 1 when 'position' then 2 else 3 end, name")
    ideologies = cur.fetchall()
    cur.execute("select r.ideology_id, a.position, a.name, a.negative_pole, a.positive_pole, a.is_active, r.min_score, r.max_score from ideology_axis_ranges r join axes a on a.id = r.axis_id order by r.ideology_id, a.position")
    ranges = {}
    for row in cur.fetchall():
        ranges.setdefault(row[0], []).append(row[1:])

core = [a for a in axes if a[10] == "12axes"]
extra = [a for a in axes if a[10] != "12axes"]
out = []
w = out.append

w("# Axes et idéologies à relire\n")
w("Cette page est **générée à partir de la base** (`generate_axes_review.py`) : elle dit exactement ce que contient `seed-axes.sql`. Pour changer quelque chose, modifiez `seed-axes.sql` (ou la base), puis relancez le générateur.\n")
w("## Comment lire\n")
w("- Chaque axe va de **−1 à +1**. −1 est le pôle de gauche du modèle [12 Axes](https://12axes.vercel.app), +1 son pôle de droite. Les pôles ne sont pas des jugements de valeur.")
w("- Pour chaque axe : la question qu'il pose, ce qu'il couvre, **ce qu'il ne couvre pas** (pour qu'un sujet n'appartienne qu'à un seul axe), et ce que veulent dire −1, 0 et +1.")
w("- Les **12 axes du modèle 12 Axes** (leurs noms et leurs pôles) et les **9 axes ajoutés** sont tous **actifs** (décision du 4 octobre 2026 : mesuré sur 55 phrases, le modèle range bien moins de phrases sur un mauvais axe quand il voit l'Europe, l'écologie, le genre, la redistribution, les animaux : voir docs/fonctionnement.md). Un axe inactif n'est ni proposé à l'IA ni calculé.")
w("- Pour éteindre un axe : `UPDATE axes SET is_active = false WHERE code = 'europe';`\n")
w("## Les axes en un coup d'œil\n")
w("| N° | Axe | −1 | +1 | Origine | État |")
w("| ---: | --- | --- | --- | --- | --- |")
for a in axes:
    w(f"| {a[8]} | **{a[2]}** (`{a[1]}`) | {a[4]} | {a[5]} | {'12 Axes' if a[10] == '12axes' else 'ajouté'} | {'actif' if a[9] else 'inactif'} |")
w("")

def axis_section(a):
    w(f"### {a[8]}. {a[2]} (`{a[1]}`){'' if a[9] else ', inactif'}\n")
    w(f"**Question :** {a[3]}\n")
    w(f"**Pôles :** −1 = {a[4]}, +1 = {a[5]}\n")
    w(f"**Ce que l'axe couvre :** {a[6]}\n")
    if a[7]:
        w(f"**Ce qu'il ne couvre pas :** {a[7]}\n")
    an = anchors.get(a[0], {})
    w("**Repères :**\n")
    for value, label in ((-1.0, a[4]), (0.0, "au milieu"), (1.0, a[5])):
        w(f"- **{fmt(value)}** ({label}) : {an.get(value, '')}")
    w("")

w("## Les 12 axes du modèle 12 Axes\n")
for a in core:
    axis_section(a)
w("## Les axes ajoutés\n")
w("Les trois premiers (Europe, écologie, rupture) couvrent ce que les 12 axes ne couvrent pas et que vos rôles de serveur expriment. Les six suivants portent sur des sujets importants du débat politique français.\n")
for a in extra:
    axis_section(a)

w("## Les idéologies\n")
w("Une idéologie est un nom, plus **ce qu'elle implique sur les axes** : la plage où quelqu'un qui s'en réclame doit se trouver. Les plages sont **larges exprès** : un écart n'est signalé que s'il est net. **Toutes sont des propositions non validées** (`is_validated = false`) tant que vous ne les avez pas relues. Une plage sur un axe inactif ne compte qu'une fois l'axe activé (elle est marquée « axe inactif »).\n")
w("Trois sortes : une **famille politique** contraint plusieurs axes, une **position** porte sur un ou deux axes, une **valeur ou attitude** n'implique presque rien.\n")
for kind in ("famille", "position", "valeur"):
    group = [i for i in ideologies if i[3] == kind]
    w(f"### {KIND_TITLE[kind]}\n")
    w("| Idéologie | Spectre | Ce qu'elle implique | Description |")
    w("| --- | --- | --- | --- |")
    for i in group:
        rs = ranges.get(i[0], [])
        if rs:
            implied = "<br>".join(
                f"{name} : de {fmt(lo)} à {fmt(hi)} ({lean(float(lo), float(hi), neg, pos)}){'' if active else ' *axe inactif*'}"
                for (_, name, neg, pos, active, lo, hi) in rs
            )
        else:
            implied = "*rien à vérifier*"
        w(f"| **{i[2]}** (`{i[1]}`) | {SPECTRUM.get(i[4], '')} | {implied} | {i[5] or ''} |")
    w("")

w("## Ce que vous pouvez faire en relisant\n")
w("- Une définition est floue ou partiale : corrigez le texte dans `seed-axes.sql`.")
w("- Un pôle est dans le mauvais sens, ou un axe en recouvre un autre : dites-le, c'est ce qui compte le plus pour la qualité du classement.")
w("- Une plage d'idéologie est trop étroite ou trop large : changez ses bornes.")
w("- Il manque un axe ou une idéologie : ajoutez une ligne dans `seed-axes.sql`.")
w("- Vous voulez éteindre un axe : `UPDATE axes SET is_active = false WHERE code = '...';`")

pathlib.Path(__file__).resolve().parents[1].joinpath("political", "axes-review.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
print(f"axes-review.txt written: {len(axes)} axes, {len(ideologies)} ideologies, {sum(len(v) for v in ranges.values())} ranges")

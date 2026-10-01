# L'exportateur

Dindon ne lit jamais Discord lui-même : il s'appuie sur **DiscordChatExporter** (programme C#, fork dans le dépôt d'origine) et sur le format JSON version 2 décrit dans [contracts/JSON-format.md](../contracts/JSON-format.md). C'est le seul contrat avec Discord.

## Obtenir le binaire

Depuis le dépôt d'origine (celui qui contient `DiscordChatExporter.Cli`) :

```console
dotnet publish DiscordChatExporter.Cli -c Release -r osx-arm64 --self-contained -o <ce dossier>/bin
# Linux : -r linux-x64
```

Le dossier `exporter/bin/` est ignoré par Git. **Cette commande n'a pas encore été relancée pour Dindon** : elle sera vérifiée en phase 1, quand la collecte en aura besoin.

## Export manuel

Déposez simplement les fichiers JSON dans le dossier `inbox/` (phase 1 : ils seront alors ingérés). Le jeton se passe par la variable `DISCORD_TOKEN`, jamais dans une commande ni dans un fichier du dépôt.

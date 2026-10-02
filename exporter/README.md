# L'exportateur

Dindon ne lit jamais Discord lui-même : il s'appuie sur **DiscordChatExporter** (programme C#, fork dans le dépôt d'origine) et sur le format JSON version 2 décrit dans [contracts/JSON-format.md](../contracts/JSON-format.md). C'est le seul contrat avec Discord.

## Obtenir le binaire

Depuis le dépôt d'origine (celui qui contient `DiscordChatExporter.Cli`), en choisissant le système **de l'endroit où il tournera** :

```console
dotnet publish DiscordChatExporter.Cli -c Release -r linux-arm64 --self-contained -o <ce dossier>/bin   # Docker sur un Mac Apple Silicon
dotnet publish DiscordChatExporter.Cli -c Release -r linux-x64   --self-contained -o <ce dossier>/bin   # Docker sur un serveur Linux x64
dotnet publish DiscordChatExporter.Cli -c Release -r osx-arm64   --self-contained -o <ce dossier>/bin   # hors Docker, sur un Mac
```

Avec Docker, **l'application tourne dans un conteneur Linux** : même sur un Mac, il faut `linux-arm64` (Apple Silicon) ou `linux-x64`, pas `osx-arm64`. Le dossier `exporter/bin/` est monté dans le conteneur ; il est ignoré par Git. La compilation d'un `linux-arm64` depuis un Mac a été faite (environ 1 min 36 s la première fois, 27 Mo).

Hors Docker, indiquer son chemin : `DINDON_EXPORTER=/chemin/DiscordChatExporter.Cli` (une commande complète est acceptée, par exemple `python tools/fake_exporter.py` pour la démonstration).

## Ce qui a été vérifié

- le binaire `linux-arm64` démarre dans l'image de l'application (bibliothèques ICU comprises) ;
- il **accepte** les arguments que la surveillance lui passe (`export -c … -f Json -o dossier/ --after … --include-threads active --partition 50000`) : une valeur invalide ou une option inconnue le fait quitter aussitôt avec le code 1, ces arguments le laissent entrer dans sa phase réseau ;
- **pas vérifié** : son fonctionnement contre un vrai serveur (aucun jeton). La surveillance s'appuie sur ce que le code de l'exportateur et sa documentation disent : fichier vide pendant l'export, avertissement (code 0) pour un salon vide ou refusé, `--after` avec un identifiant de message.

## Export manuel

Déposez simplement les fichiers JSON dans le dossier `inbox/` : ils sont importés dans les secondes qui suivent. Pour un très gros salon, ajoutez `--partition 50000` (un fichier se lit en mémoire, environ 10 fois sa taille : voir [docs/MESURES.md](../docs/MESURES.md)). Le jeton se passe par la variable `DISCORD_TOKEN`, jamais dans une commande ni dans un fichier du dépôt.

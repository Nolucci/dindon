# L'Activité : la carte dans un salon vocal

Une **Activité Discord** est une page web que Discord ouvre dans une fenêtre, depuis un salon vocal (la fusée 🚀 de la barre du salon). Ici, c'est la carte de l'interface (les points, les liens, le survol), pour tous ceux qui sont dans le vocal. Elle suit les réglages « Carte sur Discord » de la page Système : éteinte tant qu'ils ne l'activent pas, même nombre de personnes et de noms, jamais une personne qui a fait `/dindon stop` ou `effacer`, jamais un message.

Niveau de preuve : **simulé** (faux Discord dans les tests : jeton, appartenance au serveur, en-têtes). **Jamais ouvert dans un vrai Discord.**

## Ce qu'il faut

1. **Une adresse publique en HTTPS** qui mène à Dindon (port 8000). Pour essayer : `cloudflared tunnel --url http://localhost:8000` donne une adresse `https://….trycloudflare.com` qui change à chaque lancement. En production : votre domaine.
2. **Developer Portal** (discord.com/developers/applications), l'application du bot :
   - **Activities** : activer ; **URL Mappings** : racine `/` → l'adresse du tunnel, sans `https://`.
   - **OAuth2** : le *Client ID* (aussi *Application ID*) et un *Client Secret* (*Reset Secret*, affiché une seule fois).
   - Ajouter dans `.env` : `DISCORD_CLIENT_ID=` et `DISCORD_CLIENT_SECRET=` (le secret est un mot de passe : jamais dans git).
3. `docker compose up -d --build` : l'image doit être reconstruite (la page de l'Activité en fait partie).
4. Dans Dindon (page Système), **activer « Carte sur Discord »**.
5. Dans un salon vocal d'un serveur où le bot est installé : la fusée, puis l'application.

## Ce que voit et peut faire un membre

Il se connecte par Discord (rien à taper), choisit la période, clique une personne puis « Centrer sur … » pour ne voir qu'elle et ses liens. Son jeton ne permet de lire **que** cette carte : tout le reste de l'API (positions, débats, import) reste derrière le mot de passe de l'interface.

## Attention avec un tunnel

Le tunnel rend **toute** l'application accessible depuis Internet, pas seulement l'Activité : la page de connexion de l'interface devient visible. Elle reste protégée par `DINDON_PASSWORD` (choisissez-en un long), mais ne laissez pas le tunnel ouvert plus que nécessaire. En production, un reverse proxy peut ne laisser passer que `/`, `/assets`, `/activity` et `/.well-known`.

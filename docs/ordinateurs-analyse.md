# Ajouter un ordinateur à l'analyse

Dindon peut faire calculer les vecteurs des conversations par son serveur Debian et par des ordinateurs auxiliaires. Chaque machine garde **sa propre RAM et sa propre copie des modèles** ; il n'y a pas de mémoire partagée. Les conversations nécessaires au calcul sont envoyées aux ordinateurs ajoutés. Ils doivent donc être des machines de confiance.

Les lots de vecteurs sont traités en parallèle. Les étapes qui dépendent du résultat précédent (nommage des thèmes, extraction et vérification des positions) restent séquentielles et peuvent être exécutées par l'un des ordinateurs. Le bot Discord et sa vérification des débats continuent à utiliser l'Ollama du serveur. Le gain dépend du nombre de conversations en attente, de la vitesse de chaque ordinateur et du réseau.

## 1. Réseau privé

Installez Tailscale sur le [serveur Debian](https://tailscale.com/docs/install/linux), sur le [Mac](https://tailscale.com/docs/install/mac) et sur chaque [PC Windows](https://tailscale.com/docs/install/windows), puis connectez-les au **même réseau privé Tailscale**. Sur Debian, la méthode rapide indiquée par Tailscale est :

```sh
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Sur chaque ordinateur, relevez son adresse avec `tailscale ip -4` (ou dans l'application Tailscale). Ne publiez pas le port Ollama sur Internet et n'utilisez pas Tailscale Funnel.

## 2. Ollama sur chaque ordinateur

Installez et lancez Ollama sur chaque ordinateur. Son API reste sur `127.0.0.1:11434`. Installez les **mêmes versions exactes** des modèles que sur le serveur. Pour la configuration utilisée ici :

```sh
ollama pull qwen3.5:4b
ollama pull leoipulsar/harrier-0.6b
ollama list
```

Si `DINDON_EMBED_MODEL` ou `DINDON_NAMING_MODEL` a changé sur Debian, utilisez les valeurs réellement affichées par :

```sh
cd /srv/dindon
sudo docker compose exec -T app printenv DINDON_EMBED_MODEL DINDON_NAMING_MODEL
```

Sur le **Mac**, exécutez dans Terminal :

```sh
tailscale up
tailscale ip -4
tailscale serve --bg --tcp=11434 tcp://localhost:11434
tailscale serve status
```

Si `tailscale up` indique que Tailscale est arrêté, ouvrez l'application Tailscale dans la barre de menus du Mac, connectez-vous et autorisez sa configuration VPN dans les réglages macOS. Reprenez les commandes quand `tailscale ip -4` affiche une adresse `100.x.y.z`.

Sur **Windows**, exécutez dans PowerShell (Ollama et Tailscale doivent être démarrés) :

```powershell
ollama pull qwen3.5:4b
ollama pull leoipulsar/harrier-0.6b
& "$env:ProgramFiles\Tailscale\tailscale.exe" up
& "$env:ProgramFiles\Tailscale\tailscale.exe" ip -4
& "$env:ProgramFiles\Tailscale\tailscale.exe" serve --bg --tcp=11434 tcp://localhost:11434
& "$env:ProgramFiles\Tailscale\tailscale.exe" serve status
```

`tailscale serve` ne rend Ollama accessible **qu'aux appareils autorisés sur ce réseau privé**. Il continue après la fermeture du terminal grâce à `--bg`.

## 3. Vérifier depuis Debian, puis ajouter dans Dindon

Remplacez l'adresse ci-dessous par celle donnée par `tailscale ip -4` sur l'ordinateur. Le test part du conteneur de l'application, comme l'analyse réelle :

```sh
cd /srv/dindon
sudo docker compose exec -T app python -c 'import json,urllib.request; print([m["name"] for m in json.load(urllib.request.urlopen("http://100.x.y.z:11434/api/tags", timeout=5))["models"]])'
```

Puis dans **Système → Performance → Ordinateurs d'analyse**, ajoutez `http://100.x.y.z:11434`. L'état doit passer à **Connecté** après « Actualiser l'état » et indiquer les modèles utilisés. Si un modèle porte le bon nom mais n'a pas la même empreinte que sur le serveur, Dindon écarte cet ordinateur pour ce modèle afin de ne pas mélanger deux espaces de vecteurs. Vous pouvez ajouter un Mac et plusieurs PC Windows ; la liste est conservée dans la base, même après un redémarrage. Une modification est refusée pendant une analyse pour ne pas interrompre ses calculs.

Ne mettez pas à jour le modèle de vecteurs du serveur juste pour rendre un ordinateur compatible si des vecteurs ont déjà été calculés : les anciens vecteurs restent associés au nom du modèle. Faites correspondre la version de l'auxiliaire à celle du serveur ou planifiez une reconstruction complète des vecteurs.

Dès qu'il y a au moins deux machines (le serveur compte), le même panneau affiche un curseur **Part du travail** par ordinateur. Le total doit faire 100 %. « Répartir également » remet un partage égal, et un ordinateur à 0 % ne reçoit rien. La répartition s'applique aux vecteurs et au nommage des thèmes, et elle peut être changée pendant une analyse. Elle revient à un partage égal quand la liste des ordinateurs change.

Lancez ensuite une analyse qui comporte des **vecteurs**. Le journal annonce le nombre d'ordinateurs configurés. Pour vérifier leur utilisation, observez l'activité d'Ollama sur les ordinateurs et le nombre de vecteurs terminés dans l'interface.

Si un ordinateur s'éteint pendant une analyse, Dindon essaie de refaire sa requête sur l'Ollama du serveur si le même modèle y est installé. Une requête en cours peut attendre le délai d'expiration avant cette reprise ; retirez l'ordinateur hors ligne pour les analyses suivantes.

## Arrêter le partage

Retirez l'ordinateur dans **Système → Performance**, puis sur cet ordinateur :

```sh
tailscale serve --tcp=11434 off
```

Sur Windows, remplacez `tailscale` par `& "$env:ProgramFiles\Tailscale\tailscale.exe"`.

Pour les détails du réseau privé : [Tailscale Serve](https://tailscale.com/docs/reference/tailscale-cli/serve). Pour Ollama : [API Ollama](https://docs.ollama.com/api).

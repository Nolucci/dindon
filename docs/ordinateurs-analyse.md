# Ajouter un ordinateur à l'analyse

Dindon peut faire calculer les vecteurs des conversations par son serveur Debian et par des ordinateurs auxiliaires. Chaque machine garde **sa propre RAM et sa propre copie des modèles** ; il n'y a pas de mémoire partagée. Les conversations nécessaires au calcul sont envoyées aux ordinateurs ajoutés. Ils doivent donc être des machines de confiance.

Les calculs indépendants de vecteurs, de positions et d’axes peuvent être traités en parallèle, avec au plus un calcul par ordinateur. Chaque étape attend les résultats nécessaires avant de passer à la suivante. Le gain dépend du nombre de conversations en attente, de la vitesse de chaque ordinateur et du réseau.

## Installation automatique sur Linux

Copier uniquement [`install-analysis-linux.sh`](../tools/host/install-analysis-linux.sh) sur l’ordinateur à ajouter, puis exécuter :

```sh
sudo bash install-analysis-linux.sh
```

Le fichier est autonome : il contient aussi le relais thermique. Il installe les paquets avec apt-get, dnf ou zypper, installe Ollama et Tailscale si nécessaire, télécharge `qwen3.5:4b` et `leoipulsar/harrier-0.6b`, configure le démarrage automatique et partage l’API dans Tailscale. Il réserve la RAM à une requête et un modèle chargé à la fois, avec un contexte de 8 192 tokens pour les lectures Dindon. Il vérifie réellement les vecteurs et une réponse JSON avant d’annoncer que l’installation est terminée. La durée dépend des téléchargements et de la vitesse du CPU.

Ouvrir le lien de connexion Tailscale affiché et choisir le réseau utilisé par Dindon. Pour une connexion sans navigateur, fournir une **nouvelle clé** dans un fichier local :

```sh
sudo bash install-analysis-linux.sh --auth-key-file /chemin/cle-tailscale.txt
```

L’installateur n’enregistre pas cette clé. La connexion par fichier suit la [documentation Tailscale](https://tailscale.com/docs/reference/tailscale-cli/up).

La protection thermique CPU est activée automatiquement si des capteurs sont reconnus. Sans capteur, notamment dans une VM, l’installation continue en indiquant que la protection est indisponible. Pour exiger cette protection et refuser le partage sans capteur :

```sh
sudo bash install-analysis-linux.sh --require-thermal
```

Linux doit utiliser systemd et un processeur x86_64 ou ARM64. Une VM de 8 Go reste à valider sur des analyses complètes ; une seule lecture de vérification ne garantit pas que tous les messages tiendront en mémoire. Les modèles doivent correspondre aux versions exactes utilisées par le serveur.

À la fin, copier l’adresse `http://100.x.y.z:11434` affichée dans **Système → Performance → Ordinateurs d’analyse**. Le script ne dispose pas de la connexion administrateur Dindon pour faire cet ajout lui-même. Il peut être relancé après une interruption et conserve la connexion Tailscale existante. Il redémarre Ollama sur l’ordinateur concerné : l’exécuter avant de lancer une analyse.

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

Puis dans **Système → Performance → Ordinateurs d'analyse**, ajoutez `http://100.x.y.z:11434` avec un nom, par exemple « PC Pilgrimeru » ou « VM Linux ». Le nom peut être modifié à tout moment, y compris pendant une analyse. Il est conservé après redémarrage et affiché avec l’adresse dans le suivi et les débats. L'état doit passer à **Connecté** après « Actualiser l'état » et indiquer les modèles utilisés. Si un modèle porte le bon nom mais n'a pas la même empreinte que sur le serveur, Dindon écarte cet ordinateur pour ce modèle afin de ne pas mélanger deux espaces de vecteurs. Vous pouvez ajouter un Mac et plusieurs PC Windows ; la liste est conservée dans la base, même après un redémarrage. Une modification est refusée pendant une analyse pour ne pas interrompre ses calculs.

Ne mettez pas à jour le modèle de vecteurs du serveur juste pour rendre un ordinateur compatible si des vecteurs ont déjà été calculés : les anciens vecteurs restent associés au nom du modèle. Faites correspondre la version de l'auxiliaire à celle du serveur ou planifiez une reconstruction complète des vecteurs.

Dès qu'il y a au moins deux machines (le serveur compte), le même panneau affiche un curseur **Part du travail** par ordinateur. Le total doit faire 100 %. « Répartir également » remet un partage égal, et un ordinateur à 0 % reste réservé au secours si aucun autre ordinateur compatible ne peut répondre. La répartition s'applique aux vecteurs et au nommage des thèmes, et elle peut être changée pendant une analyse. Elle revient à un partage égal quand la liste des ordinateurs change.

Lancez ensuite une analyse qui comporte des **vecteurs**. Le journal annonce le nombre d'ordinateurs configurés. Pour vérifier leur utilisation, observez l'activité d'Ollama sur les ordinateurs et le nombre de vecteurs terminés dans l'interface.

Pendant une analyse, un ordinateur configuré qui ne répond plus est retiré du répartiteur. Le calcul interrompu est confié à un autre ordinateur disposant du même modèle et de la même version exacte. Les autres calculs continuent.

Les ordinateurs absents sont vérifiés toutes les deux secondes (avec un délai réseau d’une seconde par vérification, par groupes de huit). Dès qu’un ordinateur répond à nouveau, il peut recevoir le prochain calcul en attente, sans ouvrir la page Système ni relancer l’analyse. Les calculs déjà en cours restent sur leur ordinateur. La répartition configurée continue de s’appliquer : une part de 0 % réserve l’ordinateur au secours.

L’analyse s’arrête lorsque le travail demandé est terminé, lorsque quelqu’un l’annule, ou lorsqu’aucun ordinateur compatible ne peut poursuivre le calcul. Les résultats déjà enregistrés sont conservés. Une erreur de modèle, de données ou de base peut également empêcher la poursuite : elle ne doit pas être affichée comme une analyse réussie.

## Arrêter le partage

Retirez l'ordinateur dans **Système → Performance**, puis sur cet ordinateur :

```sh
tailscale serve --tcp=11434 off
```

Sur Windows, remplacez `tailscale` par `& "$env:ProgramFiles\Tailscale\tailscale.exe"`.

Pour les détails du réseau privé : [Tailscale Serve](https://tailscale.com/docs/reference/tailscale-cli/serve). Pour Ollama : [API Ollama](https://docs.ollama.com/api).

## Protection thermique sur un ordinateur Linux

Ollama ne transmet pas les températures. La reprise automatique seule ne protège donc pas contre la surchauffe. Le relais `tools/host/ollama_thermal_proxy.py` permet de retirer un hôte Linux en fonction de ses capteurs CPU, sans arrêter les autres ordinateurs. Installer ce relais sur **chaque ordinateur à protéger**, avant de lancer une analyse.

Ce relais reconnaît les capteurs CPU `coretemp`, `k10temp`, `zenpower`, `cpu_thermal` et `k8temp` via `/sys/class/hwmon`. Il ne surveille pas les GPU. Il refuse de démarrer sans capteur CPU reconnu ; une VM ne dispose souvent pas des températures de son hôte physique. Dans ce cas, la protection doit être assurée sur l’hôte physique : ne pas supposer que la VM est protégée par ce relais.

Le seuil par défaut est 85 °C, abaissé si le capteur expose une température critique plus basse (marge de 5 °C). La reprise exige de redescendre à 75 °C, ou à 10 °C sous le seuil effectif si celui-ci est inférieur à 85 °C. Ces valeurs sont des réglages de départ, à adapter aux limites du matériel ; elles ne garantissent pas la protection de toute machine. Les mesures sont relues toutes les 0,5 seconde. Une mesure devenue indisponible retire aussi l’ordinateur.

Le relais coupe la connexion d’un calcul en cours lorsque la température dépasse le seuil, refuse les calculs et les contrôles de disponibilité pendant le refroidissement, puis permet la reprise automatique. Ollama doit rester sur `127.0.0.1:11434` et tous les appels d’analyse doivent passer par le relais pour bénéficier de la protection.

### Installation

Copier `tools/host/ollama_thermal_proxy.py` sur l’ordinateur Linux, puis, depuis son dossier :

```sh
sudo apt install -y python3
sudo install -d /opt/dindon-worker
sudo install -m 644 ollama_thermal_proxy.py /opt/dindon-worker/ollama_thermal_proxy.py
python3 /opt/dindon-worker/ollama_thermal_proxy.py
```

Si un capteur est reconnu, le relais démarre sur `127.0.0.1:11435`. Interrompre avec Ctrl+C et créer le service :

```sh
sudo tee /etc/systemd/system/dindon-thermal.service >/dev/null <<'EOF'
[Unit]
Description=Ollama avec protection thermique CPU
After=network.target ollama.service

[Service]
DynamicUser=yes
ExecStart=/usr/bin/python3 /opt/dindon-worker/ollama_thermal_proxy.py
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now dindon-thermal
sudo systemctl status dindon-thermal --no-pager
curl --fail http://127.0.0.1:11435/api/tags
```

Lorsque le relais répond, faire pointer Tailscale sur ce relais, en gardant l’adresse que Dindon utilise :

```sh
sudo tailscale serve --bg --tcp=11434 tcp://localhost:11435
sudo tailscale serve status
```

Depuis la machine qui héberge Dindon :

```sh
curl --fail --connect-timeout 10 http://100.X.Y.Z:11434/api/tags
```

En cas de retrait thermique, le journal du service donne le motif :

```sh
journalctl -u dindon-thermal --since '10 minutes ago'
```

Le relais se lie uniquement à la boucle locale et n’expose que les appels Ollama utilisés par Dindon. Ne pas ouvrir les ports Ollama sur Internet. Pour modifier les seuils, ajouter `--max-temperature` et `--resume-temperature` à `ExecStart`, puis recharger systemd et redémarrer ce service entre deux analyses.

La lecture des capteurs suit la [documentation officielle Linux hwmon](https://www.kernel.org/doc/html/latest/hwmon/sysfs-interface.html). Ce relais ne couvre pas Windows ni macOS : ces ordinateurs ont besoin d’une mesure locale adaptée avant qu’un retrait thermique automatique soit possible.

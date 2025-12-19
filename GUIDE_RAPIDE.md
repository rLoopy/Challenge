# Setup

## 1. Bot Discord

1. https://discord.com/developers/applications
2. New Application → Bot → Add Bot
3. Activer : Presence Intent, Server Members Intent, Message Content Intent
4. Copier le token
5. OAuth2 → URL Generator → `bot` + `applications.commands`
6. Permissions : Send Messages, Embed Links, Attach Files, Use Slash Commands
7. Ouvrir l'URL, ajouter au serveur

## 2. Installation

```bash
pip install -r requirements.txt
```

## 3. Configuration

Créer `.env` :
```
DISCORD_TOKEN=xxx
```

## 4. Lancer

```bash
python bot.py
```

ou double-clic sur `start.bat`

## Utilisation

```
/setup user1:@A activity1:Salle goal1:4 gage1:"..." user2:@B activity2:Boxe goal2:3 gage2:"..."
```

```
/checkin [photo]
```

```
/stats
```

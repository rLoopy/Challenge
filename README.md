# Challenge Bot

Bot Discord pour tracker un défi entre deux personnes.

## Concept

- Chaque participant a un objectif hebdomadaire
- Check-in avec photo obligatoire
- Objectif manqué = gage

## Installation

### 1. Créer le bot Discord

1. [Discord Developer Portal](https://discord.com/developers/applications)
2. New Application → Bot → Add Bot
3. Activer les Intents (Presence, Server Members, Message Content)
4. Copier le token
5. OAuth2 → URL Generator → bot + applications.commands
6. Permissions : Send Messages, Embed Links, Attach Files, Use Slash Commands
7. Inviter le bot

### 2. Configuration

```bash
pip install -r requirements.txt
```

Créer `.env` :
```
DISCORD_TOKEN=ton_token
DATABASE_URL=postgresql://user:password@host:port/database
```

> **Note :** Pour Supabase, utiliser l'URL du **Pooler** (Transaction mode, port 6543)

### 3. Lancer

**Local :**
```bash
python bot.py
```

**Railway (déploiement 24/7) :**
Voir [DEPLOYMENT.md](DEPLOYMENT.md)

## Commandes

| Commande | Description |
|----------|-------------|
| `/setup` | Créer un défi |
| `/checkin` | Enregistrer une session |
| `/stats` | Voir les stats |
| `/cancel` | Annuler |
| `/help` | Aide |

## Fonctionnement

- Semaine : Lundi 00h → Dimanche 23h59
- Vérification automatique dimanche soir
- Rappels vendredi/samedi si en retard
- Objectif manqué → fin du défi + gage

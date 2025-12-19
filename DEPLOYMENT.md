# Déploiement sur Railway

## Setup Railway

### 1. Créer un compte
- Va sur [railway.app](https://railway.app)
- Connexion avec GitHub

### 2. Push ton code sur GitHub
```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin <ton-repo-github>
git push -u origin main
```

### 3. Déployer sur Railway

**Option A : Depuis GitHub**
1. Railway Dashboard → New Project
2. Deploy from GitHub repo
3. Sélectionne ton repo
4. Railway détecte automatiquement Python

**Option B : Railway CLI**
```bash
npm install -g @railway/cli
railway login
railway init
railway up
```

### 4. Ajouter le token Discord

Dans Railway Dashboard :
1. Ton projet → Variables
2. Ajouter : `DISCORD_TOKEN` = `ton_token_discord`
3. Le bot redémarre automatiquement

### 5. Vérifier les logs

Dans Railway :
- Onglet "Deployments"
- Clique sur le dernier déploiement
- Tu devrais voir : "Bot connecté: ..."

## Fichiers requis (déjà créés)

- `requirements.txt` — Dépendances Python
- `runtime.txt` — Version Python
- `Procfile` — Commande de démarrage
- `railway.json` — Config Railway
- `.railwayignore` — Fichiers à ignorer

## Base de données

Railway crée un volume persistant automatiquement.
La base SQLite (`challenge.db`) sera conservée entre les redémarrages.

## Monitoring

Le bot s'exécute 24/7 sur Railway.

Logs en temps réel :
```bash
railway logs
```

## Problèmes courants

**Bot ne démarre pas :**
- Vérifie que `DISCORD_TOKEN` est bien configuré
- Regarde les logs pour les erreurs

**Bot se déconnecte :**
- Railway redémarre automatiquement (max 10 fois)
- Vérifie les logs pour identifier le problème

**Base de données vide après redémarrage :**
- Vérifie que le volume est bien monté
- Railway devrait le gérer automatiquement

## Coût

- **Gratuit** : 500h/mois (suffisant pour 1 bot 24/7)
- **Pro** : $5/mois (usage illimité)

Pour un bot Discord simple, le plan gratuit suffit.



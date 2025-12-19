# Railway - Démarrage Rapide

## 1. Push sur GitHub

```bash
git init
git add .
git commit -m "Bot Discord"
git branch -M main
git remote add origin https://github.com/ton-username/ton-repo.git
git push -u origin main
```

## 2. Déployer sur Railway

1. [railway.app](https://railway.app) → Login avec GitHub
2. **New Project** → **Deploy from GitHub repo**
3. Sélectionne ton repo
4. Attends le build (~1 min)

## 3. Ajouter le token

1. Dashboard → Ton projet
2. **Variables** (onglet)
3. **New Variable**
   - Name: `DISCORD_TOKEN`
   - Value: `ton_token_discord_ici`
4. Save (le bot redémarre automatiquement)

## 4. Vérifier

1. Onglet **Deployments**
2. Clique sur le dernier déploiement
3. **View Logs**
4. Tu devrais voir : `Bot connecté: ...`

## C'est tout

Ton bot tourne maintenant 24/7.

## Commandes utiles

Logs en temps réel :
```bash
railway logs
```

Redémarrer :
```bash
railway restart
```

## Coût

Gratuit : 500h/mois (largement suffisant pour 1 bot)



# Guide de Test

## Checklist de test rapide

### 1. Vérifier que le bot répond
```
/test
```
Doit afficher : "Bot opérationnel"

### 2. Créer un défi de test
```
/setup
  user1: @Toi
  activity1: Test
  goal1: 2
  gage1: Test gage
  user2: @TonPote (ou un autre compte)
  activity2: Test
  goal2: 1
  gage2: Test gage 2
```

**Attendu :** Message "Nouveau défi" avec les infos

### 3. Test check-in
Upload une photo (n'importe quelle image) :
```
/checkin photo: [ta photo]
```

**Attendu :**
- Message "Session enregistrée"
- Barre de progression à jour
- Photo affichée

### 4. Voir les stats
```
/stats
```

**Attendu :** Tableau avec les progressions

### 5. Test annulation (optionnel)
```
/cancel
```
Clique "Confirmer"

**Attendu :** "Défi annulé"

---

## Après les tests

### Réinitialiser toutes les données

```
/reset
```

⚠️ **ATTENTION :** Supprime TOUT (défis, check-ins, historique)

Clique "Oui, tout effacer" pour confirmer.

---

## Tests avancés

### Test multiple check-ins
- Fais plusieurs `/checkin` pour voir la progression
- Vérifie que les stats se mettent à jour

### Test avec vrai défi
Après `/reset`, crée un vrai défi avec les bons objectifs :
```
/setup
  user1: @Loopy
  activity1: Salle
  goal1: 4
  gage1: Ton vrai gage
  user2: @Ami
  activity2: Boxe
  goal2: 3
  gage2: Son vrai gage
```

### Vérifier que tout est à zéro après reset
```
/test
```
Devrait afficher : "Défi actif: Non" et "Check-ins totaux: 0"



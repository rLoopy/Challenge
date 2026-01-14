# Système de Migrations

Ce projet utilise un système de migrations automatique pour gérer les changements de schéma de base de données.

## Comment ça marche ?

Les migrations s'exécutent **automatiquement** au démarrage du bot. Pas besoin d'intervention manuelle, c'est parfait pour Railway + Supabase !

### Processus
1. Le bot démarre
2. `run_migrations()` est appelé (avant `init_db()`)
3. Le système vérifie quelles migrations n'ont pas encore été appliquées
4. Les nouvelles migrations sont exécutées dans l'ordre
5. Le bot continue son démarrage normal

### Table de suivi
Les migrations appliquées sont trackées dans la table `schema_migrations` :
```sql
CREATE TABLE schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
```

## Ajouter une nouvelle migration

1. Ouvrir `migrate.py`
2. Ajouter un nouvel appel à `apply_migration()` dans `run_migrations()`
3. Utiliser un numéro de version séquentiel (002, 003, etc.)
4. Écrire le SQL de migration

### Exemple
```python
def run_migrations():
    print("=== Démarrage des migrations ===")
    ensure_migrations_table()

    # Migration existante
    apply_migration('001_create_challenge_participants', '''
        CREATE TABLE IF NOT EXISTS challenge_participants (...)
    ''')

    # Nouvelle migration
    apply_migration('002_add_new_column', '''
        ALTER TABLE challenge ADD COLUMN new_field TEXT
    ''')

    print("=== Migrations terminées ===\n")
```

## Vérifier les migrations appliquées

### Via Supabase Dashboard
1. Aller dans l'onglet "SQL Editor"
2. Exécuter :
```sql
SELECT * FROM schema_migrations ORDER BY applied_at DESC;
```

### Dans les logs Railway
Au démarrage du bot, tu verras :
```
=== Démarrage des migrations ===
✓ Migration 001_create_challenge_participants déjà appliquée
→ Application de la migration 002_add_new_column...
✓ Migration 002_add_new_column appliquée avec succès
=== Migrations terminées ===
```

## Rollback

Pour annuler une migration, il faut :
1. Écrire le SQL inverse manuellement dans Supabase
2. Supprimer l'entrée dans `schema_migrations` :
```sql
DELETE FROM schema_migrations WHERE version = '002_add_new_column';
```

## Bonnes pratiques

✅ **À FAIRE :**
- Toujours utiliser `IF EXISTS` / `IF NOT EXISTS`
- Tester les migrations localement d'abord
- Numéroter les migrations de façon séquentielle
- Décrire clairement ce que fait chaque migration

❌ **À ÉVITER :**
- Modifier une migration déjà appliquée en production
- Supprimer des données sans backup
- Utiliser le même numéro de version deux fois

## Migrations actuelles

| Version | Description | Date |
|---------|-------------|------|
| 001_create_challenge_participants | Création table challenge_participants pour support N participants | 2026-01-14 |


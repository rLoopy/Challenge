#!/usr/bin/env python3
"""
Système de migration automatique pour Railway
Les migrations sont exécutées automatiquement au démarrage du bot
"""
import os
import psycopg2
from psycopg2.extras import RealDictCursor

def get_db():
    """Connexion à la base de données PostgreSQL"""
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        raise Exception("DATABASE_URL non défini")
    return psycopg2.connect(db_url, cursor_factory=RealDictCursor)

def ensure_migrations_table():
    """Crée la table de suivi des migrations si elle n'existe pas"""
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def is_migration_applied(version):
    """Vérifie si une migration a déjà été appliquée"""
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT version FROM schema_migrations WHERE version = %s', (version,))
    result = c.fetchone()
    conn.close()
    return result is not None

def mark_migration_applied(version):
    """Marque une migration comme appliquée"""
    conn = get_db()
    c = conn.cursor()
    c.execute('INSERT INTO schema_migrations (version) VALUES (%s)', (version,))
    conn.commit()
    conn.close()

def apply_migration(version, sql):
    """Applique une migration SQL"""
    if is_migration_applied(version):
        print(f"✓ Migration {version} déjà appliquée")
        return

    print(f"→ Application de la migration {version}...")
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute(sql)
        conn.commit()
        mark_migration_applied(version)
        print(f"✓ Migration {version} appliquée avec succès")
    except Exception as e:
        conn.rollback()
        print(f"✗ Erreur lors de la migration {version}: {e}")
        raise
    finally:
        conn.close()

def run_migrations():
    """Exécute toutes les migrations en attente"""
    print("=== Démarrage des migrations ===")
    ensure_migrations_table()

    # Migration 001: Créer la table challenge_participants
    apply_migration('001_create_challenge_participants', '''
        CREATE TABLE IF NOT EXISTS challenge_participants (
            id SERIAL PRIMARY KEY,
            challenge_id INTEGER NOT NULL,
            user_id BIGINT NOT NULL,
            user_name TEXT NOT NULL,
            gage TEXT NOT NULL,
            is_frozen INTEGER DEFAULT 0,
            streak INTEGER DEFAULT 0
        )
    ''')

    print("=== Migrations terminées ===\n")

if __name__ == '__main__':
    run_migrations()

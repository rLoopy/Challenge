"""
Challenge Bot - Track your commitments. No excuses.
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import datetime
from zoneinfo import ZoneInfo
import os
from typing import Optional
import psycopg2
from psycopg2.extras import RealDictCursor
from migrate import run_migrations

# Fuseau horaire français
PARIS_TZ = ZoneInfo("Europe/Paris")

# ══════════════════════════════════════════════════════════════
#                       CONFIG
# ══════════════════════════════════════════════════════════════

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Couleur unique pour tous les embeds (noir/gris foncé)
EMBED_COLOR = 0x2B2D31

# ══════════════════════════════════════════════════════════════
#                       EMBED HELPERS
# ══════════════════════════════════════════════════════════════

def progress_bar(current: int, goal: int, length: int = 10) -> str:
    """Barre de progression stylée ■■■■□□□□□□"""
    filled = min(current, goal)
    empty = max(0, goal - filled)

    # Ajuster pour la longueur
    ratio = filled / goal if goal > 0 else 0
    filled_blocks = int(ratio * length)
    empty_blocks = length - filled_blocks

    return "■" * filled_blocks + "□" * empty_blocks

def format_stat_line(label: str, value: str, width: int = 12) -> str:
    """Format une ligne de stat avec alignement"""
    dashes = "—" * (width - len(label))
    return f"{label} {dashes} {value}"

def get_days_remaining() -> int:
    """Jours restants dans la semaine"""
    now = datetime.datetime.now(PARIS_TZ)
    days = (6 - now.weekday())
    return days if days >= 0 else 0

def get_week_info():
    """Retourne (week_number, year) avec le fuseau horaire français"""
    now = datetime.datetime.now(PARIS_TZ)
    iso = now.isocalendar()
    return iso[1], iso[0]

def get_challenge_week_number(challenge_start_date: str) -> int:
    """Retourne le numéro de semaine du défi (1, 2, 3...) depuis le début"""
    start = datetime.datetime.fromisoformat(challenge_start_date)
    if start.tzinfo is None:
        start = start.replace(tzinfo=PARIS_TZ)
    now = datetime.datetime.now(PARIS_TZ)
    delta = now - start
    week_number = (delta.days // 7) + 1
    return max(1, week_number)

# ══════════════════════════════════════════════════════════════
#                       DATABASE (PostgreSQL / Supabase)
# ══════════════════════════════════════════════════════════════

DATABASE_URL = os.getenv('DATABASE_URL')

def get_db():
    """Connexion à PostgreSQL"""
    if not DATABASE_URL:
        raise Exception("DATABASE_URL non configurée")
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def init_db():
    """Initialise les tables dans PostgreSQL"""
    conn = get_db()
    c = conn.cursor()

    # Table des profils utilisateurs (global)
    c.execute('''
        CREATE TABLE IF NOT EXISTS profiles (
            user_id BIGINT PRIMARY KEY,
            user_name TEXT NOT NULL,
            activity TEXT DEFAULT 'Sport',
            weekly_goal INTEGER DEFAULT 4,
            pending_goal INTEGER
        )
    ''')

    # Migration: ajouter pending_goal si n'existe pas
    c.execute('''
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='profiles' AND column_name='pending_goal') THEN
                ALTER TABLE profiles ADD COLUMN pending_goal INTEGER;
            END IF;
        END $$;
    ''')

    # Migration: cycle personnalisé (cycle_days, cycle_goal, cycle_start_date)
    c.execute('''
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='profiles' AND column_name='cycle_days') THEN
                ALTER TABLE profiles ADD COLUMN cycle_days INTEGER DEFAULT 7;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='profiles' AND column_name='cycle_goal') THEN
                ALTER TABLE profiles ADD COLUMN cycle_goal INTEGER;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='profiles' AND column_name='cycle_start_date') THEN
                ALTER TABLE profiles ADD COLUMN cycle_start_date TEXT;
            END IF;
        END $$;
    ''')

    # Table des défis (par serveur) - NOUVELLE STRUCTURE SIMPLIFIÉE
    c.execute('''
        CREATE TABLE IF NOT EXISTS challenge (
            id SERIAL PRIMARY KEY,
            guild_id BIGINT NOT NULL,
            channel_id BIGINT NOT NULL,
            checkin_channel_id BIGINT,
            start_date TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            week_number INTEGER NOT NULL,
            total_weeks INTEGER DEFAULT 0
        )
    ''')

    # Table des participants (N participants par défi)
    c.execute('''
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

    # Migration: ajouter les colonnes manquantes à challenge si elles n'existent pas
    c.execute('''
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='challenge' AND column_name='guild_id') THEN
                ALTER TABLE challenge ADD COLUMN guild_id BIGINT;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='challenge' AND column_name='checkin_channel_id') THEN
                ALTER TABLE challenge ADD COLUMN checkin_channel_id BIGINT;
            END IF;
        END $$;
    ''')

    # Migration: rendre les anciennes colonnes nullable (pour compatibilité durant migration)
    c.execute('''
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='challenge' AND column_name='user1_id') THEN
                ALTER TABLE challenge ALTER COLUMN user1_id DROP NOT NULL;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='challenge' AND column_name='user1_name') THEN
                ALTER TABLE challenge ALTER COLUMN user1_name DROP NOT NULL;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='challenge' AND column_name='user1_gage') THEN
                ALTER TABLE challenge ALTER COLUMN user1_gage DROP NOT NULL;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='challenge' AND column_name='user2_id') THEN
                ALTER TABLE challenge ALTER COLUMN user2_id DROP NOT NULL;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='challenge' AND column_name='user2_name') THEN
                ALTER TABLE challenge ALTER COLUMN user2_name DROP NOT NULL;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='challenge' AND column_name='user2_gage') THEN
                ALTER TABLE challenge ALTER COLUMN user2_gage DROP NOT NULL;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='challenge' AND column_name='user1_activity') THEN
                ALTER TABLE challenge ALTER COLUMN user1_activity DROP NOT NULL;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='challenge' AND column_name='user1_goal') THEN
                ALTER TABLE challenge ALTER COLUMN user1_goal DROP NOT NULL;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='challenge' AND column_name='user2_activity') THEN
                ALTER TABLE challenge ALTER COLUMN user2_activity DROP NOT NULL;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='challenge' AND column_name='user2_goal') THEN
                ALTER TABLE challenge ALTER COLUMN user2_goal DROP NOT NULL;
            END IF;
        END $$;
    ''')

    # Migration automatique: déplacer user1/user2 vers challenge_participants
    c.execute('''
        DO $$
        BEGIN
            -- Vérifier si la migration est nécessaire (anciennes colonnes existent)
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='challenge' AND column_name='user1_id') THEN
                -- Migrer user1 pour tous les challenges qui n'ont pas encore de participants
                INSERT INTO challenge_participants (challenge_id, user_id, user_name, gage, is_frozen, streak)
                SELECT c.id, c.user1_id, c.user1_name, COALESCE(c.user1_gage, 'Gage non défini'),
                       COALESCE(c.freeze_user1, 0), COALESCE(c.streak_user1, 0)
                FROM challenge c
                WHERE c.user1_id IS NOT NULL
                AND NOT EXISTS (
                    SELECT 1 FROM challenge_participants cp
                    WHERE cp.challenge_id = c.id AND cp.user_id = c.user1_id
                );

                -- Migrer user2 pour tous les challenges qui n'ont pas encore de participants
                INSERT INTO challenge_participants (challenge_id, user_id, user_name, gage, is_frozen, streak)
                SELECT c.id, c.user2_id, c.user2_name, COALESCE(c.user2_gage, 'Gage non défini'),
                       COALESCE(c.freeze_user2, 0), COALESCE(c.streak_user2, 0)
                FROM challenge c
                WHERE c.user2_id IS NOT NULL
                AND NOT EXISTS (
                    SELECT 1 FROM challenge_participants cp
                    WHERE cp.challenge_id = c.id AND cp.user_id = c.user2_id
                );
            END IF;
        END $$;
    ''')

    # Table des check-ins (global par utilisateur)
    c.execute('''
        CREATE TABLE IF NOT EXISTS checkins (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            timestamp TEXT NOT NULL,
            week_number INTEGER NOT NULL,
            year INTEGER NOT NULL,
            photo_url TEXT,
            note TEXT
        )
    ''')

    # Migration: ajouter note si n'existe pas, rendre challenge_id nullable
    c.execute('''
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='checkins' AND column_name='note') THEN
                ALTER TABLE checkins ADD COLUMN note TEXT;
            END IF;
            -- Rendre challenge_id nullable (ancienne architecture)
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='checkins' AND column_name='challenge_id') THEN
                ALTER TABLE checkins ALTER COLUMN challenge_id DROP NOT NULL;
            END IF;
        END $$;
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS history (
            id SERIAL PRIMARY KEY,
            challenge_id INTEGER NOT NULL,
            guild_id BIGINT,
            winner_id BIGINT,
            winner_name TEXT,
            loser_id BIGINT,
            loser_name TEXT,
            loser_gage TEXT,
            end_date TEXT NOT NULL,
            reason TEXT NOT NULL,
            total_weeks INTEGER
        )
    ''')

    # Table des plans d'entraînement (rotation de séances)
    c.execute('''
        CREATE TABLE IF NOT EXISTS workout_plan (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            workout_name TEXT NOT NULL,
            workout_order INTEGER NOT NULL,
            is_cardio BOOLEAN DEFAULT FALSE
        )
    ''')

    # Migration: ajouter workout_name sur checkins
    c.execute('''
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='checkins' AND column_name='workout_name') THEN
                ALTER TABLE checkins ADD COLUMN workout_name TEXT;
            END IF;
        END $$;
    ''')

    # Créer les index pour optimiser les requêtes
    c.execute('CREATE INDEX IF NOT EXISTS idx_challenge_guild ON challenge(guild_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_challenge_active ON challenge(is_active)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_participants_challenge ON challenge_participants(challenge_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_participants_user ON challenge_participants(user_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_checkins_user ON checkins(user_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_checkins_week ON checkins(user_id, week_number, year)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_workout_plan_user ON workout_plan(user_id)')

    # One-time fix: cycle_days 10→9 + cycle_start_date 01/03→02/03 (old /adjustcycle bug)
    c.execute('''UPDATE profiles SET cycle_days = 9, cycle_start_date = '2026-03-02T00:00:00'
                 WHERE user_id = 265556280033148929 AND (cycle_days = 10 OR cycle_start_date = '2026-03-01T00:00:00')''')

    conn.commit()
    conn.close()
    print("✅ Base de données PostgreSQL initialisée")

def get_profile(user_id):
    """Récupère le profil d'un utilisateur"""
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM profiles WHERE user_id = %s', (user_id,))
    row = c.fetchone()
    conn.close()
    return row

def get_or_create_profile(user_id, user_name):
    """Récupère ou crée un profil utilisateur"""
    profile = get_profile(user_id)
    if profile:
        return profile

    conn = get_db()
    c = conn.cursor()
    c.execute('''
        INSERT INTO profiles (user_id, user_name, activity, weekly_goal)
        VALUES (%s, %s, 'Sport', 4)
        ON CONFLICT (user_id) DO NOTHING
    ''', (user_id, user_name))
    conn.commit()
    conn.close()
    return get_profile(user_id)

def get_active_challenge_for_guild(guild_id):
    """Récupère le défi actif pour un serveur"""
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM challenge WHERE guild_id = %s AND is_active = 1 ORDER BY id DESC LIMIT 1', (guild_id,))
    row = c.fetchone()
    conn.close()
    return row

def get_all_active_challenges():
    """Récupère tous les défis actifs (pour les tâches automatiques)"""
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM challenge WHERE is_active = 1')
    rows = c.fetchall()
    conn.close()
    return rows

def get_challenge_participants(challenge_id):
    """Récupère tous les participants d'un défi"""
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM challenge_participants WHERE challenge_id = %s', (challenge_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def get_participant(challenge_id, user_id):
    """Récupère un participant spécifique d'un défi"""
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM challenge_participants WHERE challenge_id = %s AND user_id = %s', (challenge_id, user_id))
    row = c.fetchone()
    conn.close()
    return row

def add_participant(challenge_id, user_id, user_name, gage):
    """Ajoute un participant à un défi"""
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        INSERT INTO challenge_participants (challenge_id, user_id, user_name, gage, is_frozen, streak)
        VALUES (%s, %s, %s, %s, 0, 0)
    ''', (challenge_id, user_id, user_name, gage))
    conn.commit()
    conn.close()

def remove_participant(challenge_id, user_id):
    """Retire un participant d'un défi"""
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM challenge_participants WHERE challenge_id = %s AND user_id = %s', (challenge_id, user_id))
    conn.commit()
    conn.close()

def get_user_active_challenges(user_id):
    """Récupère tous les défis actifs où un utilisateur participe"""
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT c.* FROM challenge c
        JOIN challenge_participants cp ON c.id = cp.challenge_id
        WHERE c.is_active = 1 AND cp.user_id = %s
    ''', (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def get_checkins_for_user_week(user_id, week_number, year, count_gym_only=False):
    """Récupère le nombre de check-ins d'un utilisateur pour une semaine

    Args:
        count_gym_only: Si True, compte uniquement les sessions gym (pas cardio)
    """
    conn = get_db()
    c = conn.cursor()
    if count_gym_only:
        c.execute('''
            SELECT COUNT(*) as count FROM checkins
            WHERE user_id = %s AND week_number = %s AND year = %s
            AND (session_type = 'gym' OR session_type IS NULL)
        ''', (user_id, week_number, year))
    else:
        c.execute('''
            SELECT COUNT(*) as count FROM checkins
            WHERE user_id = %s AND week_number = %s AND year = %s
        ''', (user_id, week_number, year))
    result = c.fetchone()['count']
    conn.close()
    return result

def get_total_checkins_user(user_id):
    """Récupère le total de check-ins d'un utilisateur"""
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) as count FROM checkins WHERE user_id = %s', (user_id,))
    result = c.fetchone()['count']
    conn.close()
    return result

def get_checkins_for_challenge_week(challenge_id, week_number, year):
    """Récupère les check-ins de la semaine pour tous les participants d'un défi"""
    participants = get_challenge_participants(challenge_id)
    result = {}
    for p in participants:
        result[p['user_id']] = get_checkins_for_user_week(p['user_id'], week_number, year)
    return result

def get_checkins_for_user_cycle(user_id, cycle_start_date, cycle_days):
    """Compte les check-ins dans un cycle personnalisé (par plage de dates)"""
    start = datetime.datetime.fromisoformat(cycle_start_date)
    if start.tzinfo is None:
        start = start.replace(tzinfo=PARIS_TZ)
    end = start + datetime.timedelta(days=cycle_days)

    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT COUNT(*) as count FROM checkins
        WHERE user_id = %s AND timestamp >= %s AND timestamp < %s
    ''', (user_id, start.isoformat(), end.isoformat()))
    result = c.fetchone()['count']
    conn.close()
    return result

def get_user_progress(user_id, profile=None):
    """Retourne (count, goal) pour un utilisateur, gère weekly et custom cycles"""
    if profile is None:
        profile = get_profile(user_id)

    cycle_days = (profile.get('cycle_days') or 7) if profile else 7

    if cycle_days == 7:
        week_number, year = get_week_info()
        count = get_checkins_for_user_week(user_id, week_number, year, count_gym_only=False)
        goal = profile['weekly_goal'] if profile else 4
        return count, goal
    else:
        cycle_goal = (profile.get('cycle_goal') or profile['weekly_goal']) if profile else 4
        cycle_start = profile.get('cycle_start_date') if profile else None
        if not cycle_start:
            return 0, cycle_goal
        count = get_checkins_for_user_cycle(user_id, cycle_start, cycle_days)
        return count, cycle_goal

def get_cycle_days_remaining(profile):
    """Retourne les jours restants dans le cycle d'un utilisateur"""
    cycle_days = (profile.get('cycle_days') or 7) if profile else 7
    if cycle_days == 7:
        return get_days_remaining()
    cycle_start = profile.get('cycle_start_date')
    if not cycle_start:
        return cycle_days
    start = datetime.datetime.fromisoformat(cycle_start)
    if start.tzinfo is None:
        start = start.replace(tzinfo=PARIS_TZ)
    end = start + datetime.timedelta(days=cycle_days)
    now = datetime.datetime.now(PARIS_TZ)
    return max(0, (end - now).days)

def get_cycle_label(profile):
    """Retourne le label du cycle (SEMAINE ou CYCLE Xj)"""
    cycle_days = (profile.get('cycle_days') or 7) if profile else 7
    if cycle_days == 7:
        return "CETTE SEMAINE"
    return f"CYCLE ({cycle_days}J)"

def is_custom_cycle(profile):
    """Vérifie si un utilisateur a un cycle personnalisé"""
    return profile and (profile.get('cycle_days') or 7) != 7

# ── Workout plan helpers ──

def get_workout_plan(user_id):
    """Récupère le plan d'entraînement d'un utilisateur, trié par ordre"""
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM workout_plan WHERE user_id = %s ORDER BY workout_order', (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def get_cycle_workout_status(user_id, profile=None):
    """Retourne les séances faites dans le cycle en cours (dict workout_name -> count)"""
    if profile is None:
        profile = get_profile(user_id)

    cycle_days = (profile.get('cycle_days') or 7) if profile else 7

    conn = get_db()
    c = conn.cursor()

    if cycle_days == 7:
        week_number, year = get_week_info()
        c.execute('''
            SELECT workout_name, COUNT(*) as count FROM checkins
            WHERE user_id = %s AND week_number = %s AND year = %s
            AND workout_name IS NOT NULL
            GROUP BY workout_name
        ''', (user_id, week_number, year))
    else:
        cycle_start = profile.get('cycle_start_date') if profile else None
        if not cycle_start:
            conn.close()
            return {}
        start = datetime.datetime.fromisoformat(cycle_start)
        if start.tzinfo is None:
            start = start.replace(tzinfo=PARIS_TZ)
        end = start + datetime.timedelta(days=cycle_days)
        c.execute('''
            SELECT workout_name, COUNT(*) as count FROM checkins
            WHERE user_id = %s AND timestamp >= %s AND timestamp < %s
            AND workout_name IS NOT NULL
            GROUP BY workout_name
        ''', (user_id, start.isoformat(), end.isoformat()))

    rows = c.fetchall()
    conn.close()
    return {row['workout_name']: row['count'] for row in rows}

def format_rotation_status(plan, done_workouts, highlight=None):
    """Génère le texte visuel de la rotation"""
    lines = []
    for entry in plan:
        name = entry['workout_name']
        is_cardio = entry.get('is_cardio', False)

        if is_cardio:
            # Compter combien de cardio sont dans le plan
            cardio_total = sum(1 for e in plan if e.get('is_cardio', False))
            cardio_done = done_workouts.get(name, 0)
            if name == highlight:
                lines.append(f"▸ {name} ({cardio_done}/{cardio_total})  ← now")
            elif cardio_done >= cardio_total:
                lines.append(f"✓ {name} ({cardio_done}/{cardio_total})")
            else:
                lines.append(f"□ {name} ({cardio_done}/{cardio_total})")
            return "\n".join(lines)  # Cardio est toujours le dernier
        else:
            done = done_workouts.get(name, 0) > 0
            if name == highlight:
                lines.append(f"▸ {name}  ← now")
            elif done:
                lines.append(f"✓ {name}")
            else:
                lines.append(f"□ {name}")

    return "\n".join(lines)

def get_remaining_workouts(plan, done_workouts):
    """Retourne la liste des séances pas encore faites dans le cycle"""
    remaining = []
    for entry in plan:
        name = entry['workout_name']
        is_cardio = entry.get('is_cardio', False)
        if is_cardio:
            cardio_total = sum(1 for e in plan if e.get('is_cardio', False))
            cardio_done = done_workouts.get(name, 0)
            if cardio_done < cardio_total:
                remaining.append(entry)
        else:
            if done_workouts.get(name, 0) == 0:
                remaining.append(entry)
    return remaining

# ══════════════════════════════════════════════════════════════
#                       UI VIEWS
# ══════════════════════════════════════════════════════════════

class WorkoutSelectView(discord.ui.View):
    """Menu déroulant pour choisir quelle séance on a faite"""

    def __init__(self, checkin_id: int, user_id: int, remaining_workouts: list, plan: list):
        super().__init__(timeout=300)
        self.checkin_id = checkin_id
        self.allowed_user_id = user_id
        self.plan = plan

        options = []
        seen_cardio = False
        for entry in remaining_workouts:
            if entry.get('is_cardio') and seen_cardio:
                continue
            if entry.get('is_cardio'):
                seen_cardio = True
            icon = "🏃" if entry.get('is_cardio') else "🏋️"
            options.append(discord.SelectOption(
                label=entry['workout_name'],
                value=entry['workout_name'],
                emoji=icon
            ))

        if not options:
            return

        select = discord.ui.Select(
            placeholder="Quelle séance ?",
            options=options,
            min_values=1,
            max_values=1
        )
        select.callback = self.on_select
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.allowed_user_id:
            await interaction.response.send_message("Ce menu n'est pas pour toi.", ephemeral=True)
            return False
        return True

    async def on_select(self, interaction: discord.Interaction):
        selected = interaction.data['values'][0]

        # Déterminer le session_type à partir du plan
        is_cardio = any(
            e['workout_name'] == selected and e.get('is_cardio')
            for e in self.plan
        )
        new_session_type = 'cardio' if is_cardio else 'gym'

        # Mettre à jour le check-in en DB
        conn = get_db()
        c = conn.cursor()
        c.execute('''
            UPDATE checkins SET workout_name = %s, session_type = %s WHERE id = %s
        ''', (selected, new_session_type, self.checkin_id))
        conn.commit()
        conn.close()

        # Recalculer le statut de la rotation
        profile = get_profile(self.allowed_user_id)
        done = get_cycle_workout_status(self.allowed_user_id, profile)
        rotation_text = format_rotation_status(self.plan, done, highlight=selected)

        # Éditer le message pour ajouter la rotation
        original_embed = interaction.message.embeds[0] if interaction.message.embeds else None
        if original_embed:
            desc = original_embed.description or ""
            desc += f"\n\n◆ **ROTATION**\n```\n{rotation_text}\n```"
            original_embed.description = desc
            await interaction.response.edit_message(embed=original_embed, view=None)
        else:
            await interaction.response.edit_message(view=None)

        self.stop()

    async def on_timeout(self):
        pass

# ══════════════════════════════════════════════════════════════
#                       BOT EVENTS
# ══════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    print(f"Bot connecté: {bot.user}")
    run_migrations()
    init_db()
    try:
        synced = await bot.tree.sync()
        print(f"{len(synced)} commandes synchronisées")
    except Exception as e:
        print(f"Erreur: {e}")

    check_weekly_goals.start()
    send_reminders.start()
    check_custom_cycles.start()

# ══════════════════════════════════════════════════════════════
#                       COMMANDS
# ══════════════════════════════════════════════════════════════

@bot.tree.command(name="profile", description="Configurer ton profil")
@app_commands.describe(
    activity="Ton activité (ex: Sport, Salle, Course)",
    goal="Ton objectif hebdomadaire (sessions par semaine)"
)
async def profile_cmd(
    interaction: discord.Interaction,
    activity: Optional[str] = None,
    goal: Optional[int] = None
):
    user_id = interaction.user.id
    user_name = interaction.user.display_name

    # Récupérer ou créer le profil
    profile = get_or_create_profile(user_id, user_name)

    goal_change_msg = ""

    # Si des paramètres sont fournis, mettre à jour
    if activity is not None or goal is not None:
        if goal is not None and (goal <= 0 or goal > 7):
            await interaction.response.send_message("Objectif entre 1 et 7.", ephemeral=True)
            return

        conn = get_db()
        c = conn.cursor()

        new_activity = activity if activity else profile['activity']

        # Si changement de goal
        if goal is not None and goal != profile['weekly_goal']:
            now = datetime.datetime.now(PARIS_TZ)
            # Si c'est lundi, appliquer immédiatement
            if now.weekday() == 0:
                c.execute('''
                    UPDATE profiles SET activity = %s, weekly_goal = %s, pending_goal = NULL, user_name = %s
                    WHERE user_id = %s
                ''', (new_activity, goal, user_name, user_id))
                goal_change_msg = f"\n✓ Objectif changé à {goal}x/semaine"
            else:
                # Sinon, mettre en pending pour lundi prochain
                c.execute('''
                    UPDATE profiles SET activity = %s, pending_goal = %s, user_name = %s
                    WHERE user_id = %s
                ''', (new_activity, goal, user_name, user_id))
                goal_change_msg = f"\n⏳ Objectif passera à {goal}x/semaine lundi"
        else:
            c.execute('''
                UPDATE profiles SET activity = %s, user_name = %s
                WHERE user_id = %s
            ''', (new_activity, user_name, user_id))

        conn.commit()
        conn.close()

        profile = get_profile(user_id)

    # Statistiques
    total_checkins = get_total_checkins_user(user_id)
    current_count, current_goal = get_user_progress(user_id, profile)
    active_challenges = get_user_active_challenges(user_id)

    # Afficher pending_goal si défini
    pending_goal = profile.get('pending_goal')
    cycle_days = profile.get('cycle_days') or 7
    if cycle_days == 7:
        goal_display = f"{profile['weekly_goal']}x/semaine"
        if pending_goal:
            goal_display += f" → {pending_goal}x lundi"
        period_label = "CETTE SEMAINE"
    else:
        cycle_goal = profile.get('cycle_goal') or profile['weekly_goal']
        goal_display = f"{cycle_goal}x/{cycle_days}j"
        period_label = f"CYCLE ({cycle_days}J)"

    embed = discord.Embed(color=EMBED_COLOR)
    embed.description = f"""▸ **PROFIL**

**{user_name.upper()}**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **CONFIGURATION**
```
{format_stat_line("ACTIVITÉ", profile['activity'])}
{format_stat_line("OBJECTIF", goal_display)}
```

◆ **STATS**
```
{format_stat_line(period_label, f"{current_count}/{current_goal}")}
{format_stat_line("TOTAL", str(total_checkins))}
{format_stat_line("DÉFIS ACTIFS", str(len(active_challenges)))}
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

▼ Modifier: `/profile activity:X goal:X`{goal_change_msg}"""

    embed.set_footer(text="◆ Challenge Bot")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="challenges", description="Voir tous tes défis actifs")
async def challenges_cmd(interaction: discord.Interaction):
    user_id = interaction.user.id
    user_name = interaction.user.display_name

    challenges = get_user_active_challenges(user_id)

    if not challenges:
        await interaction.response.send_message("Tu n'as pas de défi actif.", ephemeral=True)
        return

    profile = get_profile(user_id)
    user_count, user_goal = get_user_progress(user_id, profile)
    user_period = get_cycle_label(profile)

    challenges_text = ""
    for challenge in challenges:
        participants = get_challenge_participants(challenge['id'])
        my_participant = next((p for p in participants if int(p['user_id']) == user_id), None)
        others = [p for p in participants if int(p['user_id']) != user_id]

        my_gage = my_participant['gage'] if my_participant else "?"
        is_frozen = my_participant.get('is_frozen', 0) if my_participant else 0

        # Trouver le nom du serveur
        guild = bot.get_guild(challenge['guild_id'])
        guild_name = guild.name if guild else f"Serveur #{challenge['guild_id']}"

        # Status
        freeze_tag = " ❄" if is_frozen else ""
        my_status = "✓" if user_count >= user_goal or is_frozen else f"{user_count}/{user_goal}"

        # Construire la liste des autres
        others_text = ""
        for other in others:
            other_user_id = int(other['user_id'])
            other_profile = get_profile(other_user_id)
            other_count, other_goal = get_user_progress(other_user_id, other_profile)
            freeze_mark = "❄" if other.get('is_frozen', 0) else ""
            others_text += f"{other['user_name'][:8]}: {other_count}/{other_goal}{freeze_mark} "

        challenges_text += f"""
◆ **{guild_name}**{freeze_tag}
```
Toi: {my_status} | {others_text.strip()}
Gage: {my_gage[:20]}
```
"""

    embed = discord.Embed(color=EMBED_COLOR)
    embed.description = f"""▸ **TES DÉFIS**

**{user_name.upper()}** — {user_count}/{user_goal} {user_period.lower()}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{challenges_text}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

💡 Un check-in compte pour tous tes défis !"""

    embed.set_footer(text="◆ Challenge Bot")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="setup", description="Créer un défi sur ce serveur")
@app_commands.describe(
    adversaire="Ton adversaire",
    ton_gage="Ton gage si tu perds",
    son_gage="Son gage si il/elle perd",
    son_objectif="Son objectif hebdo (optionnel, pour setup à sa place)"
)
async def setup(
    interaction: discord.Interaction,
    adversaire: discord.Member,
    ton_gage: str,
    son_gage: str,
    son_objectif: Optional[int] = None
):
    if not interaction.guild:
        await interaction.response.send_message("Cette commande doit être utilisée dans un serveur.", ephemeral=True)
        return

    guild_id = interaction.guild.id
    user_id = interaction.user.id

    # Vérifier si un défi existe déjà sur ce serveur
    challenge = get_active_challenge_for_guild(guild_id)
    if challenge:
        await interaction.response.send_message("Un défi est déjà en cours sur ce serveur. Utilise `/addplayer` pour ajouter quelqu'un.", ephemeral=True)
        return

    if user_id == adversaire.id:
        await interaction.response.send_message("Tu ne peux pas te défier toi-même.", ephemeral=True)
        return

    if son_objectif is not None and (son_objectif <= 0 or son_objectif > 7):
        await interaction.response.send_message("Objectif entre 1 et 7.", ephemeral=True)
        return

    # Récupérer/créer les profils
    profile1 = get_or_create_profile(user_id, interaction.user.display_name)
    profile2 = get_or_create_profile(adversaire.id, adversaire.display_name)

    # Si objectif adversaire spécifié, mettre à jour son profil
    if son_objectif is not None:
        conn = get_db()
        c = conn.cursor()
        c.execute('UPDATE profiles SET weekly_goal = %s WHERE user_id = %s', (son_objectif, adversaire.id))
        conn.commit()
        conn.close()
        profile2 = get_profile(adversaire.id)  # Recharger

    conn = get_db()
    c = conn.cursor()

    week_number, year = get_week_info()
    start_date = datetime.datetime.now().isoformat()

    # Créer le défi (nouvelle structure simplifiée)
    c.execute('''
        INSERT INTO challenge
        (guild_id, channel_id, checkin_channel_id, start_date, week_number, total_weeks)
        VALUES (%s, %s, %s, %s, %s, 0)
        RETURNING id
    ''', (guild_id, interaction.channel_id, interaction.channel_id, start_date, week_number))

    challenge_id = c.fetchone()['id']

    # Ajouter les participants
    c.execute('''
        INSERT INTO challenge_participants (challenge_id, user_id, user_name, gage, is_frozen, streak)
        VALUES (%s, %s, %s, %s, 0, 0)
    ''', (challenge_id, user_id, interaction.user.display_name, ton_gage))

    c.execute('''
        INSERT INTO challenge_participants (challenge_id, user_id, user_name, gage, is_frozen, streak)
        VALUES (%s, %s, %s, %s, 0, 0)
    ''', (challenge_id, adversaire.id, adversaire.display_name, son_gage))

    conn.commit()
    conn.close()

    # Embed stylé
    embed = discord.Embed(color=EMBED_COLOR)

    embed.description = f"""▸ **NOUVEAU DÉFI**

{interaction.user.display_name} **vs** {adversaire.display_name}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **{interaction.user.display_name.upper()}**
```
{format_stat_line("ACTIVITÉ", profile1['activity'])}
{format_stat_line("OBJECTIF", f"{profile1['weekly_goal']}x/semaine")}
{format_stat_line("GAGE", ton_gage[:20])}
```

◆ **{adversaire.display_name.upper()}**
```
{format_stat_line("ACTIVITÉ", profile2['activity'])}
{format_stat_line("OBJECTIF", f"{profile2['weekly_goal']}x/semaine")}
{format_stat_line("GAGE", son_gage[:20])}
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

▼ **Règles**
Lundi → Dimanche • Photo obligatoire
Objectif manqué = **GAME OVER** (individuel)

💡 Check-ins partagés sur tous vos serveurs
💡 Ajoute des joueurs avec `/addplayer`"""

    embed.set_footer(text=f"◆ Challenge Bot • {datetime.datetime.now().strftime('%d/%m/%Y')}")

    await interaction.response.send_message(f"<@{adversaire.id}>", embed=embed)


@bot.tree.command(name="setchannel", description="Définir le salon des check-ins automatiques")
@app_commands.describe(channel="Salon où poster les check-ins")
async def setchannel_cmd(interaction: discord.Interaction, channel: discord.TextChannel):
    if not interaction.guild:
        await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
        return

    guild_id = interaction.guild.id
    challenge = get_active_challenge_for_guild(guild_id)

    if not challenge:
        await interaction.response.send_message("Pas de défi actif sur ce serveur.", ephemeral=True)
        return

    # Vérifier que l'utilisateur participe
    user_id = interaction.user.id
    participant = get_participant(challenge['id'], user_id)
    if not participant:
        await interaction.response.send_message("Tu ne participes pas à ce défi.", ephemeral=True)
        return

    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE challenge SET checkin_channel_id = %s WHERE id = %s', (channel.id, challenge['id']))
    conn.commit()
    conn.close()

    embed = discord.Embed(color=EMBED_COLOR)
    embed.description = f"""▸ **SALON CONFIGURÉ**

Les check-ins seront postés dans {channel.mention}"""
    embed.set_footer(text="◆ Challenge Bot")

    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="addplayer", description="Ajouter un joueur au défi")
@app_commands.describe(
    joueur="Joueur à ajouter",
    gage="Son gage si il/elle perd",
    objectif="Son objectif hebdo (optionnel)"
)
async def addplayer_cmd(
    interaction: discord.Interaction,
    joueur: discord.Member,
    gage: str,
    objectif: Optional[int] = None
):
    if not interaction.guild:
        await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
        return

    guild_id = interaction.guild.id
    challenge = get_active_challenge_for_guild(guild_id)

    if not challenge:
        await interaction.response.send_message("Pas de défi actif. Utilise `/setup` d'abord.", ephemeral=True)
        return

    # Vérifier que la personne qui ajoute participe
    user_id = interaction.user.id
    participant = get_participant(challenge['id'], user_id)
    if not participant:
        await interaction.response.send_message("Tu ne participes pas à ce défi.", ephemeral=True)
        return

    # Vérifier que le joueur n'est pas déjà dans le défi
    existing = get_participant(challenge['id'], joueur.id)
    if existing:
        await interaction.response.send_message(f"{joueur.display_name} participe déjà.", ephemeral=True)
        return

    if objectif is not None and (objectif <= 0 or objectif > 7):
        await interaction.response.send_message("Objectif entre 1 et 7.", ephemeral=True)
        return

    # Créer/récupérer le profil du joueur
    profile = get_or_create_profile(joueur.id, joueur.display_name)

    # Si objectif spécifié, mettre à jour
    if objectif is not None:
        conn = get_db()
        c = conn.cursor()
        c.execute('UPDATE profiles SET weekly_goal = %s WHERE user_id = %s', (objectif, joueur.id))
        conn.commit()
        conn.close()
        profile = get_profile(joueur.id)

    # Ajouter le participant
    add_participant(challenge['id'], joueur.id, joueur.display_name, gage)

    participants = get_challenge_participants(challenge['id'])

    embed = discord.Embed(color=EMBED_COLOR)
    embed.description = f"""▸ **JOUEUR AJOUTÉ**

**{joueur.display_name}** rejoint le défi !

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **CONFIGURATION**
```
{format_stat_line("ACTIVITÉ", profile['activity'])}
{format_stat_line("OBJECTIF", f"{profile['weekly_goal']}x/semaine")}
{format_stat_line("GAGE", gage[:20])}
```

◆ **PARTICIPANTS** ({len(participants)})
{', '.join([p['user_name'] for p in participants])}"""

    embed.set_footer(text="◆ Challenge Bot")

    await interaction.response.send_message(f"<@{joueur.id}>", embed=embed)


@bot.tree.command(name="removeplayer", description="Retirer un joueur du défi")
@app_commands.describe(joueur="Joueur à retirer")
async def removeplayer_cmd(interaction: discord.Interaction, joueur: discord.Member):
    if not interaction.guild:
        await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
        return

    guild_id = interaction.guild.id
    challenge = get_active_challenge_for_guild(guild_id)

    if not challenge:
        await interaction.response.send_message("Pas de défi actif.", ephemeral=True)
        return

    # Vérifier que le joueur participe
    existing = get_participant(challenge['id'], joueur.id)
    if not existing:
        await interaction.response.send_message(f"{joueur.display_name} ne participe pas.", ephemeral=True)
        return

    # Vérifier qu'il reste au moins 2 participants après
    participants = get_challenge_participants(challenge['id'])
    if len(participants) <= 2:
        await interaction.response.send_message("Il doit rester au moins 2 participants. Utilise `/cancel` pour annuler le défi.", ephemeral=True)
        return

    # Retirer le participant
    remove_participant(challenge['id'], joueur.id)

    participants = get_challenge_participants(challenge['id'])

    embed = discord.Embed(color=EMBED_COLOR)
    embed.description = f"""▸ **JOUEUR RETIRÉ**

**{joueur.display_name}** quitte le défi.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **PARTICIPANTS RESTANTS** ({len(participants)})
{', '.join([p['user_name'] for p in participants])}"""

    embed.set_footer(text="◆ Challenge Bot")

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="setgoal", description="Changer l'objectif hebdo d'un joueur")
@app_commands.describe(
    joueur="Le joueur dont tu veux changer l'objectif",
    objectif="Nouvel objectif (sessions par semaine, entre 1 et 7)"
)
async def setgoal_cmd(
    interaction: discord.Interaction,
    joueur: discord.Member,
    objectif: int
):
    if not interaction.guild:
        await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
        return

    if objectif <= 0 or objectif > 7:
        await interaction.response.send_message("L'objectif doit être entre 1 et 7.", ephemeral=True)
        return

    guild_id = interaction.guild.id
    challenge = get_active_challenge_for_guild(guild_id)

    if not challenge:
        await interaction.response.send_message("Pas de défi actif sur ce serveur.", ephemeral=True)
        return

    # Vérifier que le joueur participe au défi
    participant = get_participant(challenge['id'], joueur.id)
    if not participant:
        await interaction.response.send_message(f"{joueur.display_name} ne participe pas au défi.", ephemeral=True)
        return

    # Récupérer l'ancien objectif
    profile = get_or_create_profile(joueur.id, joueur.display_name)
    old_goal = profile['weekly_goal']

    if old_goal == objectif:
        await interaction.response.send_message(f"{joueur.display_name} a déjà un objectif de {objectif}x/semaine.", ephemeral=True)
        return

    # Mettre à jour immédiatement
    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE profiles SET weekly_goal = %s, pending_goal = NULL WHERE user_id = %s', (objectif, joueur.id))
    conn.commit()
    conn.close()

    # Stats actuelles
    week_number, year = get_week_info()
    week_checkins = get_checkins_for_user_week(joueur.id, week_number, year, count_gym_only=False)

    embed = discord.Embed(color=EMBED_COLOR)
    embed.description = f"""▸ **OBJECTIF MODIFIÉ**

**{joueur.display_name}**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **CHANGEMENT**
```
{format_stat_line("AVANT", f"{old_goal}x/semaine")}
{format_stat_line("APRÈS", f"{objectif}x/semaine")}
```

◆ **PROGRESSION**
```
{format_stat_line("CETTE SEMAINE", f"{week_checkins}/{objectif}")}
{progress_bar(week_checkins, objectif)}
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

▼ Changement appliqué immédiatement."""

    embed.set_footer(text="◆ Challenge Bot")
    await interaction.response.send_message(f"<@{joueur.id}>", embed=embed)


@bot.tree.command(name="setworkouts", description="Définir ta rotation de séances")
@app_commands.describe(
    plan="Séances muscu séparées par des virgules (ex: Pecs/Bi, EP/Tri, Dos/Bras, Legs, Fonctionnelle)",
    cardio="Nombre de séances cardio par cycle (défaut: 0)",
    supprimer="Supprimer ton plan de rotation"
)
async def setworkouts_cmd(
    interaction: discord.Interaction,
    plan: Optional[str] = None,
    cardio: Optional[int] = 0,
    supprimer: Optional[bool] = False
):
    user_id = interaction.user.id

    if supprimer:
        conn = get_db()
        c = conn.cursor()
        c.execute('DELETE FROM workout_plan WHERE user_id = %s', (user_id,))
        conn.commit()
        conn.close()

        embed = discord.Embed(color=EMBED_COLOR)
        embed.description = "▸ **PLAN SUPPRIMÉ**\n\nTa rotation de séances a été supprimée."
        embed.set_footer(text="◆ Challenge Bot")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # Si pas de plan fourni, afficher le plan actuel
    if plan is None:
        existing = get_workout_plan(user_id)
        if not existing:
            await interaction.response.send_message(
                "Tu n'as pas de plan. Crée-en un avec:\n`/setworkouts plan:\"Pecs/Bi, EP/Tri, Dos/Bras, Legs, Fonctionnelle\" cardio:2`",
                ephemeral=True
            )
            return

        plan_text = ""
        for entry in existing:
            icon = "🏃" if entry.get('is_cardio') else "🏋️"
            plan_text += f"{icon} {entry['workout_name']}\n"

        # Afficher aussi le statut du cycle en cours
        profile = get_or_create_profile(user_id, interaction.user.display_name)
        done = get_cycle_workout_status(user_id, profile)
        rotation_text = format_rotation_status(existing, done)

        embed = discord.Embed(color=EMBED_COLOR)
        embed.description = f"""▸ **TON PLAN**

◆ **SÉANCES**
```
{plan_text.strip()}
```

◆ **{get_cycle_label(profile)}**
```
{rotation_text}
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

▼ Modifier: `/setworkouts plan:\"...\" cardio:X`
▼ Supprimer: `/setworkouts supprimer:True`"""
        embed.set_footer(text="◆ Challenge Bot")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # Parser le plan
    workouts = [w.strip() for w in plan.split(',') if w.strip()]

    if not workouts:
        await interaction.response.send_message("Plan vide. Sépare les séances par des virgules.", ephemeral=True)
        return

    if len(workouts) > 10:
        await interaction.response.send_message("Maximum 10 séances muscu.", ephemeral=True)
        return

    cardio_count = max(0, min(cardio or 0, 7))

    # Remplacer le plan existant
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM workout_plan WHERE user_id = %s', (user_id,))

    order = 1
    for workout in workouts:
        c.execute('''
            INSERT INTO workout_plan (user_id, workout_name, workout_order, is_cardio)
            VALUES (%s, %s, %s, FALSE)
        ''', (user_id, workout, order))
        order += 1

    # Ajouter les slots cardio
    if cardio_count > 0:
        for _ in range(cardio_count):
            c.execute('''
                INSERT INTO workout_plan (user_id, workout_name, workout_order, is_cardio)
                VALUES (%s, %s, %s, TRUE)
            ''', (user_id, "Cardio", order))
            order += 1

    conn.commit()
    conn.close()

    # Construire l'affichage
    plan_text = ""
    for w in workouts:
        plan_text += f"🏋️ {w}\n"
    if cardio_count > 0:
        plan_text += f"🏃 Cardio x{cardio_count}\n"

    total = len(workouts) + cardio_count

    embed = discord.Embed(color=EMBED_COLOR)
    embed.description = f"""▸ **PLAN CONFIGURÉ**

◆ **ROTATION** ({total} séances)
```
{plan_text.strip()}
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

▼ Après chaque check-in, un menu te proposera tes séances.
▼ Modifier: `/setworkouts plan:\"...\" cardio:X`"""

    embed.set_footer(text="◆ Challenge Bot")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="setcycle", description="Passer un joueur en cycle personnalisé (ex: 7 sessions sur 9 jours)")
@app_commands.describe(
    joueur="Le joueur à configurer",
    jours="Durée du cycle en jours (ex: 9)",
    objectif="Nombre de sessions à atteindre dans le cycle (ex: 7)",
    reset="Remettre en mode semaine classique (7j)"
)
async def setcycle_cmd(
    interaction: discord.Interaction,
    joueur: discord.Member,
    jours: Optional[int] = None,
    objectif: Optional[int] = None,
    reset: Optional[bool] = False
):
    if not interaction.guild:
        await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
        return

    profile = get_or_create_profile(joueur.id, joueur.display_name)

    if reset:
        conn = get_db()
        c = conn.cursor()
        c.execute('''
            UPDATE profiles SET cycle_days = 7, cycle_goal = NULL, cycle_start_date = NULL
            WHERE user_id = %s
        ''', (joueur.id,))
        conn.commit()
        conn.close()

        embed = discord.Embed(color=EMBED_COLOR)
        embed.description = f"""▸ **CYCLE RÉINITIALISÉ**

**{joueur.display_name}** repasse en mode **semaine classique** (7j).

Objectif: {profile['weekly_goal']}x/semaine"""
        embed.set_footer(text="◆ Challenge Bot")
        await interaction.response.send_message(embed=embed)
        return

    if jours is None or objectif is None:
        await interaction.response.send_message(
            "Précise `jours` et `objectif`. Ex: `/setcycle joueur:@X jours:9 objectif:7`",
            ephemeral=True
        )
        return

    if jours < 2 or jours > 30:
        await interaction.response.send_message("Le cycle doit être entre 2 et 30 jours.", ephemeral=True)
        return

    if objectif <= 0 or objectif > jours:
        await interaction.response.send_message(f"L'objectif doit être entre 1 et {jours}.", ephemeral=True)
        return

    now = datetime.datetime.now(PARIS_TZ)
    # Si après 18h, le cycle commence demain à minuit
    if now.hour >= 18:
        start_date = (now + datetime.timedelta(days=1)).strftime('%Y-%m-%dT00:00:00')
    else:
        start_date = now.strftime('%Y-%m-%dT00:00:00')
    cycle_start = start_date

    conn = get_db()
    c = conn.cursor()
    c.execute('''
        UPDATE profiles SET cycle_days = %s, cycle_goal = %s, cycle_start_date = %s
        WHERE user_id = %s
    ''', (jours, objectif, cycle_start, joueur.id))
    conn.commit()
    conn.close()

    # Compter les sessions déjà faites
    current_count, current_goal = get_user_progress(joueur.id)

    cycle_start_dt = datetime.datetime.fromisoformat(cycle_start).replace(tzinfo=PARIS_TZ)
    cycle_end = cycle_start_dt + datetime.timedelta(days=jours)
    cycle_end_str = cycle_end.strftime('%d/%m')

    embed = discord.Embed(color=EMBED_COLOR)
    embed.description = f"""▸ **CYCLE PERSONNALISÉ**

**{joueur.display_name}**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **CONFIGURATION**
```
{format_stat_line("CYCLE", f"{jours} jours")}
{format_stat_line("OBJECTIF", f"{objectif} sessions")}
{format_stat_line("FIN CYCLE", cycle_end_str)}
```

◆ **PROGRESSION**
```
{format_stat_line("SESSIONS", f"{current_count}/{objectif}")}
{progress_bar(current_count, objectif)}
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

▼ Cycle démarre le {cycle_start_dt.strftime('%d/%m à %H:%M')}.
▼ Vérification auto à la fin de chaque cycle.
▼ `/setcycle reset:True` pour revenir en semaine."""

    embed.set_footer(text="◆ Challenge Bot")
    await interaction.response.send_message(f"<@{joueur.id}>", embed=embed)


@bot.tree.command(name="adjustcycle", description="Ajuster le cycle en cours d'un joueur (+/- jours)")
@app_commands.describe(
    joueur="Le joueur à ajuster",
    jours="Nombre de jours à ajouter ou retirer (ex: +1, -2)"
)
async def adjustcycle_cmd(
    interaction: discord.Interaction,
    joueur: discord.Member,
    jours: int
):
    if not interaction.guild:
        await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
        return

    profile = get_or_create_profile(joueur.id, joueur.display_name)

    cycle_days = profile.get('cycle_days') or 7
    cycle_start = profile.get('cycle_start_date')

    if cycle_days == 7 or not cycle_start:
        await interaction.response.send_message(
            f"**{joueur.display_name}** n'a pas de cycle personnalisé en cours.",
            ephemeral=True
        )
        return

    start_dt = datetime.datetime.fromisoformat(cycle_start)
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=PARIS_TZ)

    # Reculer le start_date pour étendre le cycle (ne touche PAS cycle_days)
    new_start = start_dt - datetime.timedelta(days=jours)
    new_end = new_start + datetime.timedelta(days=cycle_days)
    old_end = start_dt + datetime.timedelta(days=cycle_days)

    cycle_goal = profile.get('cycle_goal') or profile['weekly_goal']

    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE profiles SET cycle_start_date = %s WHERE user_id = %s',
              (new_start.isoformat(), joueur.id))
    conn.commit()
    conn.close()

    current_count, _ = get_user_progress(joueur.id)
    updated_profile = {**profile, 'cycle_start_date': new_start.isoformat()}
    days_remaining = get_cycle_days_remaining(updated_profile)

    signe = f"+{jours}" if jours > 0 else str(jours)

    embed = discord.Embed(color=EMBED_COLOR)
    embed.description = f"""▸ **CYCLE AJUSTÉ**

**{joueur.display_name}**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

```
{format_stat_line("FIN AVANT", old_end.strftime('%d/%m'))}
{format_stat_line("AJUST.", signe + "j")}
{format_stat_line("FIN APRÈS", new_end.strftime('%d/%m'))}
{format_stat_line("CYCLE", f"{cycle_days}j (inchangé)")}
{format_stat_line("SESSIONS", f"{current_count}/{cycle_goal}")}
{format_stat_line("RESTANT", f"{days_remaining}j")}
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

▼ Seul ce cycle est affecté. Les prochains seront de {cycle_days}j."""

    embed.set_footer(text="◆ Challenge Bot")
    await interaction.response.send_message(f"<@{joueur.id}>", embed=embed)


@bot.tree.command(name="cycleinfo", description="Afficher les détails de ton cycle en cours")
async def cycleinfo_cmd(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
        return

    user_id = interaction.user.id
    profile = get_or_create_profile(user_id, interaction.user.display_name)

    if not is_custom_cycle(profile):
        week_number, year = get_week_info()
        count = get_checkins_for_user_week(user_id, week_number, year, count_gym_only=False)
        goal = profile['weekly_goal']
        days_left = get_days_remaining()

        now = datetime.datetime.now(PARIS_TZ)
        monday = now - datetime.timedelta(days=now.weekday())
        sunday = monday + datetime.timedelta(days=6)

        embed = discord.Embed(color=EMBED_COLOR)
        embed.description = f"""▸ **INFOS CYCLE** — {interaction.user.display_name}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

```
{format_stat_line("MODE", "Semaine standard")}
{format_stat_line("PÉRIODE", f"{monday.strftime('%d/%m')} → {sunday.strftime('%d/%m')}")}
{format_stat_line("OBJECTIF", f"{goal} sessions / 7j")}
{format_stat_line("SESSIONS", f"{count}/{goal}")}
{format_stat_line("RESTANT", f"{days_left}j")}
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
        embed.set_footer(text="◆ Challenge Bot")
        await interaction.response.send_message(embed=embed)
        return

    cycle_days = profile.get('cycle_days') or 7
    cycle_goal = profile.get('cycle_goal') or profile['weekly_goal']
    cycle_start = profile.get('cycle_start_date')

    start_dt = datetime.datetime.fromisoformat(cycle_start)
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=PARIS_TZ)
    end_dt = start_dt + datetime.timedelta(days=cycle_days)

    now = datetime.datetime.now(PARIS_TZ)
    elapsed = (now - start_dt).days
    remaining = max(0, (end_dt - now).days)

    count, _ = get_user_progress(user_id, profile)

    sessions_left = max(0, cycle_goal - count)
    status = "✓ Objectif atteint !" if count >= cycle_goal else f"{sessions_left} session(s) à faire"

    plan = get_workout_plan(user_id)
    rotation_text = ""
    if plan:
        done_workouts = get_cycle_workout_status(user_id, profile)
        rotation_text = f"\n\n▸ **ROTATION**\n```\n{format_rotation_status(plan, done_workouts)}\n```"

    embed = discord.Embed(color=EMBED_COLOR)
    embed.description = f"""▸ **INFOS CYCLE** — {interaction.user.display_name}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

```
{format_stat_line("MODE", f"Cycle perso ({cycle_days}j)")}
{format_stat_line("DÉBUT", start_dt.strftime('%d/%m/%Y %Hh%M'))}
{format_stat_line("FIN", end_dt.strftime('%d/%m/%Y %Hh%M'))}
{format_stat_line("ÉCOULÉS", f"{elapsed}j")}
{format_stat_line("RESTANT", f"{remaining}j")}
{format_stat_line("OBJECTIF", f"{cycle_goal} sessions")}
{format_stat_line("SESSIONS", f"{count}/{cycle_goal}")}
{format_stat_line("STATUT", status)}
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━{rotation_text}"""

    embed.set_footer(text="◆ Challenge Bot")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="checkin", description="Enregistrer une session")
@app_commands.describe(
    photo="Photo de ta session",
    type="Type de session (Gym par défaut)",
    note="Note optionnelle (ex: Push day, Course 5km...)"
)
@app_commands.choices(type=[
    app_commands.Choice(name="🏋️ Gym", value="gym"),
    app_commands.Choice(name="🏃 Cardio", value="cardio")
])
async def checkin(interaction: discord.Interaction, photo: discord.Attachment, type: Optional[str] = "gym", note: Optional[str] = None):
    user_id = interaction.user.id
    user_name = interaction.user.display_name

    # Vérifier que l'utilisateur a au moins un défi actif
    active_challenges = get_user_active_challenges(user_id)

    if not active_challenges:
        await interaction.response.send_message("Tu n'as pas de défi actif. Utilise `/setup` pour en créer un.", ephemeral=True)
        return

    if not photo.content_type or not photo.content_type.startswith('image/'):
        await interaction.response.send_message("Image requise.", ephemeral=True)
        return

    # Defer pour éviter le timeout de 3 secondes
    await interaction.response.defer()

    # Récupérer le profil
    profile = get_or_create_profile(user_id, user_name)

    # Enregistrer le check-in (global)
    conn = get_db()
    c = conn.cursor()

    week_number, year = get_week_info()
    timestamp = datetime.datetime.now().isoformat()

    session_type = type or "gym"

    c.execute('''
        INSERT INTO checkins (user_id, timestamp, week_number, year, photo_url, note, session_type)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    ''', (user_id, timestamp, week_number, year, photo.url, note, session_type))
    checkin_id = c.fetchone()['id']

    conn.commit()
    conn.close()

    user_count, user_goal = get_user_progress(user_id, profile)
    user_activity = profile['activity']
    days = get_cycle_days_remaining(profile)

    # Statut
    if user_count >= user_goal:
        status = "✓ VALIDÉ"
        status_emoji = "★"
    else:
        status = "En cours"
        status_emoji = "▸"

    # Construire l'embed principal
    note_text = f"\n📝 *{note}*" if note else ""

    # Récupérer le défi du serveur actuel pour afficher tous les participants
    current_guild_id = interaction.guild.id if interaction.guild else None
    current_challenge = get_active_challenge_for_guild(current_guild_id) if current_guild_id else None

    # Construire la progression de tous les participants du serveur actuel
    progression_text = f"{user_name[:10]:10} {progress_bar(user_count, user_goal)} {user_count}/{user_goal}\n"
    ping_ids = []

    if current_challenge:
        participants = get_challenge_participants(current_challenge['id'])
        for p in participants:
            p_user_id = int(p['user_id'])
            if p_user_id != user_id:
                p_profile = get_profile(p_user_id)
                p_count, p_goal = get_user_progress(p_user_id, p_profile)
                p_frozen = p.get('is_frozen', 0)
                if p_frozen:
                    progression_text += f"{p['user_name'][:10]:10} ❄️ FREEZE\n"
                else:
                    progression_text += f"{p['user_name'][:10]:10} {progress_bar(p_count, p_goal)} {p_count}/{p_goal}\n"
                ping_ids.append(p_user_id)

    # Deadline adaptée au type de cycle
    if is_custom_cycle(profile):
        cd = profile.get('cycle_days', 7)
        deadline_text = f"{format_stat_line('JOURS', f'{days}j')}\n{format_stat_line('CYCLE', f'{cd}j')}"
    else:
        deadline_text = f"{format_stat_line('JOURS', f'{days}j')}\n{format_stat_line('DEADLINE', 'Dimanche 23h')}"

    embed = discord.Embed(color=EMBED_COLOR)
    embed.description = f"""{status_emoji} **{status.upper()}**

**{user_name.upper()}**

{user_activity}
**{user_count} / {user_goal}**{note_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **PROGRESSION**
```
{progression_text.strip()}
```

◆ **TEMPS RESTANT**
```
{deadline_text}
```"""

    embed.set_image(url=photo.url)
    embed.set_footer(text=f"◆ Challenge Bot • {datetime.datetime.now().strftime('%H:%M')}")

    # Compter les autres serveurs où on doit cross-poster
    other_challenges = [ch for ch in active_challenges if ch['guild_id'] != current_guild_id]

    # Ajouter le feedback cross-post prévu
    if other_challenges:
        embed.description += f"\n\n📤 Cross-post vers {len(other_challenges)} serveur(s)..."

    # Préparer le menu de workout si l'utilisateur a un plan
    workout_view = None
    workout_plan = get_workout_plan(user_id)
    if workout_plan:
        done_workouts = get_cycle_workout_status(user_id, profile)
        remaining = get_remaining_workouts(workout_plan, done_workouts)
        if remaining:
            workout_view = WorkoutSelectView(checkin_id, user_id, remaining, workout_plan)

    # Répondre à l'interaction (après defer)
    ping_content = " ".join([f"<@{pid}>" for pid in ping_ids]) if ping_ids else None
    await interaction.followup.send(content=ping_content, embed=embed, view=workout_view)

    # Cross-poster sur les autres serveurs (après avoir répondu)
    cross_post_success = 0
    cross_post_fail = 0

    for challenge in other_challenges:
        # Trouver le salon de check-in
        checkin_channel_id = challenge.get('checkin_channel_id') or challenge['channel_id']
        channel = bot.get_channel(checkin_channel_id)

        if channel:
            # Récupérer tous les participants
            participants = get_challenge_participants(challenge['id'])
            others = [p for p in participants if int(p['user_id']) != user_id]

            # Construire la progression de tous les participants
            progression_text = f"{user_name[:10]:10} {progress_bar(user_count, user_goal)} {user_count}/{user_goal}\n"
            ping_ids = []

            for other in others:
                other_user_id = int(other['user_id'])
                other_profile = get_profile(other_user_id)
                other_count, other_goal = get_user_progress(other_user_id, other_profile)
                other_frozen = other.get('is_frozen', 0)
                if other_frozen:
                    progression_text += f"{other['user_name'][:10]:10} ❄️ FREEZE\n"
                else:
                    progression_text += f"{other['user_name'][:10]:10} {progress_bar(other_count, other_goal)} {other_count}/{other_goal}\n"
                ping_ids.append(other_user_id)

            # Embed pour ce serveur avec progression de tous
            cross_embed = discord.Embed(color=EMBED_COLOR)
            cross_embed.description = f"""{status_emoji} **CHECK-IN**

**{user_name.upper()}**

{user_activity}{note_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **PROGRESSION**
```
{progression_text.strip()}
```"""

            cross_embed.set_image(url=photo.url)
            cross_embed.set_footer(text=f"◆ Challenge Bot • Cross-post")

            try:
                ping_content = " ".join([f"<@{pid}>" for pid in ping_ids])
                await channel.send(content=ping_content, embed=cross_embed)
                cross_post_success += 1
            except Exception as e:
                print(f"Erreur cross-post vers {challenge['guild_id']}: {e}")
                cross_post_fail += 1
        else:
            cross_post_fail += 1

    # Mettre à jour le message original avec le résultat du cross-post
    if other_challenges:
        cross_post_feedback = ""
        if cross_post_success > 0:
            cross_post_feedback = f"✓ Posté sur {cross_post_success} serveur(s)"
        if cross_post_fail > 0:
            if cross_post_feedback:
                cross_post_feedback += " | "
            cross_post_feedback += f"⚠ Échec: {cross_post_fail}"

        # Mettre à jour l'embed
        new_description = embed.description.replace(
            f"📤 Cross-post vers {len(other_challenges)} serveur(s)...",
            cross_post_feedback
        )
        embed.description = new_description

        try:
            await interaction.edit_original_response(embed=embed)
        except:
            pass  # Silently fail if we can't edit


@bot.tree.command(name="latecheckin", description="Enregistrer une session d'hier")
@app_commands.describe(
    photo="Photo de ta session",
    type="Type de session (Gym par défaut)",
    note="Note optionnelle"
)
@app_commands.choices(type=[
    app_commands.Choice(name="🏋️ Gym", value="gym"),
    app_commands.Choice(name="🏃 Cardio", value="cardio")
])
async def latecheckin(interaction: discord.Interaction, photo: discord.Attachment, type: Optional[str] = "gym", note: Optional[str] = None):
    user_id = interaction.user.id
    user_name = interaction.user.display_name

    # Vérifier que l'utilisateur a au moins un défi actif
    active_challenges = get_user_active_challenges(user_id)

    if not active_challenges:
        await interaction.response.send_message("Tu n'as pas de défi actif.", ephemeral=True)
        return

    if not photo.content_type or not photo.content_type.startswith('image/'):
        await interaction.response.send_message("Image requise.", ephemeral=True)
        return

    # Calculer hier
    now = datetime.datetime.now(PARIS_TZ)
    yesterday = now - datetime.timedelta(days=1)

    # Vérifier que hier est dans la même semaine (pas la semaine dernière)
    yesterday_iso = yesterday.isocalendar()
    today_iso = now.isocalendar()

    if yesterday_iso[1] != today_iso[1]:
        await interaction.response.send_message(
            "⚠ Hier était la semaine dernière. Utilise `/rescue` si le défi est terminé.",
            ephemeral=True
        )
        return

    # Defer pour éviter le timeout
    await interaction.response.defer()

    # Récupérer le profil
    profile = get_or_create_profile(user_id, user_name)

    # Enregistrer le check-in avec la date d'hier
    conn = get_db()
    c = conn.cursor()

    week_number = yesterday_iso[1]
    year = yesterday_iso[0]
    timestamp = yesterday.replace(hour=20, minute=0, second=0).isoformat()  # 20h hier

    late_note = f"[HIER] {note}" if note else "[HIER]"
    session_type = type or "gym"

    c.execute('''
        INSERT INTO checkins (user_id, timestamp, week_number, year, photo_url, note, session_type)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    ''', (user_id, timestamp, week_number, year, photo.url, late_note, session_type))
    checkin_id = c.fetchone()['id']

    conn.commit()
    conn.close()

    user_count, user_goal = get_user_progress(user_id, profile)
    user_activity = profile['activity']
    days = get_cycle_days_remaining(profile)

    # Statut
    if user_count >= user_goal:
        status = "✓ VALIDÉ"
        status_emoji = "★"
    else:
        status = "En cours"
        status_emoji = "▸"

    # Construire l'embed principal
    note_text = f"\n📝 *{note}*" if note else ""
    yesterday_str = yesterday.strftime('%d/%m')

    # Récupérer le défi du serveur actuel pour afficher tous les participants
    current_guild_id = interaction.guild.id if interaction.guild else None
    current_challenge = get_active_challenge_for_guild(current_guild_id) if current_guild_id else None

    # Construire la progression de tous les participants
    progression_text = f"{user_name[:10]:10} {progress_bar(user_count, user_goal)} {user_count}/{user_goal}\n"
    ping_ids = []

    if current_challenge:
        participants = get_challenge_participants(current_challenge['id'])
        for p in participants:
            p_user_id = int(p['user_id'])
            if p_user_id != user_id:
                p_profile = get_profile(p_user_id)
                p_count, p_goal = get_user_progress(p_user_id, p_profile)
                p_frozen = p.get('is_frozen', 0)
                if p_frozen:
                    progression_text += f"{p['user_name'][:10]:10} ❄️ FREEZE\n"
                else:
                    progression_text += f"{p['user_name'][:10]:10} {progress_bar(p_count, p_goal)} {p_count}/{p_goal}\n"
                ping_ids.append(p_user_id)

    if is_custom_cycle(profile):
        cd = profile.get('cycle_days', 7)
        deadline_text = f"{format_stat_line('JOURS', f'{days}j')}\n{format_stat_line('CYCLE', f'{cd}j')}"
    else:
        deadline_text = f"{format_stat_line('JOURS', f'{days}j')}\n{format_stat_line('DEADLINE', 'Dimanche 23h')}"

    embed = discord.Embed(color=EMBED_COLOR)
    embed.description = f"""{status_emoji} **{status.upper()}** (hier {yesterday_str})

**{user_name.upper()}**

{user_activity}
**{user_count} / {user_goal}**{note_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **PROGRESSION**
```
{progression_text.strip()}
```

◆ **TEMPS RESTANT**
```
{deadline_text}
```

⏰ *Check-in enregistré pour hier*"""

    embed.set_image(url=photo.url)
    embed.set_footer(text=f"◆ Challenge Bot • Late check-in")

    # Compter les autres serveurs
    other_challenges = [ch for ch in active_challenges if ch['guild_id'] != current_guild_id]

    if other_challenges:
        embed.description += f"\n\n📤 Cross-post vers {len(other_challenges)} serveur(s)..."

    # Préparer le menu de workout
    workout_view = None
    workout_plan = get_workout_plan(user_id)
    if workout_plan:
        done_workouts = get_cycle_workout_status(user_id, profile)
        remaining = get_remaining_workouts(workout_plan, done_workouts)
        if remaining:
            workout_view = WorkoutSelectView(checkin_id, user_id, remaining, workout_plan)

    ping_content = " ".join([f"<@{pid}>" for pid in ping_ids]) if ping_ids else None
    await interaction.followup.send(content=ping_content, embed=embed, view=workout_view)

    # Cross-poster sur les autres serveurs
    cross_post_success = 0
    cross_post_fail = 0

    for challenge in other_challenges:
        checkin_channel_id = challenge.get('checkin_channel_id') or challenge['channel_id']
        channel = bot.get_channel(checkin_channel_id)

        if channel:
            participants = get_challenge_participants(challenge['id'])
            others = [p for p in participants if int(p['user_id']) != user_id]

            progression_text = f"{user_name[:10]:10} {progress_bar(user_count, user_goal)} {user_count}/{user_goal}\n"
            cross_ping_ids = []

            for other in others:
                other_user_id = int(other['user_id'])
                other_profile = get_profile(other_user_id)
                other_count, other_goal = get_user_progress(other_user_id, other_profile)
                other_frozen = other.get('is_frozen', 0)
                if other_frozen:
                    progression_text += f"{other['user_name'][:10]:10} ❄️ FREEZE\n"
                else:
                    progression_text += f"{other['user_name'][:10]:10} {progress_bar(other_count, other_goal)} {other_count}/{other_goal}\n"
                cross_ping_ids.append(other_user_id)

            cross_embed = discord.Embed(color=EMBED_COLOR)
            cross_embed.description = f"""{status_emoji} **CHECK-IN** (hier)

**{user_name.upper()}**

{user_activity}{note_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **PROGRESSION**
```
{progression_text.strip()}
```

⏰ *Late check-in*"""

            cross_embed.set_image(url=photo.url)
            cross_embed.set_footer(text=f"◆ Challenge Bot • Cross-post")

            try:
                cross_ping_content = " ".join([f"<@{pid}>" for pid in cross_ping_ids])
                await channel.send(content=cross_ping_content, embed=cross_embed)
                cross_post_success += 1
            except:
                cross_post_fail += 1
        else:
            cross_post_fail += 1

    # Mettre à jour avec le résultat
    if other_challenges:
        cross_post_feedback = ""
        if cross_post_success > 0:
            cross_post_feedback = f"✓ Posté sur {cross_post_success} serveur(s)"
        if cross_post_fail > 0:
            if cross_post_feedback:
                cross_post_feedback += " | "
            cross_post_feedback += f"⚠ Échec: {cross_post_fail}"

        new_description = embed.description.replace(
            f"📤 Cross-post vers {len(other_challenges)} serveur(s)...",
            cross_post_feedback
        )
        embed.description = new_description

        try:
            await interaction.edit_original_response(embed=embed)
        except:
            pass


@bot.tree.command(name="checkinfor", description="Enregistrer une session pour quelqu'un d'autre")
@app_commands.describe(
    membre="La personne pour qui enregistrer",
    type="Type de session (Gym par défaut)",
    note="Note optionnelle"
)
@app_commands.choices(type=[
    app_commands.Choice(name="🏋️ Gym", value="gym"),
    app_commands.Choice(name="🏃 Cardio", value="cardio")
])
async def checkinfor(interaction: discord.Interaction, membre: discord.Member, type: Optional[str] = "gym", note: Optional[str] = None):
    user_id = membre.id
    user_name = membre.display_name
    by_name = interaction.user.display_name

    # Vérifier que la personne a au moins un défi actif
    active_challenges = get_user_active_challenges(user_id)

    if not active_challenges:
        await interaction.response.send_message(f"{membre.mention} n'a pas de défi actif.", ephemeral=True)
        return

    # Defer pour éviter le timeout
    await interaction.response.defer()

    # Récupérer le profil
    profile = get_or_create_profile(user_id, user_name)

    # Enregistrer le check-in
    conn = get_db()
    c = conn.cursor()

    week_number, year = get_week_info()
    timestamp = datetime.datetime.now().isoformat()

    checkin_note = f"[par {by_name}] {note}" if note else f"[par {by_name}]"
    session_type = type or "gym"

    c.execute('''
        INSERT INTO checkins (user_id, timestamp, week_number, year, photo_url, note, session_type)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    ''', (user_id, timestamp, week_number, year, None, checkin_note, session_type))
    checkin_id = c.fetchone()['id']

    conn.commit()
    conn.close()

    user_count, user_goal = get_user_progress(user_id, profile)
    user_activity = profile['activity']
    days = get_cycle_days_remaining(profile)

    # Statut
    if user_count >= user_goal:
        status = "✓ VALIDÉ"
        status_emoji = "★"
    else:
        status = "En cours"
        status_emoji = "▸"

    note_text = f"\n📝 *{note}*" if note else ""

    # Récupérer le défi du serveur actuel pour afficher tous les participants
    current_guild_id = interaction.guild.id if interaction.guild else None
    current_challenge = get_active_challenge_for_guild(current_guild_id) if current_guild_id else None

    # Construire la progression de tous les participants
    progression_text = f"{user_name[:10]:10} {progress_bar(user_count, user_goal)} {user_count}/{user_goal}\n"
    ping_ids = []

    if current_challenge:
        participants = get_challenge_participants(current_challenge['id'])
        for p in participants:
            p_user_id = int(p['user_id'])
            if p_user_id != user_id:
                p_profile = get_profile(p_user_id)
                p_count, p_goal = get_user_progress(p_user_id, p_profile)
                p_frozen = p.get('is_frozen', 0)
                if p_frozen:
                    progression_text += f"{p['user_name'][:10]:10} ❄️ FREEZE\n"
                else:
                    progression_text += f"{p['user_name'][:10]:10} {progress_bar(p_count, p_goal)} {p_count}/{p_goal}\n"
                ping_ids.append(p_user_id)

    if is_custom_cycle(profile):
        cd = profile.get('cycle_days', 7)
        deadline_text = f"{format_stat_line('JOURS', f'{days}j')}\n{format_stat_line('CYCLE', f'{cd}j')}"
    else:
        deadline_text = f"{format_stat_line('JOURS', f'{days}j')}\n{format_stat_line('DEADLINE', 'Dimanche 23h')}"

    embed = discord.Embed(color=EMBED_COLOR)
    embed.description = f"""{status_emoji} **{status.upper()}**

**{user_name.upper()}**

{user_activity}
**{user_count} / {user_goal}**{note_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **PROGRESSION**
```
{progression_text.strip()}
```

◆ **TEMPS RESTANT**
```
{deadline_text}
```

👤 *Enregistré par {by_name}*"""

    embed.set_footer(text=f"◆ Challenge Bot • {datetime.datetime.now().strftime('%H:%M')}")

    # Compter les serveurs pour cross-post
    other_challenges = [ch for ch in active_challenges if ch['guild_id'] != current_guild_id]

    if other_challenges:
        embed.description += f"\n\n📤 Cross-post vers {len(other_challenges)} serveur(s)..."

    # Préparer le menu de workout (pour le membre, pas l'auteur)
    workout_view = None
    workout_plan_member = get_workout_plan(user_id)
    if workout_plan_member:
        done_workouts = get_cycle_workout_status(user_id, profile)
        remaining = get_remaining_workouts(workout_plan_member, done_workouts)
        if remaining:
            workout_view = WorkoutSelectView(checkin_id, user_id, remaining, workout_plan_member)

    # Ping le membre + les autres participants
    ping_content = f"{membre.mention} " + " ".join([f"<@{pid}>" for pid in ping_ids])
    await interaction.followup.send(content=ping_content.strip(), embed=embed, view=workout_view)

    # Cross-poster sur les autres serveurs
    cross_post_success = 0
    cross_post_fail = 0

    for challenge in other_challenges:
        checkin_channel_id = challenge.get('checkin_channel_id') or challenge['channel_id']
        channel = bot.get_channel(checkin_channel_id)

        if channel:
            participants = get_challenge_participants(challenge['id'])
            others = [p for p in participants if int(p['user_id']) != user_id]

            progression_text = f"{user_name[:10]:10} {progress_bar(user_count, user_goal)} {user_count}/{user_goal}\n"
            ping_ids = []

            for other in others:
                other_user_id = int(other['user_id'])
                other_profile = get_profile(other_user_id)
                other_count, other_goal = get_user_progress(other_user_id, other_profile)
                other_frozen = other.get('is_frozen', 0)
                if other_frozen:
                    progression_text += f"{other['user_name'][:10]:10} ❄️ FREEZE\n"
                else:
                    progression_text += f"{other['user_name'][:10]:10} {progress_bar(other_count, other_goal)} {other_count}/{other_goal}\n"
                ping_ids.append(other_user_id)

            cross_embed = discord.Embed(color=EMBED_COLOR)
            cross_embed.description = f"""{status_emoji} **CHECK-IN**

**{user_name.upper()}**

{user_activity}{note_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **PROGRESSION**
```
{progression_text.strip()}
```

👤 *Par {by_name}*"""

            cross_embed.set_footer(text=f"◆ Challenge Bot • Cross-post")

            try:
                ping_content = " ".join([f"<@{pid}>" for pid in ping_ids])
                await channel.send(content=ping_content, embed=cross_embed)
                cross_post_success += 1
            except:
                cross_post_fail += 1
        else:
            cross_post_fail += 1

    # Mettre à jour avec le résultat
    if other_challenges:
        cross_post_feedback = ""
        if cross_post_success > 0:
            cross_post_feedback = f"✓ Posté sur {cross_post_success} serveur(s)"
        if cross_post_fail > 0:
            if cross_post_feedback:
                cross_post_feedback += " | "
            cross_post_feedback += f"⚠ Échec: {cross_post_fail}"

        new_description = embed.description.replace(
            f"📤 Cross-post vers {len(other_challenges)} serveur(s)...",
            cross_post_feedback
        )
        embed.description = new_description

        try:
            await interaction.edit_original_response(embed=embed)
        except:
            pass


@bot.tree.command(name="deletecheckin", description="Supprimer un check-in en double")
@app_commands.describe(
    checkin_id="ID du check-in à supprimer (voir /mycheckins)"
)
async def deletecheckin(interaction: discord.Interaction, checkin_id: int):
    user_id = interaction.user.id

    conn = get_db()
    c = conn.cursor()

    # Vérifier que le check-in existe et appartient à l'utilisateur
    c.execute('SELECT id, timestamp, note FROM checkins WHERE id = %s AND user_id = %s', (checkin_id, user_id))
    checkin = c.fetchone()

    if not checkin:
        conn.close()
        await interaction.response.send_message(
            f"❌ Check-in #{checkin_id} introuvable ou ne t'appartient pas.\nUtilise `/mycheckins` pour voir tes check-ins.",
            ephemeral=True
        )
        return

    # Supprimer le check-in
    c.execute('DELETE FROM checkins WHERE id = %s', (checkin_id,))
    conn.commit()
    conn.close()

    timestamp = checkin['timestamp'][:10] if checkin['timestamp'] else "?"
    note = checkin['note'] or ""

    await interaction.response.send_message(
        f"✅ Check-in #{checkin_id} supprimé ({timestamp} {note})",
        ephemeral=True
    )


@bot.tree.command(name="mycheckins", description="Voir mes check-ins de la semaine")
async def mycheckins(interaction: discord.Interaction):
    user_id = interaction.user.id
    week_number, year = get_week_info()

    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT id, timestamp, note, session_type
        FROM checkins
        WHERE user_id = %s AND week_number = %s AND year = %s
        ORDER BY timestamp DESC
    ''', (user_id, week_number, year))
    checkins = c.fetchall()
    conn.close()

    if not checkins:
        await interaction.response.send_message("Aucun check-in cette semaine.", ephemeral=True)
        return

    lines = []
    for ci in checkins:
        ts = ci['timestamp'][:16].replace('T', ' ') if ci['timestamp'] else "?"
        note = f" - {ci['note']}" if ci['note'] else ""
        session_type = ci.get('session_type') or 'gym'
        type_icon = "🏃" if session_type == 'cardio' else "🏋️"
        lines.append(f"**#{ci['id']}** {type_icon} | {ts}{note}")

    embed = discord.Embed(
        title=f"📋 Mes check-ins (Semaine {week_number})",
        description="\n".join(lines),
        color=EMBED_COLOR
    )
    embed.set_footer(text="Pour supprimer: /deletecheckin <id>")

    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="stats", description="Voir les statistiques du défi")
async def stats(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
        return

    guild_id = interaction.guild.id
    challenge = get_active_challenge_for_guild(guild_id)

    if not challenge:
        await interaction.response.send_message("Pas de défi actif sur ce serveur.", ephemeral=True)
        return

    week_number, year = get_week_info()
    participants = get_challenge_participants(challenge['id'])

    challenge_week = get_challenge_week_number(challenge['start_date'])
    days = get_days_remaining()

    # Vérifier si c'est une semaine "d'échauffement"
    warmup_week = False
    start_week = challenge.get('week_number', 0)
    if start_week == week_number:
        start_date_str = challenge.get('start_date')
        if start_date_str:
            start_date = datetime.datetime.fromisoformat(start_date_str)
            if start_date.weekday() != 0:
                warmup_week = True

    # Construire les stats de chaque participant
    participants_stats = []
    all_validated = True
    leader = None
    leader_pct = -1

    for p in participants:
        profile = get_profile(p['user_id'])
        count, goal = get_user_progress(p['user_id'], profile)
        activity = profile['activity'] if profile else 'Sport'
        total = get_total_checkins_user(p['user_id'])
        frozen = p.get('is_frozen', 0)

        pct = count / goal if goal > 0 else 0
        validated = count >= goal or frozen

        if not validated and not frozen:
            all_validated = False

        if pct > leader_pct and not frozen:
            leader_pct = pct
            leader = p['user_name']

        participants_stats.append({
            'name': p['user_name'],
            'activity': activity,
            'goal': goal,
            'count': count,
            'total': total,
            'frozen': frozen,
            'gage': p['gage'],
            'validated': validated,
            'pct': pct
        })

    # Status général
    if warmup_week:
        status_text = "⚡ Semaine d'échauffement (non comptée)"
    elif all_validated:
        status_text = "✓ Tous ont validé"
    elif leader:
        status_text = f"▸ {leader} mène"
    else:
        status_text = "▸ En cours"

    # Calcul du temps restant
    if days == 0:
        time_status = "⚠ DERNIER JOUR"
    elif days == 1:
        time_status = f"{days} jour restant"
    else:
        time_status = f"{days} jours restants"

    # Construire l'embed avec tous les participants
    participants_text = ""
    for ps in participants_stats:
        freeze_tag = " ❄" if ps['frozen'] else ""
        status_mark = "✓" if ps['validated'] else ""
        freeze_mark = "FREEZE" if ps['frozen'] else ""

        participants_text += f"""
◆ **{ps['name'].upper()}**{freeze_tag} — {ps['activity']}
```
CETTE SEMAINE ——— {ps['count']}/{ps['goal']}
{progress_bar(ps['count'], ps['goal'])} {status_mark}{freeze_mark}

TOTAL ——————————— {ps['total']}
GAGE ———————————— {ps['gage'][:15]}
```
"""

    embed = discord.Embed(color=EMBED_COLOR)

    embed.description = f"""▸ **SEMAINE {challenge_week}**

{status_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{participants_text}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **DEADLINE**
```
{time_status}
Vérification: Dimanche minuit
```"""

    embed.set_footer(text=f"◆ Challenge Bot • Semaine {challenge_week} • {len(participants)} participants")

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="cancel", description="Annuler le défi sur ce serveur")
async def cancel(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
        return

    guild_id = interaction.guild.id
    challenge = get_active_challenge_for_guild(guild_id)

    if not challenge:
        await interaction.response.send_message("Pas de défi actif sur ce serveur.", ephemeral=True)
        return

    participant = get_participant(challenge['id'], interaction.user.id)
    if not participant:
        await interaction.response.send_message("Réservé aux participants.", ephemeral=True)
        return

    challenge_id = challenge['id']

    class ConfirmView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=30)

        @discord.ui.button(label="Confirmer", style=discord.ButtonStyle.danger)
        async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
            conn = get_db()
            c = conn.cursor()
            c.execute('UPDATE challenge SET is_active = 0 WHERE id = %s', (challenge_id,))
            conn.commit()
            conn.close()

            embed = discord.Embed(color=EMBED_COLOR)
            embed.description = """▸ **DÉFI ANNULÉ**

Le défi a été annulé sur ce serveur.
Aucun gagnant, aucun perdant.

Utilisez `/setup` pour recommencer."""

            await interaction.response.edit_message(embed=embed, view=None)
            self.stop()

        @discord.ui.button(label="Retour", style=discord.ButtonStyle.secondary)
        async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.edit_message(content="Annulation annulée.", embed=None, view=None)
            self.stop()

    embed = discord.Embed(color=EMBED_COLOR)
    embed.description = """▸ **CONFIRMATION**

Voulez-vous vraiment annuler le défi sur ce serveur ?

Cette action est irréversible."""

    await interaction.response.send_message(embed=embed, view=ConfirmView(), ephemeral=True)


@bot.tree.command(name="calendar", description="Ton calendrier personnel (30 derniers jours)")
async def calendar_cmd(interaction: discord.Interaction):
    user_id = interaction.user.id
    user_name = interaction.user.display_name

    # Récupérer le profil
    profile = get_or_create_profile(user_id, user_name)
    user_activity = profile['activity']

    # Récupérer les check-ins des 30 derniers jours
    now = datetime.datetime.now()
    today = now.date()
    thirty_days_ago = today - datetime.timedelta(days=30)

    conn = get_db()
    c = conn.cursor()

    # Récupérer tous les check-ins pour cet utilisateur (global) avec session_type
    c.execute('''
        SELECT timestamp, note, session_type FROM checkins
        WHERE user_id = %s
        ORDER BY timestamp DESC
    ''', (user_id,))

    rows = c.fetchall()
    conn.close()

    # Extraire les dates avec check-in (30 derniers jours) et tracker le type
    # On garde une entrée par date avec le type (si plusieurs check-ins le même jour, on prend le premier)
    checkin_data = {}  # date -> session_type
    gym_count = 0
    cardio_count = 0

    for row in rows:
        ts = datetime.datetime.fromisoformat(row['timestamp'])
        ts_date = ts.date()
        if ts_date >= thirty_days_ago and ts_date <= today:
            session_type = row.get('session_type') or 'gym'
            if ts_date not in checkin_data:
                checkin_data[ts_date] = session_type
            # Compter gym vs cardio
            if session_type == 'cardio':
                cardio_count += 1
            else:
                gym_count += 1

    # Trier les dates
    checkin_dates = sorted(checkin_data.keys())

    # Noms des jours
    day_names = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]

    # Construire la timeline
    timeline = ""
    for checkin_date in checkin_dates:
        day_name = day_names[checkin_date.weekday()]
        session_type = checkin_data[checkin_date]

        # Afficher 🏃 pour cardio
        if session_type == 'cardio':
            if checkin_date == today:
                timeline += f"│  {checkin_date.day:02d} {day_name} ━━◆ 🏃 today   │\n"
            else:
                timeline += f"│  {checkin_date.day:02d} {day_name} ━━● 🏃          │\n"
        else:
            if checkin_date == today:
                timeline += f"│  {checkin_date.day:02d} {day_name} ━━◆ aujourd'hui  │\n"
            else:
                timeline += f"│  {checkin_date.day:02d} {day_name} ━━●              │\n"

    # Si pas de check-ins
    if not checkin_dates:
        timeline = "│                          │\n"
        timeline += "│    Aucune session        │\n"
        timeline += "│    ces 30 derniers jours │\n"
        timeline += "│                          │\n"

    total_sessions = len(checkin_dates)

    # Stats séparées gym/cardio
    if cardio_count > 0:
        stats_line = f"│  🏋️ {gym_count:>2}  │  🏃 {cardio_count:>2}  │  Total: {total_sessions:<2} │"
    else:
        stats_line = f"│  Sessions: {total_sessions:<14} │"

    embed = discord.Embed(color=EMBED_COLOR)

    embed.description = f"""▸ **CALENDRIER**

**{user_name.upper()}** — {user_activity}

```
╭──────────────────────────╮
│    30 DERNIERS JOURS     │
├──────────────────────────┤
│                          │
{timeline}│                          │
{stats_line}
╰──────────────────────────╯
```"""

    embed.set_footer(text="◆ Challenge Bot")

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="mystats", description="Tes statistiques complètes (all-time)")
async def mystats_cmd(interaction: discord.Interaction):
    user_id = interaction.user.id
    user_name = interaction.user.display_name

    profile = get_or_create_profile(user_id, user_name)
    user_activity = profile['activity']
    weekly_goal = profile['weekly_goal']

    conn = get_db()
    c = conn.cursor()

    # Tous les check-ins
    c.execute('''
        SELECT timestamp, session_type, week_number, year
        FROM checkins WHERE user_id = %s
        ORDER BY timestamp ASC
    ''', (user_id,))
    all_checkins = c.fetchall()

    # Défis actifs
    active_challenges = get_user_active_challenges(user_id)

    # Défis terminés (dans l'historique)
    c.execute('''
        SELECT COUNT(*) as count FROM history
        WHERE winner_id = %s OR loser_id = %s
    ''', (user_id, user_id))
    total_challenges_done = c.fetchone()['count']

    c.execute('''
        SELECT COUNT(*) as count FROM history
        WHERE winner_id = %s
    ''', (user_id,))
    challenges_won = c.fetchone()['count']

    conn.close()

    total_sessions = len(all_checkins)

    if total_sessions == 0:
        embed = discord.Embed(color=EMBED_COLOR)
        embed.description = f"""▸ **MES STATISTIQUES**

**{user_name.upper()}** — {user_activity}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Aucune session enregistrée.
Commence avec `/checkin` !"""
        embed.set_footer(text="◆ Challenge Bot")
        await interaction.response.send_message(embed=embed)
        return

    # Comptage par type
    gym_count = sum(1 for ci in all_checkins if (ci.get('session_type') or 'gym') == 'gym')
    cardio_count = sum(1 for ci in all_checkins if (ci.get('session_type') or 'gym') == 'cardio')

    # Premier et dernier check-in
    first_ts = datetime.datetime.fromisoformat(all_checkins[0]['timestamp'])
    last_ts = datetime.datetime.fromisoformat(all_checkins[-1]['timestamp'])
    now = datetime.datetime.now(PARIS_TZ)

    if first_ts.tzinfo is None:
        first_ts = first_ts.replace(tzinfo=PARIS_TZ)
    if last_ts.tzinfo is None:
        last_ts = last_ts.replace(tzinfo=PARIS_TZ)

    # Durée depuis le premier check-in
    delta = now - first_ts
    total_days = delta.days
    if total_days >= 365:
        years = total_days // 365
        remaining_days = total_days % 365
        months = remaining_days // 30
        if years > 0 and months > 0:
            since_text = f"{years}a {months}m"
        else:
            since_text = f"{years}a"
    elif total_days >= 30:
        months = total_days // 30
        days_r = total_days % 30
        since_text = f"{months}m {days_r}j"
    else:
        since_text = f"{total_days}j"

    # Semaines avec au moins un check-in
    weeks_set = set()
    for ci in all_checkins:
        weeks_set.add((ci['year'], ci['week_number']))
    total_weeks_active = len(weeks_set)

    # Moyenne par semaine (basée sur les semaines écoulées depuis le premier check-in)
    total_calendar_weeks = max(1, (total_days // 7) + 1)
    avg_per_week = total_sessions / total_calendar_weeks

    # Semaines avec objectif atteint (streak tracking)
    week_counts = {}
    for ci in all_checkins:
        key = (ci['year'], ci['week_number'])
        week_counts[key] = week_counts.get(key, 0) + 1

    # Trier les semaines chronologiquement
    sorted_weeks = sorted(week_counts.keys())

    # Streak actuelle et meilleure streak (semaines consécutives avec objectif atteint)
    current_streak = 0
    best_streak = 0
    temp_streak = 0
    weeks_validated = 0

    current_week_key = get_week_info()
    current_week_key = (current_week_key[1], current_week_key[0])  # (year, week)

    for wk in sorted_weeks:
        if week_counts[wk] >= weekly_goal:
            temp_streak += 1
            weeks_validated += 1
            best_streak = max(best_streak, temp_streak)
        else:
            temp_streak = 0

    # La streak actuelle = la dernière streak qui touche la semaine courante ou précédente
    current_streak = 0
    for wk in reversed(sorted_weeks):
        if wk == current_week_key:
            week_number_now, year_now = get_week_info()
            current_count = get_checkins_for_user_week(user_id, week_number_now, year_now, count_gym_only=False)
            if current_count >= weekly_goal:
                current_streak += 1
            else:
                break
        elif week_counts[wk] >= weekly_goal:
            current_streak += 1
        else:
            break

    # Taux de réussite
    success_rate = (weeks_validated / total_calendar_weeks * 100) if total_calendar_weeks > 0 else 0

    # Meilleure semaine (plus de sessions)
    best_week_count = max(week_counts.values()) if week_counts else 0

    # Jour préféré
    day_counts = [0] * 7
    for ci in all_checkins:
        ts = datetime.datetime.fromisoformat(ci['timestamp'])
        day_counts[ts.weekday()] += 1
    day_names = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    fav_day_idx = day_counts.index(max(day_counts))
    fav_day = day_names[fav_day_idx]
    fav_day_count = day_counts[fav_day_idx]

    # Sessions en cours (semaine ou cycle)
    current_progress_count, current_progress_goal = get_user_progress(user_id, profile)
    period_label = get_cycle_label(profile)

    # Date du premier check-in formatée
    first_date_str = first_ts.strftime("%d/%m/%Y")

    # Construire les barres de répartition gym/cardio
    if total_sessions > 0:
        gym_pct = gym_count / total_sessions * 100
        cardio_pct = cardio_count / total_sessions * 100
        bar_len = 16
        gym_blocks = round(gym_pct / 100 * bar_len)
        cardio_blocks = bar_len - gym_blocks
        type_bar = "■" * gym_blocks + "□" * cardio_blocks
    else:
        gym_pct = 0
        cardio_pct = 0
        type_bar = "□" * 16

    # Construire le visuel
    embed = discord.Embed(color=EMBED_COLOR)

    # Section type seulement si il y a du cardio
    type_section = ""
    if cardio_count > 0:
        type_section = f"""
◆ **RÉPARTITION**
```
🏋️ Gym    ——————— {gym_count} ({gym_pct:.0f}%)
🏃 Cardio ——————— {cardio_count} ({cardio_pct:.0f}%)
{type_bar}
```
"""

    embed.description = f"""▸ **MES STATISTIQUES**

**{user_name.upper()}** — {user_activity}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **GLOBAL**
```
{format_stat_line("SESSIONS", str(total_sessions))}
{format_stat_line("DEPUIS", f"{first_date_str} ({since_text})")}
{format_stat_line("SEMAINES", str(total_weeks_active))}
```

◆ **PERFORMANCE**
```
{format_stat_line("MOY/SEMAINE", f"{avg_per_week:.1f} sessions")}
{format_stat_line("OBJECTIF", f"{current_progress_goal}x/{(profile.get('cycle_days') or 7)}j")}
{format_stat_line("TAUX RÉUSSITE", f"{success_rate:.0f}%")}
{format_stat_line("MEILLEUR SEM", f"{best_week_count} sessions")}
```

◆ **STREAKS**
```
{format_stat_line("ACTUELLE", f"{current_streak} sem ✓" if current_streak > 0 else "—")}
{format_stat_line("MEILLEURE", f"{best_streak} sem 🔥" if best_streak > 0 else "—")}
```
{type_section}
◆ **HABITUDES**
```
{format_stat_line("JOUR PRÉFÉRÉ", f"{fav_day} ({fav_day_count}x)")}
```

◆ **{period_label}**
```
{format_stat_line("PROGRESSION", f"{current_progress_count}/{current_progress_goal}")}
{progress_bar(current_progress_count, current_progress_goal)}
```

◆ **DÉFIS**
```
{format_stat_line("ACTIFS", str(len(active_challenges)))}
{format_stat_line("TERMINÉS", str(total_challenges_done))}
{format_stat_line("GAGNÉS", str(challenges_won))}
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""

    embed.set_footer(text=f"◆ Challenge Bot • Depuis le {first_date_str}")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="help", description="Aide")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(color=EMBED_COLOR)

    embed.description = """▸ **CHALLENGE BOT**

Track ton sport. Défie tes potes. Pas d'excuses.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **PROFIL** (global)
```
/profile    — Config activité + objectif
/calendar   — Ton calendrier perso
/mystats    — Tes stats complètes
/challenges — Tous tes défis actifs
```

◆ **DÉFI** (par serveur)
```
/setup       — Créer un défi
/addplayer   — Ajouter un joueur
/removeplayer— Retirer un joueur
/setgoal     — Changer l'objectif d'un joueur
/setcycle    — Cycle perso (ex: 7x/9j)
/setworkouts — Rotation de séances
/adjustcycle — Ajuster cycle (+/- jours)
/cycleinfo   — Détails du cycle en cours
/setchannel  — Salon des check-ins
/checkin     — Session + photo
/latecheckin — Session d'HIER
/checkinfor  — Session pour qqn d'autre
/mycheckins  — Voir mes check-ins
/deletecheckin— Supprimer un doublon
/stats       — Progression du défi
/freeze      — Pause (ce serveur)
/unfreeze    — Reprendre
/freezeall   — Pause TOUS les défis
/unfreezeall — Reprendre tous
/rescue      — Revenir après élimination
/cancel      — Annuler le défi
```

◆ **RÈGLES**
```
• Semaine = Lundi → Dimanche
• Photo obligatoire
• Objectif manqué = ÉLIMINÉ
• Défi continue avec restants
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

▼ Objectif modifié = appliqué lundi."""

    embed.set_footer(text="◆ Challenge Bot")

    await interaction.response.send_message(embed=embed, ephemeral=True)


ADMIN_USER_ID = 265556280033148929

@bot.tree.command(name="reset", description="Réinitialiser les données (admin)")
async def reset_cmd(interaction: discord.Interaction):
    if interaction.user.id != ADMIN_USER_ID:
        await interaction.response.send_message("Seul l'administrateur du bot peut utiliser cette commande.", ephemeral=True)
        return

    invoker_id = interaction.user.id

    class ConfirmReset(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=30)

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            return interaction.user.id == invoker_id

        @discord.ui.button(label="Confirmer", style=discord.ButtonStyle.danger)
        async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
            conn = get_db()
            c = conn.cursor()
            c.execute('DELETE FROM checkins')
            c.execute('DELETE FROM history')
            c.execute('DELETE FROM challenge_participants')
            c.execute('DELETE FROM challenge')
            c.execute('DELETE FROM profiles')
            conn.commit()
            conn.close()

            embed = discord.Embed(color=EMBED_COLOR)
            embed.description = """▸ **RESET EFFECTUÉ**

Toutes les données ont été supprimées."""

            await interaction.response.edit_message(embed=embed, view=None)
            self.stop()

        @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
        async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.edit_message(content="Annulé.", embed=None, view=None)
            self.stop()

    embed = discord.Embed(color=EMBED_COLOR)
    embed.description = """▸ **ATTENTION**

Cette action va supprimer **TOUTES** les données :
• Défis
• Check-ins
• Historique

**Irréversible.**"""

    await interaction.response.send_message(embed=embed, view=ConfirmReset(), ephemeral=True)


@bot.tree.command(name="migrate", description="Migrer les anciens défis (admin)")
async def migrate_cmd(interaction: discord.Interaction):
    """Migre les anciens défis sans guild_id vers le nouveau format"""
    if not interaction.guild:
        await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
        return

    guild_id = interaction.guild.id

    conn = get_db()
    c = conn.cursor()

    # Trouver les défis actifs sans guild_id sur ce serveur (via channel_id)
    # On récupère les channels du serveur actuel
    guild_channel_ids = [ch.id for ch in interaction.guild.channels]

    # Chercher les défis sans guild_id dont le channel_id est dans ce serveur
    c.execute('SELECT * FROM challenge WHERE guild_id IS NULL AND is_active = 1')
    orphan_challenges = c.fetchall()

    migrated = 0
    for challenge in orphan_challenges:
        if challenge['channel_id'] in guild_channel_ids:
            # Ce défi appartient à ce serveur
            c.execute('UPDATE challenge SET guild_id = %s, checkin_channel_id = %s WHERE id = %s',
                     (guild_id, challenge['channel_id'], challenge['id']))
            migrated += 1

            # Créer les profils pour les participants s'ils n'existent pas
            c.execute('''
                INSERT INTO profiles (user_id, user_name, activity, weekly_goal)
                VALUES (%s, %s, 'Sport', %s)
                ON CONFLICT (user_id) DO NOTHING
            ''', (challenge['user1_id'], challenge['user1_name'], challenge.get('user1_goal', 4) or 4))

            c.execute('''
                INSERT INTO profiles (user_id, user_name, activity, weekly_goal)
                VALUES (%s, %s, 'Sport', %s)
                ON CONFLICT (user_id) DO NOTHING
            ''', (challenge['user2_id'], challenge['user2_name'], challenge.get('user2_goal', 4) or 4))

    conn.commit()
    conn.close()

    if migrated > 0:
        embed = discord.Embed(color=EMBED_COLOR)
        embed.description = f"""▸ **MIGRATION EFFECTUÉE**

**{migrated}** défi(s) migré(s) vers ce serveur.

Les profils ont été créés avec les objectifs existants.
Utilise `/stats` pour vérifier."""
        embed.set_footer(text="◆ Challenge Bot")
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.response.send_message("Aucun défi à migrer trouvé.", ephemeral=True)


@bot.tree.command(name="test", description="Vérifier l'état du bot")
async def test_cmd(interaction: discord.Interaction):
    guild_id = interaction.guild.id if interaction.guild else None
    challenge = get_active_challenge_for_guild(guild_id) if guild_id else None

    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) as count FROM checkins')
    total_checkins = c.fetchone()['count']
    c.execute('SELECT COUNT(*) as count FROM challenge')
    total_challenges = c.fetchone()['count']
    c.execute('SELECT COUNT(*) as count FROM challenge WHERE is_active = 1')
    active_challenges = c.fetchone()['count']
    c.execute('SELECT COUNT(*) as count FROM profiles')
    total_profiles = c.fetchone()['count']
    conn.close()

    embed = discord.Embed(color=EMBED_COLOR)

    embed.description = f"""▸ **STATUS**

Bot opérationnel

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **CE SERVEUR**
```
{format_stat_line("DÉFI ACTIF", "Oui" if challenge else "Non")}
```

◆ **GLOBAL**
```
{format_stat_line("DÉFIS ACTIFS", str(active_challenges))}
{format_stat_line("TOTAL DÉFIS", str(total_challenges))}
{format_stat_line("PROFILS", str(total_profiles))}
{format_stat_line("CHECK-INS", str(total_checkins))}
```

◆ **BOT**
```
{format_stat_line("PING", f"{round(bot.latency * 1000)}ms")}
{format_stat_line("SERVEURS", str(len(bot.guilds)))}
```"""

    embed.set_footer(text="◆ Challenge Bot")

    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="freeze", description="Mettre en pause sur ce serveur")
@app_commands.describe(raison="Raison du freeze (optionnel)")
async def freeze_cmd(interaction: discord.Interaction, raison: str = "Non spécifiée"):
    if not interaction.guild:
        await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
        return

    guild_id = interaction.guild.id
    challenge = get_active_challenge_for_guild(guild_id)

    if not challenge:
        await interaction.response.send_message("Pas de défi actif sur ce serveur.", ephemeral=True)
        return

    user_id = interaction.user.id
    participant = get_participant(challenge['id'], user_id)

    if not participant:
        await interaction.response.send_message("Tu ne participes pas.", ephemeral=True)
        return

    if participant.get('is_frozen', 0):
        await interaction.response.send_message("Tu es déjà en freeze.", ephemeral=True)
        return

    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE challenge_participants SET is_frozen = 1 WHERE challenge_id = %s AND user_id = %s',
              (challenge['id'], user_id))
    conn.commit()
    conn.close()

    embed = discord.Embed(color=EMBED_COLOR)
    embed.description = f"""▸ **FREEZE ACTIVÉ**

**{participant['user_name']}** est en pause sur ce serveur.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **RAISON**
```
{raison[:50]}
```

◆ **EFFET**
```
Objectif non requis cette semaine
Pas de pénalité si non atteint
```

▼ Utilise `/unfreeze` pour reprendre."""

    embed.set_footer(text="◆ Challenge Bot")

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="unfreeze", description="Reprendre le défi sur ce serveur")
async def unfreeze_cmd(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
        return

    guild_id = interaction.guild.id
    challenge = get_active_challenge_for_guild(guild_id)

    if not challenge:
        await interaction.response.send_message("Pas de défi actif sur ce serveur.", ephemeral=True)
        return

    user_id = interaction.user.id
    participant = get_participant(challenge['id'], user_id)

    if not participant:
        await interaction.response.send_message("Tu ne participes pas.", ephemeral=True)
        return

    if not participant.get('is_frozen', 0):
        await interaction.response.send_message("Tu n'es pas en freeze.", ephemeral=True)
        return

    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE challenge_participants SET is_frozen = 0 WHERE challenge_id = %s AND user_id = %s',
              (challenge['id'], user_id))
    conn.commit()
    conn.close()

    embed = discord.Embed(color=EMBED_COLOR)
    embed.description = f"""▸ **FREEZE DÉSACTIVÉ**

**{participant['user_name']}** reprend le défi !"""
    embed.set_footer(text="◆ Challenge Bot")

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="freezeall", description="Mettre en pause TOUS tes défis")
@app_commands.describe(raison="Raison du freeze (optionnel)")
async def freezeall_cmd(interaction: discord.Interaction, raison: str = "Non spécifiée"):
    user_id = interaction.user.id
    user_name = interaction.user.display_name

    challenges = get_user_active_challenges(user_id)

    if not challenges:
        await interaction.response.send_message("Tu n'as pas de défi actif.", ephemeral=True)
        return

    conn = get_db()
    c = conn.cursor()

    frozen_count = 0
    for challenge in challenges:
        participant = get_participant(challenge['id'], user_id)
        if participant and not participant.get('is_frozen', 0):
            c.execute('UPDATE challenge_participants SET is_frozen = 1 WHERE challenge_id = %s AND user_id = %s',
                      (challenge['id'], user_id))
            frozen_count += 1

    conn.commit()
    conn.close()

    embed = discord.Embed(color=EMBED_COLOR)
    embed.description = f"""▸ **FREEZE GLOBAL ACTIVÉ**

**{user_name}** est en pause sur **{frozen_count}** défi(s).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **RAISON**
```
{raison[:50]}
```

◆ **EFFET**
```
Objectif non requis cette semaine
Sur tous tes défis actifs
```

▼ Utilise `/unfreezeall` pour reprendre."""

    embed.set_footer(text="◆ Challenge Bot")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="unfreezeall", description="Reprendre TOUS tes défis")
async def unfreezeall_cmd(interaction: discord.Interaction):
    user_id = interaction.user.id
    user_name = interaction.user.display_name

    challenges = get_user_active_challenges(user_id)

    if not challenges:
        await interaction.response.send_message("Tu n'as pas de défi actif.", ephemeral=True)
        return

    conn = get_db()
    c = conn.cursor()

    unfrozen_count = 0
    for challenge in challenges:
        participant = get_participant(challenge['id'], user_id)
        if participant and participant.get('is_frozen', 0):
            c.execute('UPDATE challenge_participants SET is_frozen = 0 WHERE challenge_id = %s AND user_id = %s',
                      (challenge['id'], user_id))
            unfrozen_count += 1

    conn.commit()
    conn.close()

    embed = discord.Embed(color=EMBED_COLOR)
    embed.description = f"""▸ **FREEZE GLOBAL DÉSACTIVÉ**

**{user_name}** reprend **{unfrozen_count}** défi(s).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

L'objectif hebdomadaire est de nouveau requis
sur tous tes défis.

Bonne reprise !"""

    embed.set_footer(text="◆ Challenge Bot")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="rescue", description="Revenir dans le défi après un oubli de check-in")
@app_commands.describe(photo="Photo de ta session manquée")
async def rescue_cmd(interaction: discord.Interaction, photo: discord.Attachment):
    """Permet de revenir dans un défi après avoir été éliminé pour oubli de check-in"""
    if not interaction.guild:
        await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
        return

    guild_id = interaction.guild.id
    user_id = interaction.user.id
    user_name = interaction.user.display_name

    # Vérifier que c'est une image
    if not photo.content_type or not photo.content_type.startswith('image/'):
        await interaction.response.send_message("Image requise.", ephemeral=True)
        return

    conn = get_db()
    c = conn.cursor()

    # Chercher dans l'historique si cet utilisateur a été éliminé récemment sur ce serveur
    c.execute('''
        SELECT h.*, c.id as challenge_id, c.is_active
        FROM history h
        JOIN challenge c ON h.challenge_id = c.id
        WHERE h.guild_id = %s AND h.loser_id = %s
        ORDER BY h.id DESC LIMIT 1
    ''', (guild_id, user_id))
    history_row = c.fetchone()

    if not history_row:
        conn.close()
        await interaction.response.send_message("Tu n'as pas été éliminé récemment sur ce serveur.", ephemeral=True)
        return

    # Vérifier que l'élimination n'est pas trop ancienne (max 24h)
    end_date = datetime.datetime.fromisoformat(history_row['end_date'])
    now = datetime.datetime.now(PARIS_TZ)
    if end_date.tzinfo is None:
        end_date = end_date.replace(tzinfo=PARIS_TZ)
    hours_since_end = (now - end_date).total_seconds() / 3600

    if hours_since_end > 24:
        conn.close()
        await interaction.response.send_message(
            f"Trop tard ! Tu as été éliminé il y a {int(hours_since_end)}h. Limite: 24h.",
            ephemeral=True
        )
        return

    challenge_id = history_row['challenge_id']
    challenge_active = history_row['is_active']
    gage = history_row['loser_gage']

    # Vérifier si le défi est toujours actif (avec d'autres participants)
    if not challenge_active:
        # Le défi n'est plus actif, on ne peut pas rescue
        conn.close()
        await interaction.response.send_message(
            "Le défi est complètement terminé (plus assez de participants). Impossible de rescue.",
            ephemeral=True
        )
        return

    # La semaine de l'échec = semaine de end_date (le check hebdo tourne dimanche soir)
    iso = end_date.isocalendar()
    week_number, year = iso[1], iso[0]

    # Récupérer le profil pour l'objectif
    profile = get_profile(user_id)
    current_count, goal = get_user_progress(user_id, profile)

    # Avec le rescue, le count sera +1
    new_count = current_count + 1

    if new_count >= goal:
        # Rescue réussi ! Ajouter le check-in et réintégrer le participant
        rescue_timestamp = datetime.datetime.now().isoformat()

        c.execute('''
            INSERT INTO checkins (user_id, timestamp, week_number, year, photo_url, note, session_type)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        ''', (user_id, rescue_timestamp, week_number, year, photo.url, "[RESCUE]", "gym"))

        # Ré-ajouter le participant au défi
        c.execute('''
            INSERT INTO challenge_participants (challenge_id, user_id, user_name, gage, is_frozen, streak)
            VALUES (%s, %s, %s, %s, 0, 0)
        ''', (challenge_id, user_id, user_name, gage))

        # Supprimer l'entrée de l'historique
        c.execute('DELETE FROM history WHERE id = %s', (history_row['id'],))

        conn.commit()
        conn.close()

        # Récupérer les autres participants pour afficher
        participants = get_challenge_participants(challenge_id)

        embed = discord.Embed(color=EMBED_COLOR)

        participants_text = ""
        for p in participants:
            p_count, p_goal = get_user_progress(p['user_id'])
            participants_text += f"{p['user_name'][:12]:12} ——— {p_count}/{p_goal} ✓\n"

        embed.description = f"""▸ **RESCUE RÉUSSI !**

**{user_name}** revient dans le défi !

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **PARTICIPANTS**
```
{participants_text}```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

▼ **Le défi continue !**
Pas de gage cette fois. 😅"""

        embed.set_image(url=photo.url)
        embed.set_footer(text="◆ Challenge Bot • Rescue")

        # Ping tous les participants
        ping_ids = [p['user_id'] for p in participants]
        ping_content = " ".join([f"<@{pid}>" for pid in ping_ids])

        await interaction.response.send_message(content=ping_content, embed=embed)

    else:
        conn.close()

        embed = discord.Embed(color=EMBED_COLOR)
        embed.description = f"""▸ **RESCUE IMPOSSIBLE**

Même avec ce check-in, l'objectif n'est pas atteint.

```
Score avec rescue: {new_count}/{goal}
Manquant: {goal - new_count}
```

Tu restes éliminé du défi."""

        embed.set_footer(text="◆ Challenge Bot")

        await interaction.response.send_message(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════
#                       SCHEDULED TASKS
# ══════════════════════════════════════════════════════════════

@tasks.loop(minutes=1)
async def check_weekly_goals():
    """Vérifie les objectifs à minuit pile heure française (fin du dimanche)"""
    now = datetime.datetime.now(PARIS_TZ)

    # Lundi 00h00 heure française = minuit pile après dimanche
    if now.weekday() != 0 or now.hour != 0 or now.minute != 0:
        return

    # Appliquer les pending_goals (changements d'objectif programmés)
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        UPDATE profiles
        SET weekly_goal = pending_goal, pending_goal = NULL
        WHERE pending_goal IS NOT NULL
    ''')
    conn.commit()
    conn.close()

    # Récupérer TOUS les défis actifs
    challenges = get_all_active_challenges()
    if not challenges:
        return

    # À minuit lundi, on vérifie la semaine qui vient de se terminer
    yesterday = now - datetime.timedelta(days=1)
    iso = yesterday.isocalendar()
    week_number, year = iso[1], iso[0]

    for challenge in challenges:
        try:
            conn = get_db()
            c = conn.cursor()

            # Vérifier si c'est la première semaine du défi
            start_week = challenge.get('week_number', 0)
            if start_week == week_number:
                start_date_str = challenge.get('start_date')
                if start_date_str:
                    start_date = datetime.datetime.fromisoformat(start_date_str)
                    if start_date.weekday() != 0:
                        conn.close()
                        continue
                else:
                    conn.close()
                    continue

            # Récupérer tous les participants
            participants = get_challenge_participants(challenge['id'])
            if not participants:
                conn.close()
                continue

            channel = bot.get_channel(challenge['channel_id'])
            if not channel:
                conn.close()
                continue

            total_weeks = challenge.get('total_weeks', 0)
            challenge_week = get_challenge_week_number(challenge['start_date'])

            # Évaluer chaque participant
            failed_participants = []
            success_participants = []

            for p in participants:
                profile = get_profile(p['user_id'])
                frozen = p.get('is_frozen', 0)

                # Les utilisateurs avec cycle custom sont gérés par check_custom_cycles
                if is_custom_cycle(profile):
                    count, goal = get_user_progress(p['user_id'], profile)
                    success_participants.append({
                        'user_id': p['user_id'],
                        'user_name': p['user_name'],
                        'count': count,
                        'goal': goal,
                        'frozen': False,
                        'custom_cycle': True
                    })
                    continue

                goal = profile['weekly_goal'] if profile else 4
                count = get_checkins_for_user_week(p['user_id'], week_number, year, count_gym_only=False)

                if count < goal and not frozen:
                    failed_participants.append({
                        'user_id': p['user_id'],
                        'user_name': p['user_name'],
                        'gage': p['gage'],
                        'count': count,
                        'goal': goal
                    })
                else:
                    success_participants.append({
                        'user_id': p['user_id'],
                        'user_name': p['user_name'],
                        'count': count,
                        'goal': goal,
                        'frozen': frozen
                    })
                    new_streak = p.get('streak', 0) + 1
                    c.execute('UPDATE challenge_participants SET streak = %s WHERE id = %s', (new_streak, p['id']))

            # Si des participants ont échoué
            if failed_participants:
                for fp in failed_participants:
                    c.execute('DELETE FROM challenge_participants WHERE challenge_id = %s AND user_id = %s',
                              (challenge['id'], fp['user_id']))

                    c.execute('''
                        INSERT INTO history (challenge_id, guild_id, winner_id, winner_name, loser_id, loser_name, loser_gage, end_date, reason, total_weeks)
                        VALUES (%s, %s, NULL, NULL, %s, %s, %s, %s, %s, %s)
                    ''', (challenge['id'], challenge['guild_id'], fp['user_id'], fp['user_name'], fp['gage'], now.isoformat(), 'Objectif non atteint', total_weeks))

                embed = discord.Embed(color=EMBED_COLOR)

                failed_text = ""
                for fp in failed_participants:
                    failed_text += f"""
◆ **{fp['user_name'].upper()}** — ÉCHEC
```
{format_stat_line("SCORE", f"{fp['count']}/{fp['goal']}")}
{format_stat_line("GAGE", fp['gage'][:20])}
```
"""

                success_text = ""
                for sp in success_participants:
                    freeze_mark = " (freeze)" if sp.get('frozen') else " ✓"
                    success_text += f"""
◆ **{sp['user_name'].upper()}**{freeze_mark}
```
{format_stat_line("SCORE", f"{sp['count']}/{sp['goal']}")}
```
"""

                remaining = len(success_participants)

                if remaining < 2:
                    c.execute('UPDATE challenge SET is_active = 0 WHERE id = %s', (challenge['id'],))

                    embed.description = f"""▸ **GAME OVER**

Échec(s) cette semaine :
{failed_text}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{"Participant(s) restant(s) :" + success_text if success_text else ""}

▼ **Le défi est terminé** (moins de 2 participants)."""
                else:
                    embed.description = f"""▸ **ÉLIMINATION**

Échec(s) cette semaine :
{failed_text}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Toujours en course ({remaining} participants) :
{success_text}

▼ **Le défi continue.**"""

                    c.execute('UPDATE challenge SET total_weeks = %s, week_number = %s WHERE id = %s',
                              (total_weeks + 1, week_number + 1, challenge['id']))

                embed.set_footer(text=f"◆ Challenge Bot • Semaine {challenge_week}")

                all_ids = [fp['user_id'] for fp in failed_participants] + [sp['user_id'] for sp in success_participants]
                ping_content = " ".join([f"<@{uid}>" for uid in all_ids])

                conn.commit()
                await channel.send(content=ping_content, embed=embed)

            else:
                c.execute('UPDATE challenge SET total_weeks = %s, week_number = %s WHERE id = %s',
                          (total_weeks + 1, week_number + 1, challenge['id']))

                success_text = ""
                for sp in success_participants:
                    freeze_mark = " (freeze)" if sp.get('frozen') else " ✓"
                    success_text += f"""
◆ **{sp['user_name'].upper()}**{freeze_mark}
```
{format_stat_line("SCORE", f"{sp['count']}/{sp['goal']}")}
```
"""

                embed = discord.Embed(color=EMBED_COLOR)
                embed.description = f"""▸ **SEMAINE {challenge_week} VALIDÉE**

Tout le monde a réussi !

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{success_text}
▼ **Le défi continue.**"""

                embed.set_footer(text=f"◆ Challenge Bot • Semaine {challenge_week + 1}")

                conn.commit()
                await channel.send(embed=embed)

        except Exception as e:
            print(f"Erreur check_weekly_goals pour challenge {challenge.get('id')}: {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass


@tasks.loop(hours=12)
async def send_reminders():
    """Rappels vendredi/samedi pour tous les défis actifs"""
    now = datetime.datetime.now(PARIS_TZ)

    if now.weekday() not in [4, 5]:
        return

    challenges = get_all_active_challenges()
    if not challenges:
        return

    week_number, year = get_week_info()

    # Calculer les heures restantes
    days_until_monday = (7 - now.weekday()) % 7
    if days_until_monday == 0:
        days_until_monday = 7
    next_monday = now.replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=days_until_monday)
    time_remaining = next_monday - now
    hours_remaining = int(time_remaining.total_seconds() // 3600)

    for challenge in challenges:
        try:
            # Vérifier si c'est la première semaine et pas créé un lundi
            start_week = challenge.get('week_number', 0)
            if start_week == week_number:
                start_date_str = challenge.get('start_date')
                if start_date_str:
                    start_date = datetime.datetime.fromisoformat(start_date_str)
                    if start_date.weekday() != 0:
                        continue
                else:
                    continue

            participants = get_challenge_participants(challenge['id'])
            if not participants:
                continue

            channel = bot.get_channel(challenge['channel_id'])
            if not channel:
                continue

            # Vérifier chaque participant
            reminder_text = "▸ **RAPPEL**\n\n"
            ping_content = ""
            has_reminders = False

            for p in participants:
                profile = get_profile(p['user_id'])
                count, goal = get_user_progress(p['user_id'], profile)
                frozen = p.get('is_frozen', 0)

                remaining = max(0, goal - count) if not frozen else 0

                if remaining > 0:
                    reminder_text += f"<@{p['user_id']}> — **{remaining}** session(s) restante(s)\n"
                    ping_content += f"<@{p['user_id']}> "
                    has_reminders = True

            if has_reminders:
                reminder_text += f"\n**{hours_remaining}** heure(s) restante(s)."

                embed = discord.Embed(color=EMBED_COLOR)
                embed.description = reminder_text
                embed.set_footer(text="◆ Challenge Bot")

                await channel.send(content=ping_content.strip(), embed=embed)

        except Exception as e:
            print(f"Erreur send_reminders pour challenge {challenge.get('id')}: {e}")


@tasks.loop(minutes=1)
async def check_custom_cycles():
    """Vérifie les cycles personnalisés à minuit chaque jour"""
    now = datetime.datetime.now(PARIS_TZ)

    if now.hour != 0 or now.minute != 0:
        return

    conn = get_db()
    c = conn.cursor()

    # Trouver tous les profils avec cycle custom dont le cycle est terminé
    c.execute('''
        SELECT * FROM profiles
        WHERE cycle_days IS NOT NULL AND cycle_days != 7
        AND cycle_start_date IS NOT NULL
    ''')
    cycle_profiles = c.fetchall()
    conn.close()

    for profile in cycle_profiles:
        try:
            cycle_start = datetime.datetime.fromisoformat(profile['cycle_start_date'])
            if cycle_start.tzinfo is None:
                cycle_start = cycle_start.replace(tzinfo=PARIS_TZ)

            cycle_end = cycle_start + datetime.timedelta(days=profile['cycle_days'])

            if now < cycle_end:
                continue

            user_id = int(profile['user_id'])
            cycle_goal = profile.get('cycle_goal') or profile['weekly_goal']
            count = get_checkins_for_user_cycle(user_id, profile['cycle_start_date'], profile['cycle_days'])

            conn = get_db()
            c = conn.cursor()

            if count >= cycle_goal:
                c.execute('''
                    UPDATE profiles SET cycle_start_date = %s WHERE user_id = %s
                ''', (now.strftime('%Y-%m-%dT00:00:00'), user_id))
                conn.commit()
                conn.close()
                print(f"Cycle réussi pour {profile['user_name']}: {count}/{cycle_goal}, nouveau cycle démarré")
            else:
                challenges = get_user_active_challenges(user_id)
                for challenge in challenges:
                    participant = get_participant(challenge['id'], user_id)
                    if not participant:
                        continue

                    frozen = participant.get('is_frozen', 0)
                    if frozen:
                        continue

                    c.execute('DELETE FROM challenge_participants WHERE challenge_id = %s AND user_id = %s',
                              (challenge['id'], user_id))

                    total_weeks = challenge.get('total_weeks', 0)
                    c.execute('''
                        INSERT INTO history (challenge_id, guild_id, winner_id, winner_name, loser_id, loser_name, loser_gage, end_date, reason, total_weeks)
                        VALUES (%s, %s, NULL, NULL, %s, %s, %s, %s, %s, %s)
                    ''', (challenge['id'], challenge['guild_id'], user_id, profile['user_name'],
                          participant['gage'], now.isoformat(), f'Cycle {profile["cycle_days"]}j non atteint ({count}/{cycle_goal})', total_weeks))

                    channel = bot.get_channel(challenge['channel_id'])
                    if channel:
                        remaining_participants = get_challenge_participants(challenge['id'])

                        embed = discord.Embed(color=EMBED_COLOR)
                        embed.description = f"""▸ **CYCLE ÉCHOUÉ**

**{profile['user_name']}** n'a pas atteint son objectif.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

```
{format_stat_line("CYCLE", f"{profile['cycle_days']} jours")}
{format_stat_line("SCORE", f"{count}/{cycle_goal}")}
{format_stat_line("GAGE", participant['gage'][:20])}
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""

                        if len(remaining_participants) < 2:
                            c.execute('UPDATE challenge SET is_active = 0 WHERE id = %s', (challenge['id'],))
                            embed.description += "\n▼ **Le défi est terminé** (moins de 2 participants)."
                        else:
                            embed.description += f"\n▼ `/rescue` disponible pendant 24h."

                        embed.set_footer(text="◆ Challenge Bot")
                        await channel.send(f"<@{user_id}>", embed=embed)

                c.execute('''
                    UPDATE profiles SET cycle_start_date = %s WHERE user_id = %s
                ''', (now.strftime('%Y-%m-%dT00:00:00'), user_id))
                conn.commit()
                conn.close()

        except Exception as e:
            print(f"Erreur check_custom_cycles pour {profile.get('user_name')}: {e}")
            try:
                conn.close()
            except Exception:
                pass


@check_weekly_goals.before_loop
async def before_check():
    await bot.wait_until_ready()

@send_reminders.before_loop
async def before_reminders():
    await bot.wait_until_ready()

@check_custom_cycles.before_loop
async def before_cycles():
    await bot.wait_until_ready()

# ══════════════════════════════════════════════════════════════
#                       START
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import time
    from dotenv import load_dotenv
    load_dotenv()

    TOKEN = os.getenv('DISCORD_TOKEN')
    if not TOKEN:
        print("Token manquant. Crée un fichier .env avec DISCORD_TOKEN=xxx")
        exit(1)

    max_retries = 5
    retry_delay = 5

    for attempt in range(max_retries):
        try:
            bot.run(TOKEN)
            break
        except discord.errors.HTTPException as e:
            if "429" in str(e) or "rate limit" in str(e).lower():
                wait_time = retry_delay * (2 ** attempt)
                print(f"Rate limited. Attente de {wait_time}s avant retry...")
                time.sleep(wait_time)
            else:
                raise
        except Exception as e:
            print(f"Erreur: {e}")
            if attempt < max_retries - 1:
                wait_time = retry_delay * (2 ** attempt)
                print(f"Retry dans {wait_time}s...")
                time.sleep(wait_time)
            else:
                raise

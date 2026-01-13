"""
Challenge Bot - Track your commitments. No excuses.
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import datetime
from zoneinfo import ZoneInfo
import random
import os
import calendar
from typing import Optional
import psycopg2
from psycopg2.extras import RealDictCursor

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
    now = datetime.datetime.now()
    days = (6 - now.weekday())
    return days if days >= 0 else 0

def get_week_info():
    now = datetime.datetime.now()
    iso = now.isocalendar()
    return iso[1], iso[0]

def get_challenge_week_number(challenge_start_date: str) -> int:
    """Retourne le numéro de semaine du défi (1, 2, 3...) depuis le début"""
    start = datetime.datetime.fromisoformat(challenge_start_date)
    now = datetime.datetime.now()
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

    # Table des défis (par serveur)
    c.execute('''
        CREATE TABLE IF NOT EXISTS challenge (
            id SERIAL PRIMARY KEY,
            guild_id BIGINT NOT NULL,
            user1_id BIGINT NOT NULL,
            user1_name TEXT NOT NULL,
            user1_gage TEXT NOT NULL,
            user2_id BIGINT NOT NULL,
            user2_name TEXT NOT NULL,
            user2_gage TEXT NOT NULL,
            channel_id BIGINT NOT NULL,
            checkin_channel_id BIGINT,
            start_date TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            week_number INTEGER NOT NULL,
            streak_user1 INTEGER DEFAULT 0,
            streak_user2 INTEGER DEFAULT 0,
            total_weeks INTEGER DEFAULT 0,
            freeze_user1 INTEGER DEFAULT 0,
            freeze_user2 INTEGER DEFAULT 0
        )
    ''')

    # Migration: ajouter les nouvelles colonnes si elles n'existent pas
    c.execute('''
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='challenge' AND column_name='guild_id') THEN
                ALTER TABLE challenge ADD COLUMN guild_id BIGINT;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='challenge' AND column_name='checkin_channel_id') THEN
                ALTER TABLE challenge ADD COLUMN checkin_channel_id BIGINT;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='challenge' AND column_name='freeze_user1') THEN
                ALTER TABLE challenge ADD COLUMN freeze_user1 INTEGER DEFAULT 0;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='challenge' AND column_name='freeze_user2') THEN
                ALTER TABLE challenge ADD COLUMN freeze_user2 INTEGER DEFAULT 0;
            END IF;
        END $$;
    ''')

    # Migration: rendre les anciennes colonnes nullable (pour compatibilité)
    c.execute('''
        DO $$
        BEGIN
            -- Rendre user1_activity nullable si elle existe
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

    # Créer les index pour optimiser les requêtes
    c.execute('CREATE INDEX IF NOT EXISTS idx_challenge_guild ON challenge(guild_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_challenge_active ON challenge(is_active)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_challenge_users ON challenge(user1_id, user2_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_checkins_user ON checkins(user_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_checkins_week ON checkins(user_id, week_number, year)')

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

def get_user_active_challenges(user_id):
    """Récupère tous les défis actifs où un utilisateur participe"""
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT * FROM challenge
        WHERE is_active = 1 AND (user1_id = %s OR user2_id = %s)
    ''', (user_id, user_id))
    rows = c.fetchall()
    conn.close()
    return rows

def get_checkins_for_user_week(user_id, week_number, year):
    """Récupère le nombre de check-ins d'un utilisateur pour une semaine"""
    conn = get_db()
    c = conn.cursor()
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

# Compatibilité avec l'ancien code
def get_active_challenge():
    """DEPRECATED - Récupère un défi actif (pour compatibilité)"""
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM challenge WHERE is_active = 1 ORDER BY id DESC LIMIT 1')
    row = c.fetchone()
    conn.close()
    return row

def get_checkins_for_week(challenge_id, week_number, year):
    """Récupère les check-ins de la semaine pour les utilisateurs d'un défi"""
    # D'abord récupérer le challenge pour avoir les user_ids
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT user1_id, user2_id FROM challenge WHERE id = %s', (challenge_id,))
    challenge = c.fetchone()
    conn.close()

    if not challenge:
        return {}

    user1_count = get_checkins_for_user_week(challenge['user1_id'], week_number, year)
    user2_count = get_checkins_for_user_week(challenge['user2_id'], week_number, year)

    return {challenge['user1_id']: user1_count, challenge['user2_id']: user2_count}

def get_total_checkins(challenge_id, user_id):
    """Récupère le total de check-ins d'un utilisateur"""
    return get_total_checkins_user(user_id)

# ══════════════════════════════════════════════════════════════
#                       BOT EVENTS
# ══════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    print(f"Bot connecté: {bot.user}")
    init_db()
    try:
        synced = await bot.tree.sync()
        print(f"{len(synced)} commandes synchronisées")
    except Exception as e:
        print(f"Erreur: {e}")

    check_weekly_goals.start()
    send_reminders.start()

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
    week_number, year = get_week_info()
    week_checkins = get_checkins_for_user_week(user_id, week_number, year)
    active_challenges = get_user_active_challenges(user_id)

    # Afficher pending_goal si défini
    pending_goal = profile.get('pending_goal')
    goal_display = f"{profile['weekly_goal']}x/semaine"
    if pending_goal:
        goal_display += f" → {pending_goal}x lundi"

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
{format_stat_line("CETTE SEMAINE", f"{week_checkins}/{profile['weekly_goal']}")}
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

    week_number, year = get_week_info()
    profile = get_profile(user_id)
    user_goal = profile['weekly_goal'] if profile else 4
    user_count = get_checkins_for_user_week(user_id, week_number, year)

    challenges_text = ""
    for challenge in challenges:
        # Trouver l'adversaire
        if user_id == challenge['user1_id']:
            other_name = challenge['user2_name']
            other_id = challenge['user2_id']
            my_gage = challenge['user1_gage']
            is_frozen = challenge.get('freeze_user1', 0)
        else:
            other_name = challenge['user1_name']
            other_id = challenge['user1_id']
            my_gage = challenge['user2_gage']
            is_frozen = challenge.get('freeze_user2', 0)

        # Stats adversaire
        other_profile = get_profile(other_id)
        other_goal = other_profile['weekly_goal'] if other_profile else 4
        other_count = get_checkins_for_user_week(other_id, week_number, year)

        # Trouver le nom du serveur
        guild = bot.get_guild(challenge['guild_id'])
        guild_name = guild.name if guild else f"Serveur #{challenge['guild_id']}"

        # Status
        freeze_tag = " ❄" if is_frozen else ""
        my_status = "✓" if user_count >= user_goal or is_frozen else f"{user_count}/{user_goal}"
        other_status = f"{other_count}/{other_goal}"

        challenges_text += f"""
◆ **{guild_name}**{freeze_tag}
```
vs {other_name}
Toi: {my_status} | Lui: {other_status}
Gage: {my_gage[:20]}
```
"""

    embed = discord.Embed(color=EMBED_COLOR)
    embed.description = f"""▸ **TES DÉFIS**

**{user_name.upper()}** — {user_count}/{user_goal} cette semaine

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
        await interaction.response.send_message("Un défi est déjà en cours sur ce serveur.", ephemeral=True)
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

    # Note: on inclut user1_activity, user1_goal, user2_activity, user2_goal pour compatibilité avec l'ancien schéma
    c.execute('''
        INSERT INTO challenge
        (guild_id, user1_id, user1_name, user1_activity, user1_goal, user1_gage,
         user2_id, user2_name, user2_activity, user2_goal, user2_gage,
         channel_id, checkin_channel_id, start_date, week_number,
         streak_user1, streak_user2, total_weeks, freeze_user1, freeze_user2)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, 0, 0, 0, 0)
    ''', (guild_id, user_id, interaction.user.display_name, profile1['activity'], profile1['weekly_goal'], ton_gage,
          adversaire.id, adversaire.display_name, profile2['activity'], profile2['weekly_goal'], son_gage,
          interaction.channel_id, interaction.channel_id, start_date, week_number))

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
Objectif manqué = **GAME OVER**

💡 Check-ins partagés sur tous vos serveurs"""

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
    if user_id not in [challenge['user1_id'], challenge['user2_id']]:
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


@bot.tree.command(name="checkin", description="Enregistrer une session")
@app_commands.describe(
    photo="Photo de ta session",
    note="Note optionnelle (ex: Push day, Cardio...)"
)
async def checkin(interaction: discord.Interaction, photo: discord.Attachment, note: Optional[str] = None):
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

    # Récupérer le profil
    profile = get_or_create_profile(user_id, user_name)

    # Enregistrer le check-in (global)
    conn = get_db()
    c = conn.cursor()

    week_number, year = get_week_info()
    timestamp = datetime.datetime.now().isoformat()

    c.execute('''
        INSERT INTO checkins (user_id, timestamp, week_number, year, photo_url, note)
        VALUES (%s, %s, %s, %s, %s, %s)
    ''', (user_id, timestamp, week_number, year, photo.url, note))

    conn.commit()
    conn.close()

    # Compter les check-ins de la semaine
    user_count = get_checkins_for_user_week(user_id, week_number, year)
    user_goal = profile['weekly_goal']
    user_activity = profile['activity']
    days = get_days_remaining()

    # Statut
    if user_count >= user_goal:
        status = "✓ VALIDÉ"
        status_emoji = "★"
    else:
        status = "En cours"
        status_emoji = "▸"

    # Construire l'embed principal
    note_text = f"\n📝 *{note}*" if note else ""

    embed = discord.Embed(color=EMBED_COLOR)
    embed.description = f"""{status_emoji} **{status.upper()}**

**{user_name.upper()}**

{user_activity}
**{user_count} / {user_goal}**{note_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **CETTE SEMAINE**
```
{progress_bar(user_count, user_goal)} {user_count}/{user_goal}
```

◆ **TEMPS RESTANT**
```
{format_stat_line("JOURS", f"{days}j")}
{format_stat_line("DEADLINE", "Dimanche 23h")}
```"""

    embed.set_image(url=photo.url)
    embed.set_footer(text=f"◆ Challenge Bot • {datetime.datetime.now().strftime('%H:%M')}")

    # Compter les autres serveurs où on doit cross-poster
    current_guild_id = interaction.guild.id if interaction.guild else None
    other_challenges = [c for c in active_challenges if c['guild_id'] != current_guild_id]

    # Ajouter le feedback cross-post prévu
    if other_challenges:
        embed.description += f"\n\n📤 Cross-post vers {len(other_challenges)} serveur(s)..."

    # Répondre à l'interaction originale (on doit répondre dans les 3 secondes)
    await interaction.response.send_message(embed=embed)

    # Cross-poster sur les autres serveurs (après avoir répondu)
    cross_post_success = 0
    cross_post_fail = 0

    for challenge in other_challenges:
        # Trouver le salon de check-in
        checkin_channel_id = challenge.get('checkin_channel_id') or challenge['channel_id']
        channel = bot.get_channel(checkin_channel_id)

        if channel:
            # Trouver l'adversaire
            if user_id == challenge['user1_id']:
                other_id = challenge['user2_id']
                other_name = challenge['user2_name']
            else:
                other_id = challenge['user1_id']
                other_name = challenge['user1_name']

            # Récupérer le profil et stats de l'adversaire
            other_profile = get_profile(other_id)
            other_count = get_checkins_for_user_week(other_id, week_number, year)
            other_goal = other_profile['weekly_goal'] if other_profile else 4

            # Embed pour ce serveur avec progression des deux
            cross_embed = discord.Embed(color=EMBED_COLOR)
            cross_embed.description = f"""{status_emoji} **CHECK-IN**

**{user_name.upper()}**

{user_activity}{note_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **PROGRESSION**
```
{user_name[:10]:10} {progress_bar(user_count, user_goal)} {user_count}/{user_goal}
{other_name[:10]:10} {progress_bar(other_count, other_goal)} {other_count}/{other_goal}
```"""

            cross_embed.set_image(url=photo.url)
            cross_embed.set_footer(text=f"◆ Challenge Bot • Cross-post")

            try:
                await channel.send(content=f"<@{other_id}>", embed=cross_embed)
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
    note="Note optionnelle"
)
async def latecheckin(interaction: discord.Interaction, photo: discord.Attachment, note: Optional[str] = None):
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

    # Récupérer le profil
    profile = get_or_create_profile(user_id, user_name)

    # Enregistrer le check-in avec la date d'hier
    conn = get_db()
    c = conn.cursor()

    week_number = yesterday_iso[1]
    year = yesterday_iso[0]
    timestamp = yesterday.replace(hour=20, minute=0, second=0).isoformat()  # 20h hier

    late_note = f"[HIER] {note}" if note else "[HIER]"

    c.execute('''
        INSERT INTO checkins (user_id, timestamp, week_number, year, photo_url, note)
        VALUES (%s, %s, %s, %s, %s, %s)
    ''', (user_id, timestamp, week_number, year, photo.url, late_note))

    conn.commit()
    conn.close()

    # Compter les check-ins de la semaine
    user_count = get_checkins_for_user_week(user_id, week_number, year)
    user_goal = profile['weekly_goal']
    user_activity = profile['activity']
    days = get_days_remaining()

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

    embed = discord.Embed(color=EMBED_COLOR)
    embed.description = f"""{status_emoji} **{status.upper()}** (hier {yesterday_str})

**{user_name.upper()}**

{user_activity}
**{user_count} / {user_goal}**{note_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **CETTE SEMAINE**
```
{progress_bar(user_count, user_goal)} {user_count}/{user_goal}
```

◆ **TEMPS RESTANT**
```
{format_stat_line("JOURS", f"{days}j")}
{format_stat_line("DEADLINE", "Dimanche 23h")}
```

⏰ *Check-in enregistré pour hier*"""

    embed.set_image(url=photo.url)
    embed.set_footer(text=f"◆ Challenge Bot • Late check-in")

    # Compter les autres serveurs
    current_guild_id = interaction.guild.id if interaction.guild else None
    other_challenges = [c for c in active_challenges if c['guild_id'] != current_guild_id]

    if other_challenges:
        embed.description += f"\n\n📤 Cross-post vers {len(other_challenges)} serveur(s)..."

    await interaction.response.send_message(embed=embed)

    # Cross-poster sur les autres serveurs
    cross_post_success = 0
    cross_post_fail = 0

    for challenge in other_challenges:
        checkin_channel_id = challenge.get('checkin_channel_id') or challenge['channel_id']
        channel = bot.get_channel(checkin_channel_id)

        if channel:
            if user_id == challenge['user1_id']:
                other_id = challenge['user2_id']
                other_name = challenge['user2_name']
            else:
                other_id = challenge['user1_id']
                other_name = challenge['user1_name']

            other_profile = get_profile(other_id)
            other_count = get_checkins_for_user_week(other_id, week_number, year)
            other_goal = other_profile['weekly_goal'] if other_profile else 4

            cross_embed = discord.Embed(color=EMBED_COLOR)
            cross_embed.description = f"""{status_emoji} **CHECK-IN** (hier)

**{user_name.upper()}**

{user_activity}{note_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **PROGRESSION**
```
{user_name[:10]:10} {progress_bar(user_count, user_goal)} {user_count}/{user_goal}
{other_name[:10]:10} {progress_bar(other_count, other_goal)} {other_count}/{other_goal}
```

⏰ *Late check-in*"""

            cross_embed.set_image(url=photo.url)
            cross_embed.set_footer(text=f"◆ Challenge Bot • Cross-post")

            try:
                await channel.send(content=f"<@{other_id}>", embed=cross_embed)
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
    note="Note optionnelle"
)
async def checkinfor(interaction: discord.Interaction, membre: discord.Member, note: Optional[str] = None):
    user_id = membre.id
    user_name = membre.display_name
    by_name = interaction.user.display_name

    # Vérifier que la personne a au moins un défi actif
    active_challenges = get_user_active_challenges(user_id)

    if not active_challenges:
        await interaction.response.send_message(f"{membre.mention} n'a pas de défi actif.", ephemeral=True)
        return

    # Récupérer le profil
    profile = get_or_create_profile(user_id, user_name)

    # Enregistrer le check-in
    conn = get_db()
    c = conn.cursor()

    week_number, year = get_week_info()
    timestamp = datetime.datetime.now().isoformat()

    checkin_note = f"[par {by_name}] {note}" if note else f"[par {by_name}]"

    c.execute('''
        INSERT INTO checkins (user_id, timestamp, week_number, year, photo_url, note)
        VALUES (%s, %s, %s, %s, %s, %s)
    ''', (user_id, timestamp, week_number, year, None, checkin_note))

    conn.commit()
    conn.close()

    # Compter les check-ins de la semaine
    user_count = get_checkins_for_user_week(user_id, week_number, year)
    user_goal = profile['weekly_goal']
    user_activity = profile['activity']
    days = get_days_remaining()

    # Statut
    if user_count >= user_goal:
        status = "✓ VALIDÉ"
        status_emoji = "★"
    else:
        status = "En cours"
        status_emoji = "▸"

    note_text = f"\n📝 *{note}*" if note else ""

    embed = discord.Embed(color=EMBED_COLOR)
    embed.description = f"""{status_emoji} **{status.upper()}**

**{user_name.upper()}**

{user_activity}
**{user_count} / {user_goal}**{note_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **CETTE SEMAINE**
```
{progress_bar(user_count, user_goal)} {user_count}/{user_goal}
```

◆ **TEMPS RESTANT**
```
{format_stat_line("JOURS", f"{days}j")}
{format_stat_line("DEADLINE", "Dimanche 23h")}
```

👤 *Enregistré par {by_name}*"""

    embed.set_footer(text=f"◆ Challenge Bot • {datetime.datetime.now().strftime('%H:%M')}")

    # Compter les serveurs pour cross-post
    current_guild_id = interaction.guild.id if interaction.guild else None
    other_challenges = [c for c in active_challenges if c['guild_id'] != current_guild_id]

    if other_challenges:
        embed.description += f"\n\n📤 Cross-post vers {len(other_challenges)} serveur(s)..."

    await interaction.response.send_message(content=f"{membre.mention}", embed=embed)

    # Cross-poster sur les autres serveurs
    cross_post_success = 0
    cross_post_fail = 0

    for challenge in other_challenges:
        checkin_channel_id = challenge.get('checkin_channel_id') or challenge['channel_id']
        channel = bot.get_channel(checkin_channel_id)

        if channel:
            if user_id == challenge['user1_id']:
                other_id = challenge['user2_id']
                other_name_c = challenge['user2_name']
            else:
                other_id = challenge['user1_id']
                other_name_c = challenge['user1_name']

            other_profile = get_profile(other_id)
            other_count = get_checkins_for_user_week(other_id, week_number, year)
            other_goal = other_profile['weekly_goal'] if other_profile else 4

            cross_embed = discord.Embed(color=EMBED_COLOR)
            cross_embed.description = f"""{status_emoji} **CHECK-IN**

**{user_name.upper()}**

{user_activity}{note_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **PROGRESSION**
```
{user_name[:10]:10} {progress_bar(user_count, user_goal)} {user_count}/{user_goal}
{other_name_c[:10]:10} {progress_bar(other_count, other_goal)} {other_count}/{other_goal}
```

👤 *Par {by_name}*"""

            cross_embed.set_footer(text=f"◆ Challenge Bot • Cross-post")

            try:
                await channel.send(content=f"<@{other_id}>", embed=cross_embed)
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

    # Récupérer les profils pour les objectifs
    profile1 = get_profile(challenge['user1_id'])
    profile2 = get_profile(challenge['user2_id'])

    user1_goal = profile1['weekly_goal'] if profile1 else 4
    user2_goal = profile2['weekly_goal'] if profile2 else 4
    user1_activity = profile1['activity'] if profile1 else 'Sport'
    user2_activity = profile2['activity'] if profile2 else 'Sport'

    user1_count = get_checkins_for_user_week(challenge['user1_id'], week_number, year)
    user2_count = get_checkins_for_user_week(challenge['user2_id'], week_number, year)

    user1_total = get_total_checkins_user(challenge['user1_id'])
    user2_total = get_total_checkins_user(challenge['user2_id'])

    challenge_week = get_challenge_week_number(challenge['start_date'])
    days = get_days_remaining()

    # Vérifier si c'est une semaine "d'échauffement" (créé en cours de semaine, pas un lundi)
    warmup_week = False
    start_week = challenge.get('week_number', 0)
    if start_week == week_number:
        start_date_str = challenge.get('start_date')
        if start_date_str:
            start_date = datetime.datetime.fromisoformat(start_date_str)
            if start_date.weekday() != 0:  # Pas créé un lundi
                warmup_week = True

    # Vérifier le freeze
    user1_frozen = challenge.get('freeze_user1', 0)
    user2_frozen = challenge.get('freeze_user2', 0)

    # Déterminer le leader
    user1_pct = user1_count / user1_goal if user1_goal > 0 else 0
    user2_pct = user2_count / user2_goal if user2_goal > 0 else 0

    if warmup_week:
        status_text = "⚡ Semaine d'échauffement (non comptée)"
    elif user1_count >= user1_goal and user2_count >= user2_goal:
        status_text = "✓ Les deux ont validé"
    elif user1_pct > user2_pct:
        status_text = f"▸ {challenge['user1_name']} mène"
    elif user2_pct > user1_pct:
        status_text = f"▸ {challenge['user2_name']} mène"
    else:
        status_text = "▸ Égalité"

    # Indicateurs freeze
    user1_freeze_tag = " ❄" if user1_frozen else ""
    user2_freeze_tag = " ❄" if user2_frozen else ""

    # Calcul du temps restant
    if days == 0:
        time_status = "⚠ DERNIER JOUR"
    elif days == 1:
        time_status = f"{days} jour restant"
    else:
        time_status = f"{days} jours restants"

    embed = discord.Embed(color=EMBED_COLOR)

    embed.description = f"""▸ **SEMAINE {challenge_week}**

{status_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **{challenge['user1_name'].upper()}**{user1_freeze_tag} — {user1_activity}
```
CETTE SEMAINE ——— {user1_count}/{user1_goal}
{progress_bar(user1_count, user1_goal)} {"✓" if user1_count >= user1_goal else ""}{"FREEZE" if user1_frozen else ""}

TOTAL ——————————— {user1_total}
GAGE ———————————— {challenge['user1_gage'][:15]}
```

◆ **{challenge['user2_name'].upper()}**{user2_freeze_tag} — {user2_activity}
```
CETTE SEMAINE ——— {user2_count}/{user2_goal}
{progress_bar(user2_count, user2_goal)} {"✓" if user2_count >= user2_goal else ""}{"FREEZE" if user2_frozen else ""}

TOTAL ——————————— {user2_total}
GAGE ———————————— {challenge['user2_gage'][:15]}
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **DEADLINE**
```
{time_status}
Vérification: Dimanche minuit
```"""

    embed.set_footer(text=f"◆ Challenge Bot • Semaine {challenge_week}")

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

    if interaction.user.id not in [challenge['user1_id'], challenge['user2_id']]:
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

    # Récupérer tous les check-ins pour cet utilisateur (global)
    c.execute('''
        SELECT timestamp, note FROM checkins
        WHERE user_id = %s
        ORDER BY timestamp DESC
    ''', (user_id,))

    rows = c.fetchall()
    conn.close()

    # Extraire les dates avec check-in (30 derniers jours)
    checkin_dates = []
    for row in rows:
        ts = datetime.datetime.fromisoformat(row['timestamp'])
        ts_date = ts.date()
        if ts_date >= thirty_days_ago and ts_date <= today:
            checkin_dates.append(ts_date)

    # Trier les dates (uniques)
    checkin_dates = sorted(set(checkin_dates))

    # Noms des jours
    day_names = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]

    # Construire la timeline
    timeline = ""
    for checkin_date in checkin_dates:
        day_name = day_names[checkin_date.weekday()]

        if checkin_date == today:
            timeline += f"│  {checkin_date.day:02d} {day_name} ━━◆ aujourd'hui  │\n"
        else:
            timeline += f"│  {checkin_date.day:02d} {day_name} ━━━●             │\n"

    # Si pas de check-ins
    if not checkin_dates:
        timeline = "│                          │\n"
        timeline += "│    Aucune session        │\n"
        timeline += "│    ces 30 derniers jours │\n"
        timeline += "│                          │\n"

    total_sessions = len(checkin_dates)

    embed = discord.Embed(color=EMBED_COLOR)

    embed.description = f"""▸ **CALENDRIER**

**{user_name.upper()}** — {user_activity}

```
╭──────────────────────────╮
│    30 DERNIERS JOURS     │
├──────────────────────────┤
│                          │
{timeline}│                          │
│  Sessions: {total_sessions:<14} │
╰──────────────────────────╯
```"""

    embed.set_footer(text="◆ Challenge Bot")

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
/challenges — Tous tes défis actifs
```

◆ **DÉFI** (par serveur)
```
/setup      — Créer un défi
/checkin    — Session + photo
/latecheckin— Session d'HIER
/checkinfor — Session pour qqn d'autre
/stats      — Progression du défi
/freeze     — Pause ce serveur
/freezeall  — Pause TOUS les défis
/rescue     — Sauver après oubli
/cancel     — Annuler le défi
```

◆ **RÈGLES**
```
• Semaine = Lundi → Dimanche
• Photo obligatoire
• Objectif manqué = GAME OVER
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

▼ **Multi-serveur**
Check-ins partagés entre serveurs.
Objectif modifié = appliqué lundi."""

    embed.set_footer(text="◆ Challenge Bot")

    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="reset", description="Réinitialiser les données (admin)")
async def reset_cmd(interaction: discord.Interaction):
    class ConfirmReset(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=30)

        @discord.ui.button(label="Confirmer", style=discord.ButtonStyle.danger)
        async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
            conn = get_db()
            c = conn.cursor()
            c.execute('DELETE FROM checkins')
            c.execute('DELETE FROM history')
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
    if user_id not in [challenge['user1_id'], challenge['user2_id']]:
        await interaction.response.send_message("Tu ne participes pas.", ephemeral=True)
        return

    # Vérifier si déjà en freeze
    if user_id == challenge['user1_id']:
        is_frozen = challenge.get('freeze_user1', 0)
        freeze_col = "freeze_user1"
        user_name = challenge['user1_name']
    else:
        is_frozen = challenge.get('freeze_user2', 0)
        freeze_col = "freeze_user2"
        user_name = challenge['user2_name']

    if is_frozen:
        await interaction.response.send_message("Tu es déjà en freeze.", ephemeral=True)
        return

    conn = get_db()
    c = conn.cursor()
    c.execute(f'UPDATE challenge SET {freeze_col} = 1 WHERE id = %s', (challenge['id'],))
    conn.commit()
    conn.close()

    embed = discord.Embed(color=EMBED_COLOR)
    embed.description = f"""▸ **FREEZE ACTIVÉ**

**{user_name}** est en pause sur ce serveur.

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
    if user_id not in [challenge['user1_id'], challenge['user2_id']]:
        await interaction.response.send_message("Tu ne participes pas.", ephemeral=True)
        return

    # Vérifier si en freeze
    if user_id == challenge['user1_id']:
        is_frozen = challenge.get('freeze_user1', 0)
        freeze_col = "freeze_user1"
        user_name = challenge['user1_name']
    else:
        is_frozen = challenge.get('freeze_user2', 0)
        freeze_col = "freeze_user2"
        user_name = challenge['user2_name']

    if not is_frozen:
        await interaction.response.send_message("Tu n'es pas en freeze.", ephemeral=True)
        return

    conn = get_db()
    c = conn.cursor()
    c.execute(f'UPDATE challenge SET {freeze_col} = 0 WHERE id = %s', (challenge['id'],))
    conn.commit()
    conn.close()


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
        if user_id == challenge['user1_id']:
            if not challenge.get('freeze_user1', 0):
                c.execute('UPDATE challenge SET freeze_user1 = 1 WHERE id = %s', (challenge['id'],))
                frozen_count += 1
        else:
            if not challenge.get('freeze_user2', 0):
                c.execute('UPDATE challenge SET freeze_user2 = 1 WHERE id = %s', (challenge['id'],))
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
        if user_id == challenge['user1_id']:
            if challenge.get('freeze_user1', 0):
                c.execute('UPDATE challenge SET freeze_user1 = 0 WHERE id = %s', (challenge['id'],))
                unfrozen_count += 1
        else:
            if challenge.get('freeze_user2', 0):
                c.execute('UPDATE challenge SET freeze_user2 = 0 WHERE id = %s', (challenge['id'],))
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

    embed = discord.Embed(color=EMBED_COLOR)
    embed.description = f"""▸ **FREEZE DÉSACTIVÉ**

**{user_name}** reprend le défi.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

L'objectif hebdomadaire est de nouveau requis.

Bonne reprise !"""

    embed.set_footer(text="◆ Challenge Bot")

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="rescue", description="Sauver le défi après un oubli de check-in")
@app_commands.describe(photo="Photo de ta session manquée")
async def rescue_cmd(interaction: discord.Interaction, photo: discord.Attachment):
    """Permet de sauver un défi terminé si quelqu'un a oublié de check-in"""
    if not interaction.guild:
        await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
        return

    guild_id = interaction.guild.id
    user_id = interaction.user.id

    # Récupérer le dernier défi inactif de CE serveur
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM challenge WHERE guild_id = %s AND is_active = 0 ORDER BY id DESC LIMIT 1', (guild_id,))
    challenge = c.fetchone()

    if not challenge:
        conn.close()
        await interaction.response.send_message("Aucun défi terminé à sauver sur ce serveur.", ephemeral=True)
        return

    # Vérifier que l'utilisateur était participant
    if user_id not in [challenge['user1_id'], challenge['user2_id']]:
        conn.close()
        await interaction.response.send_message("Tu ne participais pas à ce défi.", ephemeral=True)
        return

    # Vérifier que c'est une image
    if not photo.content_type or not photo.content_type.startswith('image/'):
        conn.close()
        await interaction.response.send_message("Image requise.", ephemeral=True)
        return

    # Vérifier que le défi n'a pas été terminé il y a trop longtemps (max 24h)
    c.execute('SELECT end_date FROM history WHERE challenge_id = %s ORDER BY id DESC LIMIT 1', (challenge['id'],))
    history_row = c.fetchone()

    if history_row:
        end_date = datetime.datetime.fromisoformat(history_row['end_date'])
        now = datetime.datetime.now(PARIS_TZ)
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=PARIS_TZ)
        hours_since_end = (now - end_date).total_seconds() / 3600

        if hours_since_end > 24:
            conn.close()
            await interaction.response.send_message(
                f"Trop tard ! Le défi a été terminé il y a {int(hours_since_end)}h. Limite: 24h.",
                ephemeral=True
            )
            return

    # Déterminer la semaine de l'échec
    now = datetime.datetime.now(PARIS_TZ)
    yesterday = now - datetime.timedelta(days=1)
    iso = yesterday.isocalendar()
    week_number, year = iso[1], iso[0]

    if now.weekday() > 0:
        last_sunday = now - datetime.timedelta(days=now.weekday())
        iso = last_sunday.isocalendar()
        week_number, year = iso[1], iso[0]

    # Récupérer les profils pour les objectifs
    profile1 = get_profile(challenge['user1_id'])
    profile2 = get_profile(challenge['user2_id'])

    user1_goal = profile1['weekly_goal'] if profile1 else 4
    user2_goal = profile2['weekly_goal'] if profile2 else 4

    # Récupérer les check-ins ACTUELS
    user1_count = get_checkins_for_user_week(challenge['user1_id'], week_number, year)
    user2_count = get_checkins_for_user_week(challenge['user2_id'], week_number, year)

    # Ajouter +1 pour le rescue
    if user_id == challenge['user1_id']:
        user1_count += 1
    else:
        user2_count += 1

    # Vérifier le freeze
    user1_frozen = challenge.get('freeze_user1', 0)
    user2_frozen = challenge.get('freeze_user2', 0)

    user1_ok = user1_count >= user1_goal or user1_frozen
    user2_ok = user2_count >= user2_goal or user2_frozen

    if user1_ok and user2_ok:
        # Les deux passent ! Ajouter le check-in (global) et réactiver
        rescue_timestamp = datetime.datetime.now().isoformat()

        c.execute('''
            INSERT INTO checkins (user_id, timestamp, week_number, year, photo_url, note)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (user_id, rescue_timestamp, week_number, year, photo.url, "Rescue"))

        c.execute('UPDATE challenge SET is_active = 1 WHERE id = %s', (challenge['id'],))
        c.execute('DELETE FROM history WHERE challenge_id = %s', (challenge['id'],))

        conn.commit()
        conn.close()

        saved_name = challenge['user1_name'] if user_id == challenge['user1_id'] else challenge['user2_name']

        embed = discord.Embed(color=EMBED_COLOR)
        embed.description = f"""▸ **DÉFI SAUVÉ !**

**{saved_name}** a ajouté son check-in manquant.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **NOUVEAU SCORE**
```
{challenge['user1_name'][:12]:12} ——— {user1_count}/{user1_goal} {"✓" if user1_ok else "✗"}
{challenge['user2_name'][:12]:12} ——— {user2_count}/{user2_goal} {"✓" if user2_ok else "✗"}
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

▼ **Le défi continue !**
Pas de gage cette fois. 😅"""

        embed.set_image(url=photo.url)
        embed.set_footer(text="◆ Challenge Bot • Rescue")

        await interaction.response.send_message(
            content=f"<@{challenge['user1_id']}> <@{challenge['user2_id']}>",
            embed=embed
        )

    else:
        conn.close()

        if user_id == challenge['user1_id']:
            user_count = user1_count
            user_goal = user1_goal
        else:
            user_count = user2_count
            user_goal = user2_goal

        embed = discord.Embed(color=EMBED_COLOR)
        embed.description = f"""▸ **RESCUE IMPOSSIBLE**

Même avec ce check-in, l'objectif n'est pas atteint.

```
Score avec rescue: {user_count}/{user_goal}
Manquant: {user_goal - user_count}
```

Le défi reste terminé."""

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

    conn = get_db()
    c = conn.cursor()

    for challenge in challenges:
        try:
            # Vérifier si c'est la première semaine du défi
            start_week = challenge.get('week_number', 0)
            if start_week == week_number:
                start_date_str = challenge.get('start_date')
                if start_date_str:
                    start_date = datetime.datetime.fromisoformat(start_date_str)
                    if start_date.weekday() != 0:
                        continue  # Pas créé un lundi → ignorer cette semaine
                else:
                    continue

            # Récupérer les profils pour les objectifs
            profile1 = get_profile(challenge['user1_id'])
            profile2 = get_profile(challenge['user2_id'])

            user1_goal = profile1['weekly_goal'] if profile1 else 4
            user2_goal = profile2['weekly_goal'] if profile2 else 4

            user1_count = get_checkins_for_user_week(challenge['user1_id'], week_number, year)
            user2_count = get_checkins_for_user_week(challenge['user2_id'], week_number, year)

            # Vérifier le freeze
            user1_frozen = challenge.get('freeze_user1', 0)
            user2_frozen = challenge.get('freeze_user2', 0)

            user1_failed = user1_count < user1_goal and not user1_frozen
            user2_failed = user2_count < user2_goal and not user2_frozen

            channel = bot.get_channel(challenge['channel_id'])
            if not channel:
                continue

            total_weeks = challenge.get('total_weeks', 0)
            challenge_week = get_challenge_week_number(challenge['start_date'])

            if user1_failed or user2_failed:
                c.execute('UPDATE challenge SET is_active = 0 WHERE id = %s', (challenge['id'],))

                embed = discord.Embed(color=EMBED_COLOR)

                if user1_failed and user2_failed:
                    embed.description = f"""▸ **GAME OVER**

Les deux ont échoué.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **{challenge['user1_name'].upper()}** — ÉCHEC
```
{format_stat_line("SCORE", f"{user1_count}/{user1_goal}")}
{format_stat_line("GAGE", challenge['user1_gage'][:20])}
```

◆ **{challenge['user2_name'].upper()}** — ÉCHEC
```
{format_stat_line("SCORE", f"{user2_count}/{user2_goal}")}
{format_stat_line("GAGE", challenge['user2_gage'][:20])}
```

▼ **Les deux doivent faire leur gage.**"""

                    c.execute('''
                        INSERT INTO history (challenge_id, guild_id, winner_id, winner_name, loser_id, loser_name, loser_gage, end_date, reason, total_weeks)
                        VALUES (%s, %s, NULL, NULL, NULL, 'Les deux', %s, %s, 'Double échec', %s)
                    ''', (challenge['id'], challenge['guild_id'], f"{challenge['user1_gage']} / {challenge['user2_gage']}", now.isoformat(), total_weeks))

                elif user1_failed:
                    embed.description = f"""▸ **GAME OVER**

**{challenge['user1_name']}** a perdu.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **PERDANT**
```
{challenge['user1_name']}
{format_stat_line("SCORE", f"{user1_count}/{user1_goal}")}
```

◆ **GAGNANT**
```
{challenge['user2_name']}
{format_stat_line("SCORE", f"{user2_count}/{user2_goal}")}
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

▼ **GAGE À FAIRE**
{challenge['user1_gage']}"""

                    c.execute('''
                        INSERT INTO history (challenge_id, guild_id, winner_id, winner_name, loser_id, loser_name, loser_gage, end_date, reason, total_weeks)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ''', (challenge['id'], challenge['guild_id'], challenge['user2_id'], challenge['user2_name'],
                          challenge['user1_id'], challenge['user1_name'], challenge['user1_gage'], now.isoformat(), 'Objectif non atteint', total_weeks))

                else:
                    embed.description = f"""▸ **GAME OVER**

**{challenge['user2_name']}** a perdu.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **PERDANT**
```
{challenge['user2_name']}
{format_stat_line("SCORE", f"{user2_count}/{user2_goal}")}
```

◆ **GAGNANT**
```
{challenge['user1_name']}
{format_stat_line("SCORE", f"{user1_count}/{user1_goal}")}
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

▼ **GAGE À FAIRE**
{challenge['user2_gage']}"""

                    c.execute('''
                        INSERT INTO history (challenge_id, guild_id, winner_id, winner_name, loser_id, loser_name, loser_gage, end_date, reason, total_weeks)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ''', (challenge['id'], challenge['guild_id'], challenge['user1_id'], challenge['user1_name'],
                          challenge['user2_id'], challenge['user2_name'], challenge['user2_gage'], now.isoformat(), 'Objectif non atteint', total_weeks))

                embed.set_footer(text=f"◆ Challenge Bot • Semaine {challenge_week}")
                await channel.send(f"<@{challenge['user1_id']}> <@{challenge['user2_id']}>", embed=embed)

            else:
                # Les deux ont réussi
                new_streak1 = challenge.get('streak_user1', 0) + 1
                new_streak2 = challenge.get('streak_user2', 0) + 1
                new_total = total_weeks + 1

                c.execute('''
                    UPDATE challenge
                    SET streak_user1 = %s, streak_user2 = %s, total_weeks = %s, week_number = %s
                    WHERE id = %s
                ''', (new_streak1, new_streak2, new_total, week_number + 1, challenge['id']))

                embed = discord.Embed(color=EMBED_COLOR)
                embed.description = f"""▸ **SEMAINE {challenge_week} VALIDÉE**

Les deux ont réussi !

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **{challenge['user1_name'].upper()}**
```
{format_stat_line("SCORE", f"{user1_count}/{user1_goal}")} ✓
```

◆ **{challenge['user2_name'].upper()}**
```
{format_stat_line("SCORE", f"{user2_count}/{user2_goal}")} ✓
```

▼ **Le défi continue.**"""

                embed.set_footer(text=f"◆ Challenge Bot • Semaine {challenge_week + 1}")
                await channel.send(embed=embed)

        except Exception as e:
            print(f"Erreur check_weekly_goals pour challenge {challenge.get('id')}: {e}")

    conn.commit()
    conn.close()


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

            # Récupérer les profils pour les objectifs
            profile1 = get_profile(challenge['user1_id'])
            profile2 = get_profile(challenge['user2_id'])

            user1_goal = profile1['weekly_goal'] if profile1 else 4
            user2_goal = profile2['weekly_goal'] if profile2 else 4

            user1_count = get_checkins_for_user_week(challenge['user1_id'], week_number, year)
            user2_count = get_checkins_for_user_week(challenge['user2_id'], week_number, year)

            channel = bot.get_channel(challenge['channel_id'])
            if not channel:
                continue

            # Vérifier le freeze
            user1_frozen = challenge.get('freeze_user1', 0)
            user2_frozen = challenge.get('freeze_user2', 0)

            user1_remaining = max(0, user1_goal - user1_count) if not user1_frozen else 0
            user2_remaining = max(0, user2_goal - user2_count) if not user2_frozen else 0

            if user1_remaining > 0 or user2_remaining > 0:
                embed = discord.Embed(color=EMBED_COLOR)

                reminder_text = "▸ **RAPPEL**\n\n"
                ping_content = ""

                if user1_remaining > 0:
                    reminder_text += f"<@{challenge['user1_id']}> — **{user1_remaining}** session(s) restante(s)\n"
                    ping_content += f"<@{challenge['user1_id']}> "

                if user2_remaining > 0:
                    reminder_text += f"<@{challenge['user2_id']}> — **{user2_remaining}** session(s) restante(s)\n"
                    ping_content += f"<@{challenge['user2_id']}>"

                reminder_text += f"\n**{hours_remaining}** heure(s) restante(s)."

                embed.description = reminder_text
                embed.set_footer(text="◆ Challenge Bot")

                await channel.send(content=ping_content, embed=embed)

        except Exception as e:
            print(f"Erreur send_reminders pour challenge {challenge.get('id')}: {e}")


@check_weekly_goals.before_loop
async def before_check():
    await bot.wait_until_ready()

@send_reminders.before_loop
async def before_reminders():
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

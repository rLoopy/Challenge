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

    c.execute('''
        CREATE TABLE IF NOT EXISTS challenge (
            id SERIAL PRIMARY KEY,
            user1_id BIGINT NOT NULL,
            user1_name TEXT NOT NULL,
            user1_activity TEXT NOT NULL,
            user1_goal INTEGER NOT NULL,
            user1_gage TEXT NOT NULL,
            user2_id BIGINT NOT NULL,
            user2_name TEXT NOT NULL,
            user2_activity TEXT NOT NULL,
            user2_goal INTEGER NOT NULL,
            user2_gage TEXT NOT NULL,
            channel_id BIGINT NOT NULL,
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

    # Ajouter les colonnes freeze si elles n'existent pas (migration)
    c.execute('''
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='challenge' AND column_name='freeze_user1') THEN
                ALTER TABLE challenge ADD COLUMN freeze_user1 INTEGER DEFAULT 0;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='challenge' AND column_name='freeze_user2') THEN
                ALTER TABLE challenge ADD COLUMN freeze_user2 INTEGER DEFAULT 0;
            END IF;
        END $$;
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS checkins (
            id SERIAL PRIMARY KEY,
            challenge_id INTEGER NOT NULL,
            user_id BIGINT NOT NULL,
            timestamp TEXT NOT NULL,
            week_number INTEGER NOT NULL,
            year INTEGER NOT NULL,
            photo_url TEXT,
            FOREIGN KEY (challenge_id) REFERENCES challenge(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS history (
            id SERIAL PRIMARY KEY,
            challenge_id INTEGER NOT NULL,
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

    conn.commit()
    conn.close()
    print("✅ Base de données PostgreSQL initialisée")

def get_active_challenge():
    """Récupère le défi actif"""
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM challenge WHERE is_active = 1 ORDER BY id DESC LIMIT 1')
    row = c.fetchone()
    conn.close()

    if row:
        # Convertir en tuple pour compatibilité
        # Index: 0=id, 1=user1_id, 2=user1_name, 3=user1_activity, 4=user1_goal, 5=user1_gage
        #        6=user2_id, 7=user2_name, 8=user2_activity, 9=user2_goal, 10=user2_gage
        #        11=channel_id, 12=start_date, 13=is_active, 14=week_number
        #        15=streak_user1, 16=streak_user2, 17=total_weeks
        #        18=freeze_user1, 19=freeze_user2
        return (
            row['id'], row['user1_id'], row['user1_name'], row['user1_activity'],
            row['user1_goal'], row['user1_gage'], row['user2_id'], row['user2_name'],
            row['user2_activity'], row['user2_goal'], row['user2_gage'], row['channel_id'],
            row['start_date'], row['is_active'], row['week_number'],
            row['streak_user1'], row['streak_user2'], row['total_weeks'],
            row.get('freeze_user1', 0) or 0, row.get('freeze_user2', 0) or 0
        )
    return None

def get_checkins_for_week(challenge_id, week_number, year):
    """Récupère les check-ins de la semaine"""
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT user_id, COUNT(*) as count
        FROM checkins
        WHERE challenge_id = %s AND week_number = %s AND year = %s
        GROUP BY user_id
    ''', (challenge_id, week_number, year))
    checkins = c.fetchall()
    conn.close()
    return {row['user_id']: row['count'] for row in checkins}

def get_total_checkins(challenge_id, user_id):
    """Récupère le total de check-ins"""
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) as count FROM checkins WHERE challenge_id = %s AND user_id = %s', (challenge_id, user_id))
    result = c.fetchone()['count']
    conn.close()
    return result

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

@bot.tree.command(name="setup", description="Créer un nouveau défi")
@app_commands.describe(
    user1="Premier participant",
    activity1="Activité (ex: Salle)",
    goal1="Sessions par semaine",
    gage1="Gage si échec",
    user2="Deuxième participant",
    activity2="Activité (ex: Boxe)",
    goal2="Sessions par semaine",
    gage2="Gage si échec"
)
async def setup(
    interaction: discord.Interaction,
    user1: discord.Member,
    activity1: str,
    goal1: int,
    gage1: str,
    user2: discord.Member,
    activity2: str,
    goal2: int,
    gage2: str
):
    challenge = get_active_challenge()
    if challenge:
        await interaction.response.send_message("Un défi est déjà en cours.", ephemeral=True)
        return

    if goal1 <= 0 or goal2 <= 0 or goal1 > 7 or goal2 > 7:
        await interaction.response.send_message("Objectif entre 1 et 7.", ephemeral=True)
        return

    if user1.id == user2.id:
        await interaction.response.send_message("Deux participants différents requis.", ephemeral=True)
        return

    conn = get_db()
    c = conn.cursor()

    week_number, year = get_week_info()
    start_date = datetime.datetime.now().isoformat()

    c.execute('''
        INSERT INTO challenge
        (user1_id, user1_name, user1_activity, user1_goal, user1_gage,
         user2_id, user2_name, user2_activity, user2_goal, user2_gage,
         channel_id, start_date, week_number, streak_user1, streak_user2, total_weeks)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, 0, 0)
    ''', (user1.id, user1.display_name, activity1, goal1, gage1,
          user2.id, user2.display_name, activity2, goal2, gage2,
          interaction.channel_id, start_date, week_number))

    conn.commit()
    conn.close()

    # Embed stylé
    embed = discord.Embed(color=EMBED_COLOR)

    embed.description = f"""▸ **NOUVEAU DÉFI**

{user1.display_name} **vs** {user2.display_name}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **{user1.display_name.upper()}**
```
{format_stat_line("ACTIVITÉ", activity1)}
{format_stat_line("OBJECTIF", f"{goal1}x/semaine")}
{format_stat_line("GAGE", gage1[:20])}
```

◆ **{user2.display_name.upper()}**
```
{format_stat_line("ACTIVITÉ", activity2)}
{format_stat_line("OBJECTIF", f"{goal2}x/semaine")}
{format_stat_line("GAGE", gage2[:20])}
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

▼ **Règles**
Lundi → Dimanche • Photo obligatoire
Objectif manqué = **GAME OVER**"""

    embed.set_footer(text=f"◆ Challenge Bot • {datetime.datetime.now().strftime('%d/%m/%Y')}")

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="checkin", description="Enregistrer une session")
@app_commands.describe(photo="Photo de ta session")
async def checkin(interaction: discord.Interaction, photo: discord.Attachment):
    challenge = get_active_challenge()

    if not challenge:
        await interaction.response.send_message("Pas de défi actif.", ephemeral=True)
        return

    user_id = interaction.user.id
    if user_id not in [challenge[1], challenge[6]]:
        await interaction.response.send_message("Tu ne participes pas.", ephemeral=True)
        return

    if not photo.content_type or not photo.content_type.startswith('image/'):
        await interaction.response.send_message("Image requise.", ephemeral=True)
        return

    conn = get_db()
    c = conn.cursor()

    week_number, year = get_week_info()
    timestamp = datetime.datetime.now().isoformat()

    c.execute('''
        INSERT INTO checkins (challenge_id, user_id, timestamp, week_number, year, photo_url)
        VALUES (%s, %s, %s, %s, %s, %s)
    ''', (challenge[0], user_id, timestamp, week_number, year, photo.url))

    conn.commit()
    conn.close()

    checkins = get_checkins_for_week(challenge[0], week_number, year)

    if user_id == challenge[1]:
        user_name, user_activity, user_goal = challenge[2], challenge[3], challenge[4]
        other_name, other_goal, other_id = challenge[7], challenge[9], challenge[6]
    else:
        user_name, user_activity, user_goal = challenge[7], challenge[8], challenge[9]
        other_name, other_goal, other_id = challenge[2], challenge[4], challenge[1]

    user_count = checkins.get(user_id, 0)
    other_count = checkins.get(other_id, 0)

    # Statut
    if user_count >= user_goal:
        status = "✓ VALIDÉ"
        status_emoji = "★"
    else:
        status = "En cours"
        status_emoji = "▸"

    challenge_week = get_challenge_week_number(challenge[12])
    days = get_days_remaining()

    # Embed stylé
    embed = discord.Embed(color=EMBED_COLOR)

    embed.description = f"""{status_emoji} **{status.upper()}**

**{user_name.upper()}**

{user_activity}
**{user_count} / {user_goal}**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **PROGRESSION**
```
{user_name[:10]:10} {progress_bar(user_count, user_goal)} {user_count}/{user_goal}
{other_name[:10]:10} {progress_bar(other_count, other_goal)} {other_count}/{other_goal}
```

◆ **SEMAINE {challenge_week}**
```
{format_stat_line("RESTANT", f"{days}j")}
{format_stat_line("DEADLINE", "Dimanche 23h")}
```"""

    embed.set_image(url=photo.url)
    embed.set_footer(text=f"◆ Challenge Bot • {datetime.datetime.now().strftime('%H:%M')}")

    # Mention l'autre participant
    await interaction.response.send_message(content=f"<@{other_id}>", embed=embed)


@bot.tree.command(name="stats", description="Voir les statistiques")
async def stats(interaction: discord.Interaction):
    challenge = get_active_challenge()

    if not challenge:
        await interaction.response.send_message("Pas de défi actif.", ephemeral=True)
        return

    week_number, year = get_week_info()
    checkins = get_checkins_for_week(challenge[0], week_number, year)

    user1_count = checkins.get(challenge[1], 0)
    user2_count = checkins.get(challenge[6], 0)

    user1_total = get_total_checkins(challenge[0], challenge[1])
    user2_total = get_total_checkins(challenge[0], challenge[6])

    challenge_week = get_challenge_week_number(challenge[12])
    days = get_days_remaining()

    # Vérifier si c'est une semaine "d'échauffement" (créé en cours de semaine, pas un lundi)
    warmup_week = False
    start_week = challenge[14] if len(challenge) > 14 else 0
    if start_week == week_number:
        start_date_str = challenge[12] if len(challenge) > 12 else None
        if start_date_str:
            start_date = datetime.datetime.fromisoformat(start_date_str)
            if start_date.weekday() != 0:  # Pas créé un lundi
                warmup_week = True

    # Vérifier le freeze
    user1_frozen = challenge[18] if len(challenge) > 18 else 0
    user2_frozen = challenge[19] if len(challenge) > 19 else 0

    # Déterminer le leader
    user1_pct = user1_count / challenge[4] if challenge[4] > 0 else 0
    user2_pct = user2_count / challenge[9] if challenge[9] > 0 else 0

    if warmup_week:
        status_text = "⚡ Semaine d'échauffement (non comptée)"
    elif user1_count >= challenge[4] and user2_count >= challenge[9]:
        status_text = "✓ Les deux ont validé"
    elif user1_pct > user2_pct:
        status_text = f"▸ {challenge[2]} mène"
    elif user2_pct > user1_pct:
        status_text = f"▸ {challenge[7]} mène"
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

◆ **{challenge[2].upper()}**{user1_freeze_tag} — {challenge[3]}
```
CETTE SEMAINE ——— {user1_count}/{challenge[4]}
{progress_bar(user1_count, challenge[4])} {"✓" if user1_count >= challenge[4] else ""}{"FREEZE" if user1_frozen else ""}

TOTAL ——————————— {user1_total}
GAGE ———————————— {challenge[5][:15]}
```

◆ **{challenge[7].upper()}**{user2_freeze_tag} — {challenge[8]}
```
CETTE SEMAINE ——— {user2_count}/{challenge[9]}
{progress_bar(user2_count, challenge[9])} {"✓" if user2_count >= challenge[9] else ""}{"FREEZE" if user2_frozen else ""}

TOTAL ——————————— {user2_total}
GAGE ———————————— {challenge[10][:15]}
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **DEADLINE**
```
{time_status}
Vérification: Dimanche minuit
```"""

    embed.set_footer(text=f"◆ Challenge Bot • Semaine {challenge_week}")

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="cancel", description="Annuler le défi")
async def cancel(interaction: discord.Interaction):
    challenge = get_active_challenge()

    if not challenge:
        await interaction.response.send_message("Pas de défi actif.", ephemeral=True)
        return

    if interaction.user.id not in [challenge[1], challenge[6]]:
        await interaction.response.send_message("Réservé aux participants.", ephemeral=True)
        return

    class ConfirmView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=30)

        @discord.ui.button(label="Confirmer", style=discord.ButtonStyle.danger)
        async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
            conn = get_db()
            c = conn.cursor()
            c.execute('UPDATE challenge SET is_active = 0 WHERE id = %s', (challenge[0],))
            conn.commit()
            conn.close()

            embed = discord.Embed(color=EMBED_COLOR)
            embed.description = """▸ **DÉFI ANNULÉ**

Le défi a été annulé.
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

Voulez-vous vraiment annuler le défi ?

Cette action est irréversible."""

    await interaction.response.send_message(embed=embed, view=ConfirmView(), ephemeral=True)


@bot.tree.command(name="calendar", description="Calendrier des sessions (30 derniers jours)")
async def calendar_cmd(interaction: discord.Interaction):
    challenge = get_active_challenge()

    if not challenge:
        await interaction.response.send_message("Pas de défi actif.", ephemeral=True)
        return

    user_id = interaction.user.id
    if user_id not in [challenge[1], challenge[6]]:
        await interaction.response.send_message("Tu ne participes pas.", ephemeral=True)
        return

    # Déterminer l'utilisateur
    if user_id == challenge[1]:
        user_name = challenge[2]
        user_activity = challenge[3]
    else:
        user_name = challenge[7]
        user_activity = challenge[8]

    # Récupérer les check-ins des 30 derniers jours
    now = datetime.datetime.now()
    today = now.date()
    thirty_days_ago = today - datetime.timedelta(days=30)

    conn = get_db()
    c = conn.cursor()

    # Récupérer tous les check-ins pour cet utilisateur
    c.execute('''
        SELECT timestamp FROM checkins
        WHERE challenge_id = %s AND user_id = %s
    ''', (challenge[0], user_id))

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
    month_names = ["", "Jan", "Fév", "Mar", "Avr", "Mai", "Juin",
                   "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]

    # Construire la timeline
    timeline = ""
    for checkin_date in checkin_dates:
        day_name = day_names[checkin_date.weekday()]
        month_abbr = month_names[checkin_date.month]

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

Un défi. Deux personnes. Pas d'excuses.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **COMMANDES**
```
/setup    — Créer un défi
/checkin  — Enregistrer une session
/stats    — Voir la progression
/calendar — Calendrier (30 jours)
/freeze   — Pause (maladie, etc.)
/unfreeze — Reprendre le défi
/rescue   — Sauver après oubli
/cancel   — Annuler le défi
```

◆ **RÈGLES**
```
• Semaine = Lundi → Dimanche
• Photo obligatoire
• Objectif manqué = GAME OVER
• Le perdant fait son gage
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

▼ **Comment ça marche ?**
1. Créez un défi avec `/setup`
2. Faites vos sessions
3. Validez avec `/checkin` + photo
4. Dimanche minuit = vérification"""

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


@bot.tree.command(name="test", description="Vérifier l'état du bot")
async def test_cmd(interaction: discord.Interaction):
    challenge = get_active_challenge()

    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) as count FROM checkins')
    total_checkins = c.fetchone()['count']
    c.execute('SELECT COUNT(*) as count FROM challenge')
    total_challenges = c.fetchone()['count']
    conn.close()

    embed = discord.Embed(color=EMBED_COLOR)

    embed.description = f"""▸ **STATUS**

Bot opérationnel

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **DATABASE**
```
{format_stat_line("DÉFI ACTIF", "Oui" if challenge else "Non")}
{format_stat_line("TOTAL DÉFIS", str(total_challenges))}
{format_stat_line("CHECK-INS", str(total_checkins))}
{format_stat_line("DB TYPE", "PostgreSQL")}
```

◆ **BOT**
```
{format_stat_line("PING", f"{round(bot.latency * 1000)}ms")}
{format_stat_line("SERVEURS", str(len(bot.guilds)))}
```"""

    embed.set_footer(text="◆ Challenge Bot")

    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="freeze", description="Mettre en pause (maladie, etc.)")
@app_commands.describe(raison="Raison du freeze (optionnel)")
async def freeze_cmd(interaction: discord.Interaction, raison: str = "Non spécifiée"):
    challenge = get_active_challenge()

    if not challenge:
        await interaction.response.send_message("Pas de défi actif.", ephemeral=True)
        return

    user_id = interaction.user.id
    if user_id not in [challenge[1], challenge[6]]:
        await interaction.response.send_message("Tu ne participes pas.", ephemeral=True)
        return

    # Vérifier si déjà en freeze
    if user_id == challenge[1]:
        is_frozen = challenge[18]
        freeze_col = "freeze_user1"
        user_name = challenge[2]
    else:
        is_frozen = challenge[19]
        freeze_col = "freeze_user2"
        user_name = challenge[7]

    if is_frozen:
        await interaction.response.send_message("Tu es déjà en freeze.", ephemeral=True)
        return

    conn = get_db()
    c = conn.cursor()
    c.execute(f'UPDATE challenge SET {freeze_col} = 1 WHERE id = %s', (challenge[0],))
    conn.commit()
    conn.close()

    embed = discord.Embed(color=EMBED_COLOR)
    embed.description = f"""▸ **FREEZE ACTIVÉ**

**{user_name}** est en pause.

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


@bot.tree.command(name="unfreeze", description="Reprendre le défi")
async def unfreeze_cmd(interaction: discord.Interaction):
    challenge = get_active_challenge()

    if not challenge:
        await interaction.response.send_message("Pas de défi actif.", ephemeral=True)
        return

    user_id = interaction.user.id
    if user_id not in [challenge[1], challenge[6]]:
        await interaction.response.send_message("Tu ne participes pas.", ephemeral=True)
        return

    # Vérifier si en freeze
    if user_id == challenge[1]:
        is_frozen = challenge[18]
        freeze_col = "freeze_user1"
        user_name = challenge[2]
    else:
        is_frozen = challenge[19]
        freeze_col = "freeze_user2"
        user_name = challenge[7]

    if not is_frozen:
        await interaction.response.send_message("Tu n'es pas en freeze.", ephemeral=True)
        return

    conn = get_db()
    c = conn.cursor()
    c.execute(f'UPDATE challenge SET {freeze_col} = 0 WHERE id = %s', (challenge[0],))
    conn.commit()
    conn.close()

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
    user_id = interaction.user.id

    # Récupérer le dernier défi inactif
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM challenge WHERE is_active = 0 ORDER BY id DESC LIMIT 1')
    row = c.fetchone()

    if not row:
        conn.close()
        await interaction.response.send_message("Aucun défi terminé à sauver.", ephemeral=True)
        return

    challenge = (
        row['id'], row['user1_id'], row['user1_name'], row['user1_activity'],
        row['user1_goal'], row['user1_gage'], row['user2_id'], row['user2_name'],
        row['user2_activity'], row['user2_goal'], row['user2_gage'], row['channel_id'],
        row['start_date'], row['is_active'], row['week_number'],
        row['streak_user1'], row['streak_user2'], row['total_weeks'],
        row.get('freeze_user1', 0) or 0, row.get('freeze_user2', 0) or 0
    )

    # Vérifier que l'utilisateur était participant
    if user_id not in [challenge[1], challenge[6]]:
        conn.close()
        await interaction.response.send_message("Tu ne participais pas à ce défi.", ephemeral=True)
        return

    # Vérifier que c'est une image
    if not photo.content_type or not photo.content_type.startswith('image/'):
        conn.close()
        await interaction.response.send_message("Image requise.", ephemeral=True)
        return

    # Vérifier que le défi n'a pas été terminé il y a trop longtemps (max 24h)
    # On regarde l'historique
    c.execute('SELECT end_date FROM history WHERE challenge_id = %s ORDER BY id DESC LIMIT 1', (challenge[0],))
    history_row = c.fetchone()

    if history_row:
        end_date = datetime.datetime.fromisoformat(history_row['end_date'])
        now = datetime.datetime.now(PARIS_TZ)
        # Rendre end_date timezone-aware si nécessaire
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

    # Déterminer la semaine de l'échec (semaine précédente)
    now = datetime.datetime.now(PARIS_TZ)
    # Si on est lundi, la semaine échouée est celle d'hier (dimanche)
    yesterday = now - datetime.timedelta(days=1)
    iso = yesterday.isocalendar()
    week_number, year = iso[1], iso[0]

    # Si on est plus tard dans la semaine, prendre la semaine d'avant
    if now.weekday() > 0:  # Pas lundi
        last_sunday = now - datetime.timedelta(days=now.weekday())
        iso = last_sunday.isocalendar()
        week_number, year = iso[1], iso[0]

    # Ajouter le check-in manquant
    # On met un timestamp du dimanche 23h pour être dans la bonne semaine
    rescue_timestamp = datetime.datetime.now().isoformat()

    c.execute('''
        INSERT INTO checkins (challenge_id, user_id, timestamp, week_number, year, photo_url)
        VALUES (%s, %s, %s, %s, %s, %s)
    ''', (challenge[0], user_id, rescue_timestamp, week_number, year, photo.url))

    # Recalculer les check-ins
    checkins = get_checkins_for_week(challenge[0], week_number, year)

    user1_count = checkins.get(challenge[1], 0)
    user2_count = checkins.get(challenge[6], 0)

    user1_goal = challenge[4]
    user2_goal = challenge[9]

    # Vérifier le freeze
    user1_frozen = challenge[18]
    user2_frozen = challenge[19]

    user1_ok = user1_count >= user1_goal or user1_frozen
    user2_ok = user2_count >= user2_goal or user2_frozen

    if user1_ok and user2_ok:
        # Les deux passent maintenant ! Réactiver le défi
        c.execute('UPDATE challenge SET is_active = 1 WHERE id = %s', (challenge[0],))

        # Supprimer l'entrée d'historique
        c.execute('DELETE FROM history WHERE challenge_id = %s ORDER BY id DESC LIMIT 1', (challenge[0],))

        conn.commit()
        conn.close()

        # Déterminer qui a été sauvé
        if user_id == challenge[1]:
            saved_name = challenge[2]
        else:
            saved_name = challenge[7]

        embed = discord.Embed(color=EMBED_COLOR)
        embed.description = f"""▸ **DÉFI SAUVÉ !**

**{saved_name}** a ajouté son check-in manquant.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **NOUVEAU SCORE**
```
{challenge[2][:12]:12} ——— {user1_count}/{user1_goal} {"✓" if user1_ok else "✗"}
{challenge[7][:12]:12} ——— {user2_count}/{user2_goal} {"✓" if user2_ok else "✗"}
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

▼ **Le défi continue !**
Pas de gage cette fois. 😅"""

        embed.set_image(url=photo.url)
        embed.set_footer(text="◆ Challenge Bot • Rescue")

        # Mentionner les deux participants
        await interaction.response.send_message(
            content=f"<@{challenge[1]}> <@{challenge[6]}>",
            embed=embed
        )

    else:
        # Toujours pas suffisant
        conn.rollback()
        conn.close()

        if user_id == challenge[1]:
            user_count = user1_count
            user_goal = user1_goal
        else:
            user_count = user2_count
            user_goal = user2_goal

        embed = discord.Embed(color=EMBED_COLOR)
        embed.description = f"""▸ **RESCUE IMPOSSIBLE**

Même avec ce check-in, l'objectif n'est pas atteint.

```
Score actuel: {user_count}/{user_goal}
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

    challenge = get_active_challenge()
    if not challenge:
        return

    # À minuit lundi, on vérifie la semaine qui vient de se terminer (dimanche = hier)
    yesterday = now - datetime.timedelta(days=1)
    iso = yesterday.isocalendar()
    week_number, year = iso[1], iso[0]

    # Vérifier si c'est la première semaine du défi
    start_week = challenge[14] if len(challenge) > 14 else 0
    if start_week == week_number:
        # Si créé un lundi, la semaine compte. Sinon, on ignore.
        start_date_str = challenge[12] if len(challenge) > 12 else None
        if start_date_str:
            start_date = datetime.datetime.fromisoformat(start_date_str)
            start_day = start_date.weekday()  # 0 = lundi, 6 = dimanche
            if start_day != 0:  # Pas créé un lundi → ignorer cette semaine
                return
        else:
            return  # Pas de date → ignorer par sécurité

    checkins = get_checkins_for_week(challenge[0], week_number, year)

    user1_count = checkins.get(challenge[1], 0)
    user2_count = checkins.get(challenge[6], 0)

    user1_goal = challenge[4]
    user2_goal = challenge[9]

    # Vérifier le freeze - si en freeze, pas de pénalité
    user1_frozen = challenge[18] if len(challenge) > 18 else 0
    user2_frozen = challenge[19] if len(challenge) > 19 else 0

    user1_failed = user1_count < user1_goal and not user1_frozen
    user2_failed = user2_count < user2_goal and not user2_frozen

    channel = bot.get_channel(challenge[11])
    if not channel:
        return

    conn = get_db()
    c = conn.cursor()

    total_weeks = challenge[17] if len(challenge) > 17 else 0
    challenge_week = get_challenge_week_number(challenge[12])

    if user1_failed or user2_failed:
        c.execute('UPDATE challenge SET is_active = 0 WHERE id = %s', (challenge[0],))

        embed = discord.Embed(color=EMBED_COLOR)

        if user1_failed and user2_failed:
            embed.description = f"""▸ **GAME OVER**

Les deux ont échoué.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **{challenge[2].upper()}** — ÉCHEC
```
{format_stat_line("SCORE", f"{user1_count}/{user1_goal}")}
{format_stat_line("GAGE", challenge[5][:20])}
```

◆ **{challenge[7].upper()}** — ÉCHEC
```
{format_stat_line("SCORE", f"{user2_count}/{user2_goal}")}
{format_stat_line("GAGE", challenge[10][:20])}
```

▼ **Les deux doivent faire leur gage.**"""

            c.execute('''
                INSERT INTO history (challenge_id, winner_id, winner_name, loser_id, loser_name, loser_gage, end_date, reason, total_weeks)
                VALUES (%s, NULL, NULL, NULL, 'Les deux', %s, %s, 'Double échec', %s)
            ''', (challenge[0], f"{challenge[5]} / {challenge[10]}", now.isoformat(), total_weeks))

        elif user1_failed:
            embed.description = f"""▸ **GAME OVER**

**{challenge[2]}** a perdu.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **PERDANT**
```
{challenge[2]}
{format_stat_line("SCORE", f"{user1_count}/{user1_goal}")}
```

◆ **GAGNANT**
```
{challenge[7]}
{format_stat_line("SCORE", f"{user2_count}/{user2_goal}")}
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

▼ **GAGE À FAIRE**
{challenge[5]}"""

            c.execute('''
                INSERT INTO history (challenge_id, winner_id, winner_name, loser_id, loser_name, loser_gage, end_date, reason, total_weeks)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (challenge[0], challenge[6], challenge[7], challenge[1], challenge[2], challenge[5], now.isoformat(), 'Objectif non atteint', total_weeks))

        else:
            embed.description = f"""▸ **GAME OVER**

**{challenge[7]}** a perdu.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **PERDANT**
```
{challenge[7]}
{format_stat_line("SCORE", f"{user2_count}/{user2_goal}")}
```

◆ **GAGNANT**
```
{challenge[2]}
{format_stat_line("SCORE", f"{user1_count}/{user1_goal}")}
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

▼ **GAGE À FAIRE**
{challenge[10]}"""

            c.execute('''
                INSERT INTO history (challenge_id, winner_id, winner_name, loser_id, loser_name, loser_gage, end_date, reason, total_weeks)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (challenge[0], challenge[1], challenge[2], challenge[6], challenge[7], challenge[10], now.isoformat(), 'Objectif non atteint', total_weeks))

        embed.set_footer(text=f"◆ Challenge Bot • Semaine {challenge_week}")
        await channel.send(f"<@{challenge[1]}> <@{challenge[6]}>", embed=embed)

    else:
        # Les deux ont réussi
        new_streak1 = (challenge[15] if len(challenge) > 15 else 0) + 1
        new_streak2 = (challenge[16] if len(challenge) > 16 else 0) + 1
        new_total = total_weeks + 1

        c.execute('''
            UPDATE challenge
            SET streak_user1 = %s, streak_user2 = %s, total_weeks = %s, week_number = %s
            WHERE id = %s
        ''', (new_streak1, new_streak2, new_total, week_number + 1, challenge[0]))

        embed = discord.Embed(color=EMBED_COLOR)
        embed.description = f"""▸ **SEMAINE {challenge_week} VALIDÉE**

Les deux ont réussi !

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **{challenge[2].upper()}**
```
{format_stat_line("SCORE", f"{user1_count}/{user1_goal}")} ✓
```

◆ **{challenge[7].upper()}**
```
{format_stat_line("SCORE", f"{user2_count}/{user2_goal}")} ✓
```

▼ **Le défi continue.**"""

        embed.set_footer(text=f"◆ Challenge Bot • Semaine {challenge_week + 1}")
        await channel.send(embed=embed)

    conn.commit()
    conn.close()


@tasks.loop(hours=12)
async def send_reminders():
    """Rappels vendredi/samedi"""
    now = datetime.datetime.now(PARIS_TZ)

    if now.weekday() not in [4, 5]:
        return

    challenge = get_active_challenge()
    if not challenge:
        return

    week_number, year = get_week_info()

    # Vérifier si c'est la première semaine et pas créé un lundi
    start_week = challenge[14] if len(challenge) > 14 else 0
    if start_week == week_number:
        start_date_str = challenge[12] if len(challenge) > 12 else None
        if start_date_str:
            start_date = datetime.datetime.fromisoformat(start_date_str)
            if start_date.weekday() != 0:  # Pas créé un lundi
                return  # Pas de rappel, cette semaine ne compte pas
        else:
            return

    checkins = get_checkins_for_week(challenge[0], week_number, year)

    # Calculer les heures restantes jusqu'à dimanche minuit (lundi 00h00)
    # Trouver le prochain lundi 00h00
    days_until_monday = (7 - now.weekday()) % 7
    if days_until_monday == 0:
        days_until_monday = 7  # Si on est lundi, c'est dans 7 jours
    next_monday = now.replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=days_until_monday)
    time_remaining = next_monday - now
    hours_remaining = int(time_remaining.total_seconds() // 3600)

    channel = bot.get_channel(challenge[11])
    if not channel:
        return

    # Vérifier le freeze
    user1_frozen = challenge[18] if len(challenge) > 18 else 0
    user2_frozen = challenge[19] if len(challenge) > 19 else 0

    user1_count = checkins.get(challenge[1], 0)
    user1_remaining = challenge[4] - user1_count if not user1_frozen else 0

    user2_count = checkins.get(challenge[6], 0)
    user2_remaining = challenge[9] - user2_count if not user2_frozen else 0

    if user1_remaining > 0 or user2_remaining > 0:
        embed = discord.Embed(color=EMBED_COLOR)

        reminder_text = "▸ **RAPPEL**\n\n"

        if user1_remaining > 0:
            reminder_text += f"<@{challenge[1]}> — **{user1_remaining}** session(s) restante(s)\n"

        if user2_remaining > 0:
            reminder_text += f"<@{challenge[6]}> — **{user2_remaining}** session(s) restante(s)\n"

        reminder_text += f"\n**{hours_remaining}** heure(s) restante(s)."

        embed.description = reminder_text
        embed.set_footer(text="◆ Challenge Bot")

        await channel.send(embed=embed)


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

"""
Challenge Bot - Track your commitments. No excuses.
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import sqlite3
import datetime
import random
import os
from typing import Optional

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
#                       DATABASE
# ══════════════════════════════════════════════════════════════

DB_PATH = os.getenv('DB_PATH', 'challenge.db')

def get_db():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS challenge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user1_id INTEGER NOT NULL,
            user1_name TEXT NOT NULL,
            user1_activity TEXT NOT NULL,
            user1_goal INTEGER NOT NULL,
            user1_gage TEXT NOT NULL,
            user2_id INTEGER NOT NULL,
            user2_name TEXT NOT NULL,
            user2_activity TEXT NOT NULL,
            user2_goal INTEGER NOT NULL,
            user2_gage TEXT NOT NULL,
            channel_id INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            week_number INTEGER NOT NULL,
            streak_user1 INTEGER DEFAULT 0,
            streak_user2 INTEGER DEFAULT 0,
            total_weeks INTEGER DEFAULT 0
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS checkins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            challenge_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            week_number INTEGER NOT NULL,
            year INTEGER NOT NULL,
            photo_url TEXT,
            FOREIGN KEY (challenge_id) REFERENCES challenge(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            challenge_id INTEGER NOT NULL,
            winner_id INTEGER,
            winner_name TEXT,
            loser_id INTEGER,
            loser_name TEXT,
            loser_gage TEXT,
            end_date TEXT NOT NULL,
            reason TEXT NOT NULL,
            total_weeks INTEGER
        )
    ''')

    conn.commit()
    conn.close()

def get_active_challenge():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM challenge WHERE is_active = 1 ORDER BY id DESC LIMIT 1')
    challenge = c.fetchone()
    conn.close()
    return challenge

def get_checkins_for_week(challenge_id, week_number, year):
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT user_id, COUNT(*) as count
        FROM checkins
        WHERE challenge_id = ? AND week_number = ? AND year = ?
        GROUP BY user_id
    ''', (challenge_id, week_number, year))
    checkins = c.fetchall()
    conn.close()
    return {user_id: count for user_id, count in checkins}

def get_total_checkins(challenge_id, user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM checkins WHERE challenge_id = ? AND user_id = ?', (challenge_id, user_id))
    result = c.fetchone()[0]
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
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0)
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
        VALUES (?, ?, ?, ?, ?, ?)
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
    
    await interaction.response.send_message(embed=embed)


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
    
    # Déterminer le leader
    user1_pct = user1_count / challenge[4] if challenge[4] > 0 else 0
    user2_pct = user2_count / challenge[6] if challenge[9] > 0 else 0
    
    if user1_count >= challenge[4] and user2_count >= challenge[9]:
        status_text = "✓ Les deux ont validé"
    elif user1_pct > user2_pct:
        status_text = f"▸ {challenge[2]} mène"
    elif user2_pct > user1_pct:
        status_text = f"▸ {challenge[7]} mène"
    else:
        status_text = "▸ Égalité"
    
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

◆ **{challenge[2].upper()}** — {challenge[3]}
```
CETTE SEMAINE ——— {user1_count}/{challenge[4]}
{progress_bar(user1_count, challenge[4])} {"✓" if user1_count >= challenge[4] else ""}

TOTAL ——————————— {user1_total}
GAGE ———————————— {challenge[5][:15]}
```

◆ **{challenge[7].upper()}** — {challenge[8]}
```
CETTE SEMAINE ——— {user2_count}/{challenge[9]}
{progress_bar(user2_count, challenge[9])} {"✓" if user2_count >= challenge[9] else ""}

TOTAL ——————————— {user2_total}
GAGE ———————————— {challenge[10][:15]}
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **DEADLINE**
```
{time_status}
Vérification: Dimanche 23h30
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
            c.execute('UPDATE challenge SET is_active = 0 WHERE id = ?', (challenge[0],))
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


@bot.tree.command(name="help", description="Aide")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(color=EMBED_COLOR)
    
    embed.description = """▸ **CHALLENGE BOT**

Un défi. Deux personnes. Pas d'excuses.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

◆ **COMMANDES**
```
/setup   — Créer un défi
/checkin — Enregistrer une session
/stats   — Voir la progression
/cancel  — Annuler le défi
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
4. Dimanche 23h30 = vérification"""

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
    c.execute('SELECT COUNT(*) FROM checkins')
    total_checkins = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM challenge')
    total_challenges = c.fetchone()[0]
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
{format_stat_line("DB TYPE", "SQLite")}
```

◆ **BOT**
```
{format_stat_line("PING", f"{round(bot.latency * 1000)}ms")}
{format_stat_line("SERVEURS", str(len(bot.guilds)))}
```"""

    embed.set_footer(text="◆ Challenge Bot")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ══════════════════════════════════════════════════════════════
#                       SCHEDULED TASKS
# ══════════════════════════════════════════════════════════════

@tasks.loop(minutes=30)
async def check_weekly_goals():
    """Vérifie les objectifs dimanche soir"""
    now = datetime.datetime.now()

    if now.weekday() != 6 or now.hour != 23:
        return

    challenge = get_active_challenge()
    if not challenge:
        return

    week_number, year = get_week_info()

    start_week = challenge[14] if len(challenge) > 14 else 0
    if start_week == week_number:
        return

    checkins = get_checkins_for_week(challenge[0], week_number, year)

    user1_count = checkins.get(challenge[1], 0)
    user2_count = checkins.get(challenge[6], 0)

    user1_goal = challenge[4]
    user2_goal = challenge[9]

    user1_failed = user1_count < user1_goal
    user2_failed = user2_count < user2_goal

    channel = bot.get_channel(challenge[11])
    if not channel:
        return

    conn = get_db()
    c = conn.cursor()

    total_weeks = challenge[17] if len(challenge) > 17 else 0
    challenge_week = get_challenge_week_number(challenge[12])

    if user1_failed or user2_failed:
        c.execute('UPDATE challenge SET is_active = 0 WHERE id = ?', (challenge[0],))

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
                VALUES (?, NULL, NULL, NULL, 'Les deux', ?, ?, 'Double échec', ?)
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
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            SET streak_user1 = ?, streak_user2 = ?, total_weeks = ?, week_number = ?
            WHERE id = ?
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
    now = datetime.datetime.now()

    if now.weekday() not in [4, 5]:
        return

    challenge = get_active_challenge()
    if not challenge:
        return

    week_number, year = get_week_info()
    checkins = get_checkins_for_week(challenge[0], week_number, year)

    days = get_days_remaining()

    channel = bot.get_channel(challenge[11])
    if not channel:
        return

    user1_count = checkins.get(challenge[1], 0)
    user1_remaining = challenge[4] - user1_count

    user2_count = checkins.get(challenge[6], 0)
    user2_remaining = challenge[9] - user2_count

    if user1_remaining > 0 or user2_remaining > 0:
        embed = discord.Embed(color=EMBED_COLOR)
        
        reminder_text = "▸ **RAPPEL**\n\n"
        
        if user1_remaining > 0:
            reminder_text += f"<@{challenge[1]}> — **{user1_remaining}** session(s) restante(s)\n"
        
        if user2_remaining > 0:
            reminder_text += f"<@{challenge[6]}> — **{user2_remaining}** session(s) restante(s)\n"
        
        reminder_text += f"\n**{days}** jour(s) restant(s)."
        
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

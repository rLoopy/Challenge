"""
Challenge Bot - Track your commitments. No excuses.
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import sqlite3
import datetime
import random
from typing import Optional

# ══════════════════════════════════════════════════════════════
#                       CONFIG
# ══════════════════════════════════════════════════════════════

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Couleurs sobres
class Colors:
    DEFAULT = 0x2F3136      # Gris Discord
    SUCCESS = 0x57F287      # Vert
    WARNING = 0xFEE75C      # Jaune
    ERROR = 0xED4245        # Rouge
    INFO = 0x5865F2         # Bleu Discord

# Messages courts et directs
class Messages:
    CHECKIN = [
        "Session enregistrée.",
        "C'est noté.",
        "Validé.",
        "Ajouté.",
    ]

    AHEAD = [
        "En avance.",
        "Devant.",
    ]

    BEHIND = [
        "En retard.",
        "À la traîne.",
    ]

    LOSER = [
        "N'a pas tenu.",
        "A lâché.",
        "Objectif raté.",
    ]

# ══════════════════════════════════════════════════════════════
#                       UTILS
# ══════════════════════════════════════════════════════════════

def progress_bar(current: int, goal: int) -> str:
    """Barre de progression simple"""
    filled = min(current, goal)
    empty = max(0, goal - current)
    bar = "●" * filled + "○" * empty
    status = "✓" if current >= goal else ""
    return f"`{bar}` {current}/{goal} {status}"

def days_remaining() -> int:
    """Jours restants dans la semaine"""
    now = datetime.datetime.now()
    return (6 - now.weekday()) % 7 or (7 if now.weekday() != 6 else 0)

def get_week_info():
    now = datetime.datetime.now()
    iso = now.isocalendar()
    return iso[1], iso[0]

# ══════════════════════════════════════════════════════════════
#                       DATABASE
# ══════════════════════════════════════════════════════════════

def init_db():
    conn = sqlite3.connect('challenge.db')
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
    conn = sqlite3.connect('challenge.db')
    c = conn.cursor()
    c.execute('SELECT * FROM challenge WHERE is_active = 1 ORDER BY id DESC LIMIT 1')
    challenge = c.fetchone()
    conn.close()
    return challenge

def get_checkins_for_week(challenge_id, week_number, year):
    conn = sqlite3.connect('challenge.db')
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
    conn = sqlite3.connect('challenge.db')
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

    conn = sqlite3.connect('challenge.db')
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

    embed = discord.Embed(
        title="Nouveau défi",
        color=Colors.DEFAULT
    )

    embed.add_field(
        name=user1.display_name,
        value=f"{activity1}\n{goal1}x/semaine\n\n*Gage:* {gage1}",
        inline=True
    )

    embed.add_field(
        name="vs",
        value="​",  # caractère invisible
        inline=True
    )

    embed.add_field(
        name=user2.display_name,
        value=f"{activity2}\n{goal2}x/semaine\n\n*Gage:* {gage2}",
        inline=True
    )

    embed.set_footer(text="Semaine: Lundi → Dimanche • Photo obligatoire")

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

    conn = sqlite3.connect('challenge.db')
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
        user_name, user_goal = challenge[2], challenge[4]
        other_name, other_goal, other_id = challenge[7], challenge[9], challenge[6]
    else:
        user_name, user_goal = challenge[7], challenge[9]
        other_name, other_goal, other_id = challenge[2], challenge[4], challenge[1]

    user_count = checkins.get(user_id, 0)
    other_count = checkins.get(other_id, 0)

    embed = discord.Embed(
        title=random.choice(Messages.CHECKIN),
        description=f"**{user_name}**",
        color=Colors.SUCCESS if user_count >= user_goal else Colors.DEFAULT
    )

    embed.add_field(
        name=user_name,
        value=progress_bar(user_count, user_goal),
        inline=True
    )

    embed.add_field(
        name=other_name,
        value=progress_bar(other_count, other_goal),
        inline=True
    )

    embed.set_image(url=photo.url)

    days = days_remaining()
    embed.set_footer(text=f"{days}j restant{'s' if days > 1 else ''}" if days > 0 else "Dernier jour")

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

    streak1 = challenge[15] if len(challenge) > 15 else 0
    streak2 = challenge[16] if len(challenge) > 16 else 0

    embed = discord.Embed(
        title=f"Semaine {week_number}",
        color=Colors.DEFAULT
    )

    status1 = "✓" if user1_count >= challenge[4] else ""
    status2 = "✓" if user2_count >= challenge[9] else ""

    embed.add_field(
        name=f"{challenge[2]} {status1}",
        value=f"{progress_bar(user1_count, challenge[4])}\n\nTotal: {user1_total} • Streak: {streak1}",
        inline=True
    )

    embed.add_field(
        name=f"{challenge[7]} {status2}",
        value=f"{progress_bar(user2_count, challenge[9])}\n\nTotal: {user2_total} • Streak: {streak2}",
        inline=True
    )

    days = days_remaining()
    if days == 0:
        footer = "Dernier jour"
    elif days == 1:
        footer = "1 jour restant"
    else:
        footer = f"{days} jours restants"

    embed.set_footer(text=footer)

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
            conn = sqlite3.connect('challenge.db')
            c = conn.cursor()
            c.execute('UPDATE challenge SET is_active = 0 WHERE id = ?', (challenge[0],))
            conn.commit()
            conn.close()

            await interaction.response.edit_message(content="Défi annulé.", embed=None, view=None)
            self.stop()

        @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
        async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.edit_message(content="OK.", embed=None, view=None)
            self.stop()

    await interaction.response.send_message("Annuler le défi ?", view=ConfirmView(), ephemeral=True)


@bot.tree.command(name="help", description="Aide")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Commandes",
        color=Colors.DEFAULT
    )

    embed.description = """
`/setup` — Créer un défi
`/checkin` — Enregistrer une session (+ photo)
`/stats` — Voir les stats
`/cancel` — Annuler le défi

**Règles**
• Semaine = Lundi → Dimanche
• Photo obligatoire pour valider
• Objectif manqué = gage
"""

    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="reset", description="⚠️ Réinitialiser toutes les données (TEST)")
async def reset_cmd(interaction: discord.Interaction):
    """Réinitialise complètement la base de données - pour les tests uniquement"""

    class ConfirmReset(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=30)

        @discord.ui.button(label="Oui, tout effacer", style=discord.ButtonStyle.danger)
        async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
            import os

            conn = sqlite3.connect('challenge.db')
            c = conn.cursor()

            # Supprimer toutes les données
            c.execute('DELETE FROM checkins')
            c.execute('DELETE FROM history')
            c.execute('DELETE FROM challenge')

            conn.commit()
            conn.close()

            embed = discord.Embed(
                title="Base de données réinitialisée",
                description="Toutes les données ont été supprimées.",
                color=Colors.SUCCESS
            )

            await interaction.response.edit_message(embed=embed, view=None)
            self.stop()

        @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
        async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.edit_message(content="Annulé.", embed=None, view=None)
            self.stop()

    embed = discord.Embed(
        title="⚠️ Réinitialisation complète",
        description="**ATTENTION:** Cette action va supprimer **TOUTES** les données :\n\n• Tous les défis\n• Tous les check-ins\n• Tout l'historique\n\n**Cette action est irréversible.**",
        color=Colors.WARNING
    )

    await interaction.response.send_message(embed=embed, view=ConfirmReset(), ephemeral=True)


@bot.tree.command(name="test", description="Vérifier l'état du bot")
async def test_cmd(interaction: discord.Interaction):
    """Commande de test pour vérifier que le bot fonctionne"""

    challenge = get_active_challenge()

    embed = discord.Embed(
        title="Test du bot",
        color=Colors.INFO
    )

    embed.add_field(
        name="Statut",
        value="✓ Bot opérationnel" if bot.is_ready() else "✗ Bot non prêt",
        inline=False
    )

    embed.add_field(
        name="Défi actif",
        value="Oui" if challenge else "Non",
        inline=True
    )

    if challenge:
        week_number, year = get_week_info()
        checkins = get_checkins_for_week(challenge[0], week_number, year)
        embed.add_field(
            name="Check-ins cette semaine",
            value=f"User1: {checkins.get(challenge[1], 0)}\nUser2: {checkins.get(challenge[6], 0)}",
            inline=True
        )

    # Infos DB
    conn = sqlite3.connect('challenge.db')
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM checkins')
    total_checkins = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM challenge WHERE is_active = 1')
    active_challenges = c.fetchone()[0]
    conn.close()

    embed.add_field(
        name="Base de données",
        value=f"Check-ins totaux: {total_checkins}\nDéfis actifs: {active_challenges}",
        inline=False
    )

    embed.set_footer(text="Utilisez /reset pour réinitialiser les données de test")

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

    conn = sqlite3.connect('challenge.db')
    c = conn.cursor()

    total_weeks = challenge[17] if len(challenge) > 17 else 0

    if user1_failed or user2_failed:
        c.execute('UPDATE challenge SET is_active = 0 WHERE id = ?', (challenge[0],))

        if user1_failed and user2_failed:
            # Double échec
            embed = discord.Embed(
                title="Fin du défi",
                description="Les deux ont échoué.",
                color=Colors.ERROR
            )

            embed.add_field(
                name=challenge[2],
                value=f"{user1_count}/{user1_goal}\n*Gage:* {challenge[5]}",
                inline=True
            )

            embed.add_field(
                name=challenge[7],
                value=f"{user2_count}/{user2_goal}\n*Gage:* {challenge[10]}",
                inline=True
            )

            c.execute('''
                INSERT INTO history (challenge_id, winner_id, winner_name, loser_id, loser_name, loser_gage, end_date, reason, total_weeks)
                VALUES (?, NULL, NULL, NULL, 'Les deux', ?, ?, 'Double échec', ?)
            ''', (challenge[0], f"{challenge[5]} / {challenge[10]}", now.isoformat(), total_weeks))

        elif user1_failed:
            embed = discord.Embed(
                title="Fin du défi",
                description=f"**{challenge[2]}** {random.choice(Messages.LOSER).lower()}",
                color=Colors.ERROR
            )

            embed.add_field(name="Perdant", value=f"{challenge[2]}\n{user1_count}/{user1_goal}", inline=True)
            embed.add_field(name="Gagnant", value=f"{challenge[7]}\n{user2_count}/{user2_goal}", inline=True)
            embed.add_field(name="Gage", value=challenge[5], inline=False)

            c.execute('''
                INSERT INTO history (challenge_id, winner_id, winner_name, loser_id, loser_name, loser_gage, end_date, reason, total_weeks)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (challenge[0], challenge[6], challenge[7], challenge[1], challenge[2], challenge[5], now.isoformat(), 'Objectif non atteint', total_weeks))

        else:
            embed = discord.Embed(
                title="Fin du défi",
                description=f"**{challenge[7]}** {random.choice(Messages.LOSER).lower()}",
                color=Colors.ERROR
            )

            embed.add_field(name="Perdant", value=f"{challenge[7]}\n{user2_count}/{user2_goal}", inline=True)
            embed.add_field(name="Gagnant", value=f"{challenge[2]}\n{user1_count}/{user1_goal}", inline=True)
            embed.add_field(name="Gage", value=challenge[10], inline=False)

            c.execute('''
                INSERT INTO history (challenge_id, winner_id, winner_name, loser_id, loser_name, loser_gage, end_date, reason, total_weeks)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (challenge[0], challenge[1], challenge[2], challenge[6], challenge[7], challenge[10], now.isoformat(), 'Objectif non atteint', total_weeks))

        if total_weeks > 0:
            embed.set_footer(text=f"Durée: {total_weeks} semaine{'s' if total_weeks > 1 else ''}")

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

        embed = discord.Embed(
            title=f"Semaine {week_number} validée",
            color=Colors.SUCCESS
        )

        embed.add_field(name=challenge[2], value=f"Streak: {new_streak1}", inline=True)
        embed.add_field(name=challenge[7], value=f"Streak: {new_streak2}", inline=True)

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

    days = days_remaining()

    channel = bot.get_channel(challenge[11])
    if not channel:
        return

    # User 1
    user1_count = checkins.get(challenge[1], 0)
    user1_remaining = challenge[4] - user1_count

    if user1_remaining > 0:
        await channel.send(f"<@{challenge[1]}> — {user1_remaining} session{'s' if user1_remaining > 1 else ''} restante{'s' if user1_remaining > 1 else ''}, {days}j.")

    # User 2
    user2_count = checkins.get(challenge[6], 0)
    user2_remaining = challenge[9] - user2_count

    if user2_remaining > 0:
        await channel.send(f"<@{challenge[6]}> — {user2_remaining} session{'s' if user2_remaining > 1 else ''} restante{'s' if user2_remaining > 1 else ''}, {days}j.")


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
    import os
    import time
    from dotenv import load_dotenv
    load_dotenv()
    
    TOKEN = os.getenv('DISCORD_TOKEN')
    if not TOKEN:
        print("Token manquant. Crée un fichier .env avec DISCORD_TOKEN=xxx")
        exit(1)
    
    # Retry avec délai exponentiel en cas d'erreur
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

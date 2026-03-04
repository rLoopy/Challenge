"""
Test du cycle d'entraînement: 7 sessions en 9 jours

Simule le scénario complet d'un utilisateur configuré avec un cycle
personnalisé de 9 jours avec un objectif de 7 sessions.
"""

import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch, MagicMock
import sys

PARIS_TZ = ZoneInfo("Europe/Paris")


# ── Helpers extraits de bot.py (logique pure, sans DB) ──────────────

def get_cycle_days_remaining_logic(profile, now):
    """Calcul des jours restants (logique pure)"""
    cycle_days = (profile.get('cycle_days') or 7) if profile else 7
    if cycle_days == 7:
        return 6 - now.weekday()  # jours jusqu'à dimanche
    cycle_start = profile.get('cycle_start_date')
    if not cycle_start:
        return cycle_days
    start = datetime.datetime.fromisoformat(cycle_start)
    if start.tzinfo is None:
        start = start.replace(tzinfo=PARIS_TZ)
    end = start + datetime.timedelta(days=cycle_days)
    return max(0, (end - now).days)


def count_checkins_in_cycle(checkins, cycle_start_date, cycle_days):
    """Compte les check-ins dans la fenêtre du cycle (logique pure)"""
    start = datetime.datetime.fromisoformat(cycle_start_date)
    if start.tzinfo is None:
        start = start.replace(tzinfo=PARIS_TZ)
    end = start + datetime.timedelta(days=cycle_days)
    return sum(1 for ts in checkins if start <= ts < end)


def is_cycle_complete(now, cycle_start_date, cycle_days):
    """Vérifie si le cycle est terminé"""
    start = datetime.datetime.fromisoformat(cycle_start_date)
    if start.tzinfo is None:
        start = start.replace(tzinfo=PARIS_TZ)
    end = start + datetime.timedelta(days=cycle_days)
    return now >= end


def evaluate_cycle(count, cycle_goal):
    """Évalue le résultat du cycle"""
    return "success" if count >= cycle_goal else "failure"


# ── Tests ────────────────────────────────────────────────────────────

def test_setup_cycle():
    """Test: Configuration d'un cycle 7 sessions / 9 jours"""
    print("=" * 60)
    print("TEST 1: Configuration du cycle")
    print("=" * 60)

    now = datetime.datetime(2026, 3, 4, 10, 0, 0, tzinfo=PARIS_TZ)
    cycle_start = now.strftime('%Y-%m-%dT00:00:00')  # Minuit du jour

    profile = {
        'user_id': 12345,
        'user_name': 'TestUser',
        'weekly_goal': 4,
        'cycle_days': 9,
        'cycle_goal': 7,
        'cycle_start_date': cycle_start,
    }

    assert profile['cycle_days'] == 9
    assert profile['cycle_goal'] == 7
    assert profile['cycle_start_date'] == '2026-03-04T00:00:00'

    days_remaining = get_cycle_days_remaining_logic(profile, now)
    # At 10:00 on day 1: end is 9 days from midnight = 8 days 14h from now → .days = 8
    assert days_remaining == 8, f"Expected 8 days remaining at 10:00 on day 1, got {days_remaining}"

    # At midnight (cycle start), it would be 9
    days_at_start = get_cycle_days_remaining_logic(profile, datetime.datetime(2026, 3, 4, 0, 0, 0, tzinfo=PARIS_TZ))
    assert days_at_start == 9, f"Expected 9 days remaining at midnight, got {days_at_start}"

    print(f"  Cycle configuré: {profile['cycle_days']}j, objectif: {profile['cycle_goal']} sessions")
    print(f"  Début: {profile['cycle_start_date']}")
    print(f"  Fin prévue: 2026-03-13T00:00:00")
    print(f"  Jours restants à minuit: {days_at_start}, à 10h: {days_remaining}")
    print("  ✓ OK\n")


def test_progress_tracking():
    """Test: Suivi de progression jour par jour"""
    print("=" * 60)
    print("TEST 2: Progression jour par jour (7 sessions / 9 jours)")
    print("=" * 60)

    cycle_start = '2026-03-04T00:00:00'
    cycle_days = 9
    cycle_goal = 7

    profile = {
        'cycle_days': cycle_days,
        'cycle_goal': cycle_goal,
        'cycle_start_date': cycle_start,
    }

    # Simuler des check-ins: sessions aux jours 1, 2, 3, 5, 6, 7, 8 (repos jours 4 et 9)
    checkin_timestamps = [
        datetime.datetime(2026, 3, 4, 18, 30, tzinfo=PARIS_TZ),   # Jour 1 - mercredi
        datetime.datetime(2026, 3, 5, 19, 0, tzinfo=PARIS_TZ),    # Jour 2 - jeudi
        datetime.datetime(2026, 3, 6, 17, 45, tzinfo=PARIS_TZ),   # Jour 3 - vendredi
        # Jour 4 (samedi) - REPOS
        datetime.datetime(2026, 3, 8, 10, 0, tzinfo=PARIS_TZ),    # Jour 5 - dimanche
        datetime.datetime(2026, 3, 9, 20, 0, tzinfo=PARIS_TZ),    # Jour 6 - lundi
        datetime.datetime(2026, 3, 10, 18, 0, tzinfo=PARIS_TZ),   # Jour 7 - mardi
        datetime.datetime(2026, 3, 11, 7, 30, tzinfo=PARIS_TZ),   # Jour 8 - mercredi
        # Jour 9 (jeudi) - REPOS
    ]

    print(f"\n  Planning des sessions:")
    print(f"  {'Jour':<8} {'Date':<14} {'Session':<10}")
    print(f"  {'─' * 35}")

    for day_offset in range(cycle_days):
        day_date = datetime.datetime(2026, 3, 4, tzinfo=PARIS_TZ) + datetime.timedelta(days=day_offset)
        day_name = day_date.strftime('%A')
        day_num = day_offset + 1

        # Check-ins faits jusqu'à la fin de ce jour
        end_of_day = day_date + datetime.timedelta(days=1)
        count = count_checkins_in_cycle(
            [t for t in checkin_timestamps if t < end_of_day],
            cycle_start, cycle_days
        )

        has_session = any(
            day_date <= t < end_of_day
            for t in checkin_timestamps
        )

        status = "✓ Session" if has_session else "— Repos"
        days_left = get_cycle_days_remaining_logic(profile, end_of_day)

        print(f"  J{day_num:<6} {day_date.strftime('%d/%m'):<14} {status:<10} ({count}/{cycle_goal}) - {days_left}j restants")

    # Vérifier le total
    total = count_checkins_in_cycle(checkin_timestamps, cycle_start, cycle_days)
    assert total == 7, f"Expected 7 check-ins, got {total}"
    print(f"\n  Total: {total}/{cycle_goal} sessions")
    print("  ✓ OK\n")


def test_cycle_evaluation_success():
    """Test: Évaluation à minuit J10 - cycle réussi"""
    print("=" * 60)
    print("TEST 3: Évaluation du cycle - SUCCÈS (7/7)")
    print("=" * 60)

    cycle_start = '2026-03-04T00:00:00'
    cycle_days = 9
    cycle_goal = 7

    # Minuit du jour 10 = fin du cycle
    evaluation_time = datetime.datetime(2026, 3, 13, 0, 0, 0, tzinfo=PARIS_TZ)

    # Le cycle est-il terminé ?
    complete = is_cycle_complete(evaluation_time, cycle_start, cycle_days)
    assert complete, "Cycle should be complete at day 10 midnight"
    print(f"  Heure d'évaluation: {evaluation_time.strftime('%d/%m/%Y %H:%M')} (minuit)")
    print(f"  Cycle terminé: {complete}")

    # 7 sessions enregistrées
    count = 7
    result = evaluate_cycle(count, cycle_goal)
    assert result == "success"
    print(f"  Sessions: {count}/{cycle_goal}")
    print(f"  Résultat: SUCCÈS → Nouveau cycle démarre automatiquement")

    # Nouveau cycle
    new_start = evaluation_time.strftime('%Y-%m-%dT00:00:00')
    new_end = (evaluation_time + datetime.timedelta(days=cycle_days)).strftime('%d/%m/%Y')
    print(f"  Nouveau cycle: {new_start} → {new_end}")
    print("  ✓ OK\n")


def test_cycle_evaluation_failure():
    """Test: Évaluation du cycle - échec (5/7)"""
    print("=" * 60)
    print("TEST 4: Évaluation du cycle - ÉCHEC (5/7)")
    print("=" * 60)

    cycle_goal = 7
    count = 5
    result = evaluate_cycle(count, cycle_goal)
    assert result == "failure"

    print(f"  Sessions: {count}/{cycle_goal}")
    print(f"  Résultat: ÉCHEC")
    print(f"  → Éliminé des défis actifs")
    print(f"  → /rescue disponible pendant 24h")
    print(f"  → Le cycle redémarre quand même (pour le rescue)")
    print("  ✓ OK\n")


def test_days_remaining_throughout_cycle():
    """Test: Jours restants à différents moments du cycle"""
    print("=" * 60)
    print("TEST 5: Jours restants tout au long du cycle")
    print("=" * 60)

    profile = {
        'cycle_days': 9,
        'cycle_goal': 7,
        'cycle_start_date': '2026-03-04T00:00:00',
    }

    test_cases = [
        (datetime.datetime(2026, 3, 4, 0, 0, tzinfo=PARIS_TZ), 9),   # Début du cycle
        (datetime.datetime(2026, 3, 4, 23, 59, tzinfo=PARIS_TZ), 8),  # Fin jour 1
        (datetime.datetime(2026, 3, 7, 12, 0, tzinfo=PARIS_TZ), 5),   # Milieu jour 4
        (datetime.datetime(2026, 3, 10, 0, 0, tzinfo=PARIS_TZ), 3),   # Début jour 7
        (datetime.datetime(2026, 3, 12, 23, 0, tzinfo=PARIS_TZ), 0),  # Dernier jour, 23h
        (datetime.datetime(2026, 3, 13, 0, 0, tzinfo=PARIS_TZ), 0),   # Minuit = fin du cycle
    ]

    for now, expected in test_cases:
        remaining = get_cycle_days_remaining_logic(profile, now)
        assert remaining == expected, f"At {now}: expected {expected}, got {remaining}"
        print(f"  {now.strftime('%d/%m %H:%M')} → {remaining}j restants {'✓' if remaining == expected else '✗'}")

    print("  ✓ OK\n")


def test_checkins_outside_cycle_window():
    """Test: Les check-ins hors fenêtre ne comptent pas"""
    print("=" * 60)
    print("TEST 6: Check-ins hors fenêtre du cycle")
    print("=" * 60)

    cycle_start = '2026-03-04T00:00:00'
    cycle_days = 9

    checkins = [
        datetime.datetime(2026, 3, 3, 23, 59, tzinfo=PARIS_TZ),   # AVANT le cycle
        datetime.datetime(2026, 3, 5, 10, 0, tzinfo=PARIS_TZ),    # DANS le cycle
        datetime.datetime(2026, 3, 10, 18, 0, tzinfo=PARIS_TZ),   # DANS le cycle
        datetime.datetime(2026, 3, 13, 0, 0, tzinfo=PARIS_TZ),    # APRÈS le cycle (= début cycle suivant)
        datetime.datetime(2026, 3, 14, 12, 0, tzinfo=PARIS_TZ),   # APRÈS le cycle
    ]

    count = count_checkins_in_cycle(checkins, cycle_start, cycle_days)
    assert count == 2, f"Expected 2 in-window check-ins, got {count}"

    print(f"  5 check-ins total, 2 dans la fenêtre [04/03 00:00 → 13/03 00:00[")
    print(f"  - 03/03 23:59 → Hors fenêtre (avant)")
    print(f"  - 05/03 10:00 → ✓ Compté")
    print(f"  - 10/03 18:00 → ✓ Compté")
    print(f"  - 13/03 00:00 → Hors fenêtre (= début cycle suivant)")
    print(f"  - 14/03 12:00 → Hors fenêtre (après)")
    print(f"  Résultat: {count} check-ins comptés")
    print("  ✓ OK\n")


def test_multiple_checkins_same_day():
    """Test: Plusieurs check-ins le même jour"""
    print("=" * 60)
    print("TEST 7: Plusieurs check-ins le même jour")
    print("=" * 60)

    cycle_start = '2026-03-04T00:00:00'
    cycle_days = 9
    cycle_goal = 7

    # 2 check-ins le même jour
    checkins = [
        datetime.datetime(2026, 3, 5, 10, 0, tzinfo=PARIS_TZ),
        datetime.datetime(2026, 3, 5, 18, 0, tzinfo=PARIS_TZ),  # même jour !
    ]

    count = count_checkins_in_cycle(checkins, cycle_start, cycle_days)
    assert count == 2, f"Expected 2 check-ins counted, got {count}"

    print(f"  2 check-ins le 05/03 → les 2 sont comptés ({count}/7)")
    print(f"  Note: Le système compte TOUS les check-ins, pas les jours uniques")
    print(f"  C'est cohérent avec le code SQL: COUNT(*) sans DISTINCT sur date")
    print("  ✓ OK\n")


def test_full_scenario_timeline():
    """Test: Timeline complète d'un cycle 7/9"""
    print("=" * 60)
    print("TEST 8: Scénario complet - Timeline 7 sessions / 9 jours")
    print("=" * 60)

    cycle_start = '2026-03-04T00:00:00'
    cycle_days = 9
    cycle_goal = 7

    profile = {
        'cycle_days': cycle_days,
        'cycle_goal': cycle_goal,
        'cycle_start_date': cycle_start,
        'weekly_goal': 4,
    }

    print(f"""
  ┌──────────────────────────────────────────────────────────┐
  │          CYCLE: 7 sessions en 9 jours                    │
  ├──────────────────────────────────────────────────────────┤
  │                                                          │
  │  Jour 1 (04/03 mer)  ██ Session gym        [1/7]        │
  │  Jour 2 (05/03 jeu)  ██ Session gym        [2/7]        │
  │  Jour 3 (06/03 ven)  ██ Session cardio     [3/7]        │
  │  Jour 4 (07/03 sam)  ░░ Repos                           │
  │  Jour 5 (08/03 dim)  ██ Session gym        [4/7]        │
  │  Jour 6 (09/03 lun)  ██ Session gym        [5/7]        │
  │  Jour 7 (10/03 mar)  ██ Session gym        [6/7]        │
  │  Jour 8 (11/03 mer)  ██ Session cardio     [7/7] ✓      │
  │  Jour 9 (12/03 jeu)  ░░ Repos                           │
  │                                                          │
  │  13/03 00:00 → Évaluation automatique                    │
  │  Résultat: 7/7 ✓ SUCCÈS                                 │
  │  → Nouveau cycle: 13/03 → 22/03                          │
  │                                                          │
  └──────────────────────────────────────────────────────────┘
""")

    checkins = [
        datetime.datetime(2026, 3, 4, 18, 30, tzinfo=PARIS_TZ),
        datetime.datetime(2026, 3, 5, 19, 0, tzinfo=PARIS_TZ),
        datetime.datetime(2026, 3, 6, 17, 45, tzinfo=PARIS_TZ),
        datetime.datetime(2026, 3, 8, 10, 0, tzinfo=PARIS_TZ),
        datetime.datetime(2026, 3, 9, 20, 0, tzinfo=PARIS_TZ),
        datetime.datetime(2026, 3, 10, 18, 0, tzinfo=PARIS_TZ),
        datetime.datetime(2026, 3, 11, 7, 30, tzinfo=PARIS_TZ),
    ]

    count = count_checkins_in_cycle(checkins, cycle_start, cycle_days)
    assert count == 7
    assert evaluate_cycle(count, cycle_goal) == "success"

    eval_time = datetime.datetime(2026, 3, 13, 0, 0, tzinfo=PARIS_TZ)
    assert is_cycle_complete(eval_time, cycle_start, cycle_days)

    # Nouveau cycle
    new_start = eval_time.strftime('%Y-%m-%dT00:00:00')
    new_end = eval_time + datetime.timedelta(days=cycle_days)

    profile['cycle_start_date'] = new_start
    remaining = get_cycle_days_remaining_logic(profile, eval_time)
    assert remaining == 9, f"New cycle should have 9 days remaining, got {remaining}"

    print(f"  Cycle 1: {cycle_start} → 13/03 00:00 → 7/7 SUCCÈS")
    print(f"  Cycle 2: {new_start} → {new_end.strftime('%d/%m')} 00:00 → En cours...")
    print("  ✓ OK\n")


def test_cross_week_boundary():
    """Test: Le cycle traverse les frontières de semaine ISO"""
    print("=" * 60)
    print("TEST 9: Cycle qui traverse la frontière de semaine")
    print("=" * 60)

    # Cycle de 9 jours à partir du mercredi
    # Traverse 2 semaines ISO (sem 10 et sem 11)
    cycle_start = '2026-03-04T00:00:00'  # mercredi sem 10
    cycle_days = 9
    # Fin: 13/03 = vendredi sem 11

    checkins = [
        # Semaine ISO 10 (lun 02/03 → dim 08/03)
        datetime.datetime(2026, 3, 4, 18, 0, tzinfo=PARIS_TZ),   # mer sem 10
        datetime.datetime(2026, 3, 5, 18, 0, tzinfo=PARIS_TZ),   # jeu sem 10
        datetime.datetime(2026, 3, 6, 18, 0, tzinfo=PARIS_TZ),   # ven sem 10
        datetime.datetime(2026, 3, 8, 18, 0, tzinfo=PARIS_TZ),   # dim sem 10
        # Semaine ISO 11 (lun 09/03 → dim 15/03)
        datetime.datetime(2026, 3, 9, 18, 0, tzinfo=PARIS_TZ),   # lun sem 11
        datetime.datetime(2026, 3, 10, 18, 0, tzinfo=PARIS_TZ),  # mar sem 11
        datetime.datetime(2026, 3, 11, 18, 0, tzinfo=PARIS_TZ),  # mer sem 11
    ]

    count = count_checkins_in_cycle(checkins, cycle_start, cycle_days)
    assert count == 7

    print(f"  Le cycle 9j traverse 2 semaines ISO:")
    print(f"  Sem 10: 4 sessions (mer→dim)")
    print(f"  Sem 11: 3 sessions (lun→mer)")
    print(f"  Total cycle: {count}/7 ✓")
    print(f"")
    print(f"  Avantage du mode cycle vs semaine:")
    print(f"  - Mode semaine: 4/4 sem 10 ✓, puis 3/4 sem 11 ✗ → ÉCHEC")
    print(f"  - Mode cycle 9j: 7/7 sur le cycle complet → SUCCÈS")
    print("  ✓ OK\n")


if __name__ == '__main__':
    print("\n" + "═" * 60)
    print("  TEST DU CYCLE D'ENTRAÎNEMENT: 7 sessions / 9 jours")
    print("═" * 60 + "\n")

    test_setup_cycle()
    test_progress_tracking()
    test_cycle_evaluation_success()
    test_cycle_evaluation_failure()
    test_days_remaining_throughout_cycle()
    test_checkins_outside_cycle_window()
    test_multiple_checkins_same_day()
    test_full_scenario_timeline()
    test_cross_week_boundary()

    print("═" * 60)
    print("  TOUS LES TESTS PASSENT ✓")
    print("═" * 60)

"""Logika grafiku (bez Streamlita): baza SQLite, święta, rotacja zmian."""
import sqlite3
from datetime import date, timedelta
from pathlib import Path

DB_PATH = Path(__file__).with_name("grafik.db")

# kod: (opis, kolor tła). Dodaj tu własne kody, np. "UB": ("Urlop bezpłatny", "#ccc")
CODES = {
    "8":    ("Praca (8h)", "#ffffff"),
    "W":    ("Wolne", "#d9d9d9"),
    "Uw":   ("Urlop wypoczynkowy", "#a8d5ff"),
    "UŻ":   ("Urlop na żądanie", "#7fc4ff"),
    "L4":   ("Chorobowe", "#ffb3b3"),
    "WS":   ("WS", "#ffe08a"),
    "Op":   ("Opieka", "#d8c2f0"),
    "Szk":  ("Szkolenie", "#b9e6b0"),
    "Krew": ("Krwiodawstwo", "#f7a8c8"),
    "Biuro": ("Biuro", "#e3f1e0"),
    "Inne": ("Inne wolne", "#f5d0a9"),
}
DNI = ["Pn", "Wt", "Śr", "Cz", "Pt", "So", "N"]
MIESIACE = ["Styczeń", "Luty", "Marzec", "Kwiecień", "Maj", "Czerwiec", "Lipiec",
            "Sierpień", "Wrzesień", "Październik", "Listopad", "Grudzień"]

# (nazwa, rotacyjny?, zmiana w tygodniu kotwicy, liczba pracowników na start)
SEED_TEAMS = [
    ("ZMIANA A", 1, 1, 10), ("ZMIANA B", 1, 2, 9), ("ZMIANA C", 1, 3, 10),
    ("Korespondent P", 0, 1, 1), ("Naprawa opon", 0, 1, 1), ("Jednozmianowi", 0, 1, 1),
]
ANCHOR_MONDAY = "2026-11-30"  # tydzień 30.11–6.12.2026: A=1, B=2, C=3


def conn():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def q(sql, args=(), commit=False):
    c = conn()
    try:
        cur = c.execute(sql, args)
        if commit:
            c.commit()
            return cur.lastrowid
        return [dict(r) for r in cur.fetchall()]
    finally:
        c.close()


def init_db():
    c = conn()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS teams(
        name TEXT PRIMARY KEY, sort INTEGER, rotating INTEGER,
        anchor_monday TEXT, anchor_shift INTEGER);
    CREATE TABLE IF NOT EXISTS employees(
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, team TEXT, pin TEXT DEFAULT '');
    CREATE TABLE IF NOT EXISTS entries(
        employee_id INTEGER, day TEXT, code TEXT, PRIMARY KEY(employee_id, day));
    """)
    if not c.execute("SELECT 1 FROM teams").fetchone():
        for i, (name, rot, shift, n) in enumerate(SEED_TEAMS):
            c.execute("INSERT INTO teams VALUES(?,?,?,?,?)", (name, i, rot, ANCHOR_MONDAY, shift))
            prefix = name.replace("ZMIANA ", "")
            for k in range(1, n + 1):
                c.execute("INSERT INTO employees(name,team) VALUES(?,?)",
                          (f"Pracownik {prefix} {k}", name))
    c.commit()
    c.close()


def easter(y):
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(y, month, day + 1)


def holidays(y):
    e = easter(y)
    s = {date(y, 1, 1), date(y, 1, 6), e, e + timedelta(1), date(y, 5, 1), date(y, 5, 3),
         e + timedelta(49), e + timedelta(60), date(y, 8, 15), date(y, 11, 1),
         date(y, 11, 11), date(y, 12, 25), date(y, 12, 26)}
    if y >= 2025:
        s.add(date(y, 12, 24))  # Wigilia wolna od 2025
    return s


def is_workday(d, hol):
    return d.weekday() < 5 and d not in hol


def shift_for(team, d):
    """Numer zmiany zespołu w danym dniu (rotacja co tydzień: 1→3→2→1...)."""
    anchor = date.fromisoformat(team["anchor_monday"])
    if not team["rotating"]:
        return team["anchor_shift"]
    monday = d - timedelta(days=d.weekday())
    weeks = (monday - anchor).days // 7
    return (team["anchor_shift"] - 1 - weeks) % 3 + 1


def default_code(d, hol):
    return "8" if is_workday(d, hol) else "W"

import calendar
import html
import io
import os
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from core import (CODES, DNI, MIESIACE, default_code, holidays, init_db,
                  is_workday, q, shift_for)

ADMIN_PASSWORD = os.environ.get("GRAFIK_ADMIN", "admin123")  # ZMIEŃ!
SHIFT_COLORS = {1: "#fff2b3", 2: "#ffd6a5", 3: "#c9d8ff"}

st.set_page_config(page_title="Grafik zmian", layout="wide")
init_db()

st.markdown("""
<style>
.grid-wrap{overflow-x:auto;border:1px solid #bbb}
table.grid{border-collapse:collapse;font-size:12px;color:#111;background:#fff}
table.grid th,table.grid td{border:1px solid #c8c8c8;padding:3px 5px;text-align:center;min-width:26px;color:#111}
table.grid th.name,table.grid td.name{position:sticky;left:0;z-index:2;text-align:left;
  min-width:190px;background:#f4f4f4;font-weight:600;white-space:nowrap}
table.grid tr.team td{font-weight:700;background:#e9e9e9}
table.grid tr.me td.name{background:#fff3a0}
table.grid th{background:#dcdcdc}
table.grid th.we{background:#b8b8b8}
table.grid th.today{outline:2px solid #d33;outline-offset:-2px}
</style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------------ dane
def teams():
    return q("SELECT * FROM teams ORDER BY sort")

def employees():
    return q("""SELECT e.id,e.name,e.team,e.pin FROM employees e
                 JOIN teams t ON t.name=e.team ORDER BY t.sort,e.id""")

def month_entries(first, last):
    rows = q("SELECT employee_id,day,code FROM entries WHERE day BETWEEN ? AND ?",
             (first.isoformat(), last.isoformat()))
    return {(r["employee_id"], r["day"]): r["code"] for r in rows}

def cell(entries, emp_id, d, hol):
    return entries.get((emp_id, d.isoformat())) or default_code(d, hol)

# ------------------------------------------------------------------ sidebar
today = date.today()
with st.sidebar:
    st.header("📅 Grafik zmian")
    year = st.number_input("Rok", 2024, 2035, today.year, step=1)
    month = st.selectbox("Miesiąc", range(1, 13), index=today.month - 1,
                         format_func=lambda m: MIESIACE[m - 1])

    st.divider()
    emps = employees()
    labels = {e["id"]: f'{e["name"]} ({e["team"]})' for e in emps}
    me_id = st.selectbox("Kim jestem", list(labels), format_func=labels.get) if emps else None
    me = next((e for e in emps if e["id"] == me_id), None)

    is_admin = st.session_state.get("admin", False)
    authed = False
    if me:
        if me["pin"] and not is_admin:
            authed = st.text_input("PIN", type="password") == me["pin"]
        else:
            authed = True

    with st.expander("🔐 Administrator"):
        if is_admin:
            st.success("Zalogowano jako administrator")
            if st.button("Wyloguj"):
                st.session_state.admin = False
                st.rerun()
        else:
            pw = st.text_input("Hasło", type="password", key="adm_pw")
            if st.button("Zaloguj") and pw == ADMIN_PASSWORD:
                st.session_state.admin = True
                st.rerun()

    st.divider()
    st.caption("Legenda")
    for k, (desc, color) in CODES.items():
        st.markdown(f'<span style="background:{color};color:#111;padding:1px 8px;'
                    f'border:1px solid #999;font-size:12px"><b>{k}</b></span> {desc}',
                    unsafe_allow_html=True)

first = date(int(year), month, 1)
last = date(int(year), month, calendar.monthrange(int(year), month)[1])
days = [first + timedelta(i) for i in range((last - first).days + 1)]
hol = holidays(int(year))

# ------------------------------------------------------------------ widok grafiku
def render_grid(me_id):
    entries = month_entries(first, last)
    out = ['<div class="grid-wrap"><table class="grid"><thead><tr>',
           f'<th class="name">{MIESIACE[month-1].upper()} {year}</th>']
    for d in days:
        cls = "we" if not is_workday(d, hol) else ""
        cls += " today" if d == today else ""
        out.append(f'<th class="{cls}">{d.day}<br>{DNI[d.weekday()]}</th>')
    out.append("</tr></thead><tbody>")
    for t in teams():
        out.append(f'<tr class="team"><td class="name">{html.escape(t["name"])}</td>')
        for d in days:
            if is_workday(d, hol):
                s = shift_for(t, d)
                out.append(f'<td style="background:{SHIFT_COLORS[s]}">{s}</td>')
            else:
                out.append('<td style="background:#d9d9d9">W</td>')
        out.append("</tr>")
        for e in [x for x in emps if x["team"] == t["name"]]:
            out.append(f'<tr class="{"me" if e["id"] == me_id else ""}">'
                       f'<td class="name">{html.escape(e["name"])}</td>')
            for d in days:
                c = cell(entries, e["id"], d, hol)
                bg = CODES.get(c, ("", "#fff"))[1]
                out.append(f'<td style="background:{bg}">{html.escape(c)}</td>')
            out.append("</tr>")
    out.append("</tbody></table></div>")
    st.markdown("".join(out), unsafe_allow_html=True)

    # eksport do Excela
    rows = []
    for e in emps:
        r = {"Zespół": e["team"], "Pracownik": e["name"]}
        r.update({str(d.day): cell(entries, e["id"], d, hol) for d in days})
        rows.append(r)
    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, index=False, sheet_name=MIESIACE[month - 1])
    st.download_button("⬇️ Pobierz miesiąc do Excela", buf.getvalue(),
                       file_name=f"grafik_{year}_{month:02d}.xlsx")

# ------------------------------------------------------------------ zapis nieobecności
def save_range(emp_id, code, d1, d2):
    n = 0
    d = d1
    while d <= d2:
        # nieobecności tylko w dni robocze; "8" i "W" można wpisać w każdy dzień
        if code in ("8", "W") or is_workday(d, holidays(d.year)):
            q("INSERT OR REPLACE INTO entries VALUES(?,?,?)",
              (emp_id, d.isoformat(), code), commit=True)
            n += 1
        d += timedelta(1)
    return n

def clear_range(emp_id, d1, d2):
    q("DELETE FROM entries WHERE employee_id=? AND day BETWEEN ? AND ?",
      (emp_id, d1.isoformat(), d2.isoformat()), commit=True)

def my_tab():
    if not me:
        st.info("Dodaj pracowników w zakładce Administracja.")
        return
    if not authed:
        st.warning("Podaj poprawny PIN w panelu bocznym.")
        return
    target_id = me_id
    if is_admin:
        target_id = st.selectbox("Pracownik (admin)", list(labels), format_func=labels.get,
                                 index=list(labels).index(me_id))
    st.subheader(f"Wpisz nieobecność: {labels[target_id]}")
    c1, c2 = st.columns([1, 2])
    code = c1.selectbox("Rodzaj", [k for k in CODES if k != "8"],
                        format_func=lambda k: f"{k} – {CODES[k][0]}")
    rng = c2.date_input("Od – do", value=(first, first), format="DD.MM.YYYY")
    b1, b2, _ = st.columns([1, 1, 3])
    if len(rng) == 2:
        d1, d2 = rng
        if b1.button("💾 Zapisz", type="primary"):
            n = save_range(target_id, code, d1, d2)
            st.success(f"Zapisano {n} dni.")
            st.rerun()
        if b2.button("↩️ Przywróć 8 / W"):
            clear_range(target_id, d1, d2)
            st.rerun()
    else:
        st.caption("Wybierz datę końcową.")

    st.markdown("**Moje wpisy (od dzisiaj)**")
    rows = q("SELECT day,code FROM entries WHERE employee_id=? AND day>=? ORDER BY day",
             (target_id, today.isoformat()))
    if rows:
        df = pd.DataFrame(rows)
        df["day"] = pd.to_datetime(df["day"]).dt.strftime("%d.%m.%Y")
        df["code"] = df["code"].map(lambda c: f"{c} – {CODES.get(c, ('',))[0]}")
        st.dataframe(df.rename(columns={"day": "Data", "code": "Wpis"}),
                     hide_index=True, use_container_width=True)
    else:
        st.caption("Brak wpisów.")

# ------------------------------------------------------------------ administracja
def admin_tab():
    if not is_admin:
        st.warning("Zaloguj się jako administrator w panelu bocznym.")
        return
    st.subheader("Pracownicy")
    tnames = [t["name"] for t in teams()]
    df = pd.DataFrame(employees()).rename(columns={"name": "Imię i nazwisko",
                                                   "team": "Zespół", "pin": "PIN"})
    edited = st.data_editor(
        df, num_rows="dynamic", hide_index=True, use_container_width=True,
        column_config={"id": None, "Zespół": st.column_config.SelectboxColumn(options=tnames),
                       "PIN": st.column_config.TextColumn(help="Opcjonalny, pusty = bez PIN-u")})
    if st.button("💾 Zapisz pracowników", type="primary"):
        present = set()
        for _, r in edited.iterrows():
            name = str(r["Imię i nazwisko"] or "").strip()
            if not name or pd.isna(r["Zespół"]):
                continue
            pin = "" if pd.isna(r["PIN"]) else str(r["PIN"])
            if pd.isna(r["id"]):
                q("INSERT INTO employees(name,team,pin) VALUES(?,?,?)",
                  (name, r["Zespół"], pin), commit=True)
            else:
                present.add(int(r["id"]))
                q("UPDATE employees SET name=?,team=?,pin=? WHERE id=?",
                  (name, r["Zespół"], pin, int(r["id"])), commit=True)
        for e in employees():
            if e["id"] not in present and e["id"] in set(df["id"]):
                q("DELETE FROM employees WHERE id=?", (e["id"],), commit=True)
                q("DELETE FROM entries WHERE employee_id=?", (e["id"],), commit=True)
        st.rerun()

    st.subheader("Rotacja zmian")
    st.caption("Zmiana zespołu w tygodniu rozpoczynającym się w podanym poniedziałku. "
               "Kolejne tygodnie: 1 → 3 → 2 → 1…")
    tdf = pd.DataFrame(teams())[["name", "rotating", "anchor_monday", "anchor_shift"]]
    tdf["anchor_monday"] = pd.to_datetime(tdf["anchor_monday"]).dt.date
    tdf["rotating"] = tdf["rotating"].astype(bool)
    tedit = st.data_editor(tdf, hide_index=True, use_container_width=True, disabled=["name"],
                           column_config={"name": "Zespół", "rotating": "Rotacyjny",
                                          "anchor_monday": st.column_config.DateColumn("Poniedziałek kotwicy"),
                                          "anchor_shift": st.column_config.NumberColumn("Zmiana", min_value=1, max_value=3)})
    if st.button("💾 Zapisz rotację"):
        for _, r in tedit.iterrows():
            q("UPDATE teams SET rotating=?,anchor_monday=?,anchor_shift=? WHERE name=?",
              (int(r["rotating"]), r["anchor_monday"].isoformat(), int(r["anchor_shift"]), r["name"]),
              commit=True)
        st.rerun()

tab1, tab2, tab3 = st.tabs(["📋 Grafik", "🏖️ Moje nieobecności", "⚙️ Administracja"])
with tab1:
    render_grid(me_id)
with tab2:
    my_tab()
with tab3:
    admin_tab()

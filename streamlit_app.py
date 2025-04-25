# -*- coding: utf-8 -*-
"""
streamlit_app.py – Dashboard CHOPS v2.4
Look iOS-like (clair, cards, coins arrondis).
"""

from __future__ import annotations
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict, List

import altair as alt
import numpy as np
import pandas as pd
import pytz
import streamlit as st
import textwrap

import firebase_admin
from firebase_admin import credentials, firestore, storage

# ─────────────────────────────────────────────────────────────
# PAGE CONFIG
st.set_page_config(
    page_title="Dashboard CHOPS",
    page_icon="🏓",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────
# STYLE GLOBAL + table Membres
st.markdown(
    """
<style>
/* ========== GLOBAL iOS-LIKE ========== */
html, body, .stApp { background:#f2f2f7 !important; }

/* Sidebar */
section[data-testid="stSidebar"] > div:first-child {
    background:#fff; border-right:1px solid #e6e6e6;
}
section[data-testid="stSidebar"] .st-emotion-cache-1wv5z7h,
section[data-testid="stSidebar"] .st-emotion-cache-75m8jr {
    color:#007aff !important;
}

/* Cards métriques */
.metric-card{background:#fff;border:1px solid #e5e5e5;border-radius:12px;
padding:1rem;text-align:center;box-shadow:0 2px 6px rgba(0,0,0,.04);}
.metric-label{font-size:.9rem;font-weight:600;color:#6b7280;}
.metric-value{font-size:1.6rem;font-weight:700;color:#1c1c1e;margin-top:.25rem;}
.metric-delta{font-size:.8rem;}
.metric-delta.up{color:#22c55e;} .metric-delta.down{color:#ef4444;}

/* Titres h2 */
h2{margin-top:2.5rem;font-weight:700;}

/* Graphs */
.stPlotlyChart,.stAltairChart,.st-vega-lite{
background:#fff;padding:1rem;border-radius:12px;
box-shadow:0 2px 6px rgba(0,0,0,.04);}
    
/* ===== TABLE MEMBRES ===== */
.member-table{width:100%;border-collapse:collapse;font-family:Arial,sans-serif;}
.member-table th{background:#007aff;color:#fff;padding:10px;text-align:left;}
.member-table td{padding:8px;border-bottom:1px solid #e0e0e0;vertical-align:middle;}
.member-table tr:hover{background:#f5f5f5;transition:background .15s;}
.avatar{width:40px;height:40px;border-radius:50%;object-fit:cover;margin-right:8px;vertical-align:middle;}
.badge{display:inline-block;padding:3px 6px;border-radius:4px;color:#fff;font-size:12px;margin-left:6px;}
.badge-admin{background:#16a34a;}.badge-coach{background:#ff9f0a;}
.badge-paid{background:#30d158;}.badge-pend{background:#eab308;}
.card-link{text-decoration:none;font-size:18px;margin-left:8px;}
</style>
""",
    unsafe_allow_html=True,
)
# ─────────────────────────────────────────────────────────────

# ╭────────── AUTH ──────────╮
if "auth" not in st.session_state:
    if st.text_input("🔑 Mot de passe", type="password") != st.secrets.get("dashboard_pwd", ""):
        st.stop()
    st.session_state.auth = True

# ╭────────── FIREBASE INIT ──────────╮
if not firebase_admin._apps:
    fb_conf = dict(st.secrets["firebase"])
    firebase_admin.initialize_app(
        credentials.Certificate(fb_conf),
        {"storageBucket": f"{fb_conf['project_id']}.appspot.com"},
    )

db = firestore.client()
_bucket = storage.bucket()

# ╭────────── UTILS ──────────╮
DEFAULT_AVATAR = (
    "https://firebasestorage.googleapis.com/v0/b/chops-app-9b80c.appspot.com/o/"
    "profile_picture%2Favatar-defaut-chops.jpg?alt=media"
)


def signed_url(path: str | None) -> str:
    if not path:
        return DEFAULT_AVATAR
    if path.startswith("http"):
        return path
    return _bucket.blob(path.lstrip("/")).generate_signed_url(expiration=3600)


def iso_date(ts) -> str:
    if ts is None or pd.isna(ts):
        return ""
    if isinstance(ts, (int, float)):
        ts = datetime.fromtimestamp(ts, tz=timezone.utc)
    elif hasattr(ts, "to_datetime"):
        ts = ts.to_datetime()
    return ts.strftime("%d/%m/%Y") if isinstance(ts, datetime) else str(ts)


@st.cache_data(show_spinner=True)
def load_col(path: str) -> pd.DataFrame:
    return pd.json_normalize([d.to_dict() | {"id": d.id} for d in db.collection(path).stream()])


def load_children(users_df: pd.DataFrame) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for uid in users_df["id"]:
        for d in db.collection(f"users/{uid}/children").stream():
            rows.append(d.to_dict() | {"childId": d.id, "parentUid": uid})
    return pd.json_normalize(rows)


def load_subrows(users_df: pd.DataFrame, sub: str) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for uid in users_df["id"]:
        for d in db.collection(f"users/{uid}/{sub}").stream():
            rows.append(d.to_dict() | {"uid": uid, "docId": d.id})
    return pd.json_normalize(rows)


@st.cache_data(show_spinner=True)
def load_all() -> Dict[str, pd.DataFrame]:
    users = load_col("users")
    children = load_children(users)
    purchases = load_col("purchases")
    sessions = load_col("sessionConfigs")
    levels = load_col("levels")

    trainings = pd.json_normalize(
        [
            d.to_dict() | {"id": d.id, "level": lvl}
            for lvl in levels["id"]
            for d in db.collection(f"levels/{lvl}/trainings").stream()
        ]
    )

    exceedances = load_subrows(users, "exceedances")
    inscriptions = load_subrows(users, "inscriptions")
    participations = load_subrows(users, "participations")

    return dict(
        users=users,
        children=children,
        purchases=purchases,
        sessions=sessions,
        levels=levels,
        trainings=trainings,
        exceedances=exceedances,
        inscriptions=inscriptions,
        participations=participations,
    )


data = load_all()

# ╭────────── MEMBRES DF ──────────╮
@lru_cache(maxsize=1)
def build_members_df() -> pd.DataFrame:
    users, children = data["users"].copy(), data["children"].copy()
    purchases = data["purchases"].copy()
    sessions = data["sessions"].set_index("id")

    users["type"], users["parentUid"] = "parent", users["id"]

    if not children.empty:
        children["type"] = "child"
        children.rename(
            columns=dict(
                childId="id",
                firstName="first_name",
                lastName="last_name",
                birthDate="birth_date",
                photoUrl="image_url",
            ),
            inplace=True,
        )
        for col in users.columns:
            if col not in children.columns:
                children[col] = None

    members = pd.concat([users, children], ignore_index=True, sort=False)

    if not purchases.empty:
        if "createdAt._seconds" in purchases:
            purchases.sort_values("createdAt._seconds", ascending=False, inplace=True)
        purchases["_k"] = purchases["userId"] + "_" + purchases["childId"].fillna("")
        firsts = purchases.drop_duplicates("_k")
        members["_k"] = members["parentUid"] + "_" + members["id"].where(
            members["type"] == "child", ""
        )
        members = members.merge(firsts, on="_k", how="left", suffixes=("", "_p")).drop(columns="_k")

    members["full_name"] = (
        members["first_name"].fillna("") + " " + members["last_name"].fillna("")
    ).str.strip()
    members["avatar"] = members["image_url"].apply(signed_url)

    if not sessions.empty and "sessionId" in members:
        end_dt = pd.to_datetime(
            members["sessionId"].map(sessions["endDate"]), errors="coerce", utc=True
        )
        today = pd.Timestamp.now(tz=pytz.UTC)
        members["days_left"] = (end_dt - today).dt.days
        members["session_name"] = members["sessionId"].map(sessions["name"])

    return members


members_df = build_members_df()

# ╭────────── SIDEBAR & MENU ──────────╮
menu = st.sidebar.radio(
    "Navigation",
    ["Dashboard", "Membres", "Présences & Excédences", "Achats", "Sessions & Niveaux"],
)

# ╭────────── helper metric card ──────────╮
def metric_card(col, label, value, delta, positive=True):
    arrow = "▲" if positive else "▼"
    cls = "up" if positive else "down"
    col.markdown(
        f"""
<div class="metric-card">
  <div class="metric-label">{label}</div>
  <div class="metric-value">{value}</div>
  <div class="metric-delta {cls}">{arrow} {delta}</div>
</div>
""",
        unsafe_allow_html=True,
    )


# ╭────────────────── DASHBOARD ──────────────────╮
if menu == "Dashboard":
    st.header("Dashboard")

    # -- métriques
    c1, c2, c3, c4, c5 = st.columns(5, gap="small")
    metric_card(c1, "Documents", "10.5 K", "+125", True)
    metric_card(c2, "Annotations", "510", "−2", False)
    metric_card(c3, "Accuracy", "87.9 %", "+0.1 %", True)
    metric_card(c4, "Training Time", "1.5 h", "+10 m", False)
    metric_card(c5, "Processing Time", "3 s", "−0.1 s", True)

    # -- charts démo ------------------------------------
    st.subheader("Data Extraction")
    df_line = pd.DataFrame(
        {"x": np.arange(20), "a": np.random.randn(20).cumsum(), "b": np.random.randn(20).cumsum()}
    )
    chart1 = (
        alt.Chart(df_line)
        .transform_fold(["a", "b"])
        .mark_line()
        .encode(x="x:Q", y="value:Q", color="key:N")
    )
    st.altair_chart(chart1, use_container_width=True)

    st.subheader("Model Training")
    df_bar = pd.DataFrame(np.random.randn(20, 2), columns=["pos", "neg"])
    chart2 = (
        alt.Chart(df_bar.reset_index())
        .transform_fold(["pos", "neg"])
        .mark_bar()
        .encode(x="index:O", y="value:Q", color="key:N")
    )
    st.altair_chart(chart2, use_container_width=True)

    st.subheader("Data Annotation")
    df_area = pd.DataFrame(np.random.randn(20, 2), columns=["x", "y"])
    chart3 = (
        alt.Chart(df_area.reset_index())
        .transform_fold(["x", "y"])
        .mark_area(opacity=0.5)
        .encode(x="index:Q", y="value:Q", color="key:N")
    )
    st.altair_chart(chart3, use_container_width=True)

# ╭────────────────── MEMBRES ──────────────────╮
elif menu == "Membres":
    st.header("👥 Member Management")

    with st.sidebar:
        st.subheader("Filters")
        f_type = st.multiselect(
            "Type",
            ["parent", "child"],
            default=["parent", "child"],
            format_func=lambda x: {"parent": "👨‍👩‍👧 Parent", "child": "👶 Child"}[x],
        )
        query = st.text_input("Search name/email…")

    df = members_df[members_df["type"].isin(f_type)].copy()
    if query:
        df = df[
            df["full_name"].str.contains(query, case=False, na=False)
            | df["email"].str.contains(query, case=False, na=False)
        ]

    rows: List[str] = []
    for _, r in df.iterrows():
        badges = ""
        if r.get("isAdmin"):
            badges += '<span class="badge badge-admin">ADMIN</span>'
        if r.get("isCoach"):
            badges += '<span class="badge badge-coach">COACH</span>'
        if r.status == "paid":
            badges += '<span class="badge badge-paid">✅ Paid</span>'
        elif r.status == "pending":
            badges += '<span class="badge badge-pend">⏱ Pending</span>'

        avatar_html = f'<img src="{r.avatar}" class="avatar"/>'
        name_html = f"{avatar_html}{r.full_name}{badges}"

        card_html = (
            f'<a href="{r.studentCardUrl}" target="_blank" class="card-link">📇</a>'
            if getattr(r, "studentCardUrl", None)
            else ""
        )

        type_emoji = "👶" if r.type == "child" else "👨‍👩‍👧"
        rows.append(
            textwrap.dedent(
                f"""\
<tr>
  <td>{name_html}</td>
  <td>{type_emoji} {r.type.title()}</td>
  <td>{r.email or '—'}</td>
  <td>{r.phone_number or '—'}</td>
  <td>{r.address or '—'}</td>
  <td>{r.birth_date or '—'}</td>
  <td>{r.session_name or '—'}</td>
  <td style="text-align:center;">{r.days_left if pd.notna(r.days_left) else '—'}</td>
  <td style="text-align:center;">{card_html}</td>
</tr>
"""
            )
        )

    header = textwrap.dedent(
        """\
<thead>
<tr>
  <th>👤 Name</th><th>🏷 Type</th><th>✉️ Email</th><th>📞 Phone</th>
  <th>🏠 Address</th><th>🎂 Birth</th><th>📅 Session</th>
  <th>⏳ Days Left</th><th>📇 Card</th>
</tr>
</thead>
"""
    )

    html = (
        "<div style='overflow-x:auto;'>"
        "<table class='member-table'>"
        + header
        + "<tbody>"
        + "\n".join(rows)
        + "</tbody></table></div>"
    )
    st.markdown(html, unsafe_allow_html=True)

# ╭────────────────── PRÉSENCES & EXCÉDENCES ──────────────────╮
elif menu == "Présences & Excédences":
    st.header("📅 Présences & excédences")

    ex_df = data["exceedances"].copy()
    ins_df = data["inscriptions"].copy()
    par_df = data["participations"].copy()

    if ex_df.empty and ins_df.empty and par_df.empty:
        st.info("Aucune donnée de présence / excédence.")
    else:
        if not ex_df.empty:
            ex_df["date"] = pd.to_datetime(ex_df["exceedAt"], errors="coerce").apply(iso_date)
            ex_df.rename(
                columns=dict(
                    uid="Utilisateur",
                    courseTitle="Cours",
                    alreadyCount="Déjà fait",
                    limitAuthorized="Quota",
                    date="Date",
                ),
                inplace=True,
            )
            st.subheader("Excédences")
            st.dataframe(
                ex_df[["Utilisateur", "Cours", "Déjà fait", "Quota", "Date"]],
                use_container_width=True,
            )

        if not ins_df.empty:
            ins_df["date"] = pd.to_datetime(ins_df["date"], errors="coerce").apply(iso_date)
            st.subheader("Inscriptions récentes")
            st.dataframe(
                ins_df[["uid", "training_uid", "type_utilisateur", "date"]]
                .sort_values("date", ascending=False),
                use_container_width=True,
            )

        if not par_df.empty:
            par_df["date"] = pd.to_datetime(par_df["date"], errors="coerce").apply(iso_date)
            st.subheader("Participations")
            st.dataframe(
                par_df[["uid", "training_uid", "type_utilisateur", "date"]]
                .sort_values("date", ascending=False),
                use_container_width=True,
            )

# ╭────────────────── ACHATS ──────────────────╮
elif menu == "Achats":
    st.header("💳 Achats & paiements")

    pur_df = data["purchases"].copy()
    if pur_df.empty:
        st.info("Collection purchases vide")
    else:
        if "createdAt._seconds" in pur_df:
            pur_df["date"] = pd.to_datetime(pur_df["createdAt._seconds"], unit="s")
        elif "createdAt" in pur_df:
            pur_df["date"] = pd.to_datetime(pur_df["createdAt"], errors="coerce")
        else:
            pur_df["date"] = pd.NaT

        cols = [
            c
            for c in [
                "id",
                "userId",
                "childId",
                "membershipId",
                "sessionId",
                "paymentMethod",
                "status",
                "finalAmount",
                "promoCode",
                "date",
            ]
            if c in pur_df
        ]
        st.dataframe(
            pur_df[cols].sort_values("date", ascending=False), use_container_width=True
        )

        if "status" in pur_df:
            pcount = pur_df["status"].fillna("None").value_counts().reset_index()
            pcount.columns = ["status", "count"]
            st.altair_chart(
                alt.Chart(pcount)
                .mark_arc(innerRadius=60)
                .encode(theta="count", color="status", tooltip=["status", "count"]),
                use_container_width=True,
            )

# ╭────────────────── SESSIONS & NIVEAUX ──────────────────╮
else:
    st.header("🗂 Sessions & Niveaux")

    st.subheader("Sessions")
    st.dataframe(
        data["sessions"]
        if not data["sessions"].empty
        else pd.DataFrame(["Aucune session"]),
        use_container_width=True,
    )

    st.markdown("---")
    st.subheader("Niveaux & trainings")
    trainings = data["trainings"]
    if trainings.empty:
        st.info("Aucun training défini.")
    else:
        st.dataframe(
            trainings.sort_values(["level", "day_of_week", "start_time"]),
            use_container_width=True,
        )

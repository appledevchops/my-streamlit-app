# -*- coding: utf-8 -*-
"""
streamlit_app.py – Dashboard CHOPS v2.3.4
• Corrects HTML indentation so the member list renders as a single table, no code block.
"""

from __future__ import annotations
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict, List

import altair as alt
import pandas as pd
import pytz
import streamlit as st

import textwrap  # NEW: used to strip indentation from multiline HTML strings

import firebase_admin
from firebase_admin import credentials, firestore, storage

# ─────────────────────────────────────────────────────────────
# 1) Page configuration (must be the first Streamlit command)
st.set_page_config(
    page_title="Dashboard CHOPS",
    page_icon="🏓",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 2) CSS for styled members table
st.markdown(
    """
<style>
.member-table { width:100%; border-collapse:collapse; font-family:Arial, sans-serif; }
.member-table th { background:#1B998B; color:#fff; padding:10px; text-align:left; }
.member-table td { padding:8px; border-bottom:1px solid #e0e0e0; vertical-align:middle; }
.member-table tr:hover { background:#f5f5f5; }
.avatar { width:40px; height:40px; border-radius:50%; object-fit:cover; margin-right:8px; vertical-align:middle; }
.badge { display:inline-block; padding:3px 6px; border-radius:4px; color:#fff; font-size:12px; margin-left:6px; }
.badge-admin  { background:#1B998B; }
.badge-coach  { background:#F97316; }
.badge-paid   { background:#3B82F6; }
.badge-pend   { background:#EAB308; }
.card-link { text-decoration:none; font-size:18px; margin-left:8px; }
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
    """Returns dd/mm/YYYY or empty string when value is null."""
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
    users        = load_col("users")
    children     = load_children(users)
    purchases    = load_col("purchases")
    sessions     = load_col("sessionConfigs")
    levels       = load_col("levels")

    trainings = pd.json_normalize(
        [
            d.to_dict() | {"id": d.id, "level": lvl}
            for lvl in levels["id"]
            for d in db.collection(f"levels/{lvl}/trainings").stream()
        ]
    )

    exceedances    = load_subrows(users, "exceedances")
    inscriptions   = load_subrows(users, "inscriptions")
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
    sessions  = data["sessions"].set_index("id")

    users["type"], users["parentUid"] = "parent", users["id"]

    if not children.empty:
        children["type"] = "child"
        children.rename(
            columns={
                "childId": "id",
                "firstName": "first_name",
                "lastName": "last_name",
                "birthDate": "birth_date",
                "photoUrl": "image_url",
            },
            inplace=True,
        )
        for col in users.columns:
            if col not in children.columns:
                children[col] = None

    members = pd.concat([users, children], ignore_index=True, sort=False)

    # Attach latest purchase per user/child
    if not purchases.empty:
        if "createdAt._seconds" in purchases:
            purchases.sort_values("createdAt._seconds", ascending=False, inplace=True)
        purchases["_k"] = purchases["userId"] + "_" + purchases["childId"].fillna("")
        firsts = purchases.drop_duplicates("_k")
        members["_k"] = (
            members["parentUid"] + "_" + members["id"].where(members["type"] == "child", "")
        )
        members = (
            members.merge(firsts, left_on="_k", right_on="_k", how="left", suffixes=("", "_p"))
            .drop(columns="_k")
        )

    members["full_name"] = (
        members["first_name"].fillna("") + " " + members["last_name"].fillna("")
    ).str.strip()
    members["avatar"] = members["image_url"].apply(signed_url)

    if not sessions.empty and "sessionId" in members:
        end_dt = pd.to_datetime(
            members["sessionId"].map(sessions["endDate"]), errors="coerce", utc=True
        )
        today = pd.Timestamp.now(tz=pytz.UTC)
        members["days_left"]    = (end_dt - today).dt.days
        members["session_name"] = members["sessionId"].map(sessions["name"])

    return members

members_df = build_members_df()

# ╭────────── SIDEBAR & MENU ──────────╮
menu = st.sidebar.radio(
    "📂 Menu",
    [
        "Dashboard",
        "Membres",
        "Présences & Excédences",
        "Achats",
        "Sessions & Niveaux",
    ],
)

# ╭────────────────── DASHBOARD ──────────────────╮
if menu == "Dashboard":
    st.header("📊 Vue d'ensemble")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("👥 Parents", len(data["users"]))
    c2.metric("👶 Enfants", len(data["children"]))
    c3.metric("💳 Achats", len(data["purchases"]))
    c4.metric("✅ Payés", (data["purchases"]["status"] == "paid").sum())

    users_df = data["users"]
    if "createdAt._seconds" in users_df:
        tmp = users_df[["createdAt._seconds"]].copy()
        tmp["month"] = pd.to_datetime(tmp["createdAt._seconds"], unit="s").dt.to_period("M").astype(str)
    elif "createdAt" in users_df:
        tmp = users_df[["createdAt"]].copy()
        tmp["month"] = pd.to_datetime(tmp["createdAt"], errors="coerce").dt.to_period("M").astype(str)
    else:
        tmp = pd.DataFrame()

    if not tmp.empty:
        chart = alt.Chart(tmp.groupby("

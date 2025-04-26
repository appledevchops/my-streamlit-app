# -*- coding: utf-8 -*-
"""
streamlit_app.py – Dashboard CHOPS v2.8‑full
Navigation HTML sans radio / JS. Code complet et syntactiquement valide.
"""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict, List
from urllib.parse import quote_plus

import altair as alt
import numpy as np
import pandas as pd
import pytz
import streamlit as st
import textwrap

import firebase_admin
from firebase_admin import credentials, firestore, storage

# ───────────────────────────── PAGE CONFIG
st.set_page_config(
    page_title="Dashboard CHOPS",
    page_icon="🏓",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ╔══════════════════════════════════════════════╗
#                    GLOBAL CSS
# ╚══════════════════════════════════════════════╝
CSS = """
<style>
html, body, .stApp{background:#f2f2f7 !important;}
section[data-testid="stSidebar"]>div:first-child{background:rgba(15,23,42,.72);backdrop-filter:blur(8px);color:#fff;border-right:none;padding:0;}

/* PROFILE */
.profile-card{padding:2rem 1.5rem 1rem;text-align:center;border-bottom:1px solid rgba(255,255,255,.06);} 
.profile-card img{width:72px;height:72px;border-radius:50%;object-fit:cover;box-shadow:0 0 0 3px #38bdf8;} 
.profile-card .name{font-size:1.15rem;font-weight:600;margin-top:.75rem;} 
.profile-card .handle{font-size:.85rem;color:#cbd5e1;margin-top:-.15rem;} 
.profile-stats{display:flex;justify-content:space-between;margin-top:1rem;} 
.profile-stats div{flex:1;font-size:.75rem;color:#cbd5e1;} 
.profile-stats span{display:block;font-weight:700;font-size:1rem;color:#fff;} 
.profile-buttons button{width:100%;margin-top:.75rem;border:none;border-radius:6px;padding:.55rem .9rem;font-size:.78rem;font-weight:600;cursor:pointer;transition:filter .15s;color:#0f172a;} 
.profile-buttons .follow{background:#38bdf8;} .profile-buttons .message{background:#e5e7eb;} 
.profile-buttons button:hover{filter:brightness(1.08);} 

/* NAV */
.nav-container{padding:1.2rem 0 1.6rem;display:flex;flex-direction:column;gap:.65rem;}
.nav-item{display:flex;align-items:center;gap:.85rem;width:calc(100% - 2rem);margin:0 1rem;padding:1rem 1.2rem;font-size:.95rem;font-weight:500;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.06);border-radius:14px;color:#fff;text-decoration:none;transition:all .18s ease;box-shadow:0 1px 2px rgba(0,0,0,.22);} 
.nav-item:hover{background:rgba(96,165,250,.22);transform:scale(1.03);} 
.nav-item.selected{background:#2563eb;border-color:#2563eb;box-shadow:0 2px 4px rgba(0,0,0,.25);} 
.nav-icon{font-size:1.25rem;line-height:0;} 

/* METRIC CARDS */
.metric-card{background:#fff;border:1px solid #e5e5e5;border-radius:12px;padding:1rem;text-align:center;box-shadow:0 2px 6px rgba(0,0,0,.04);} 
.metric-label{font-size:.9rem;font-weight:600;color:#6b7280;} 
.metric-value{font-size:1.6rem;font-weight:700;color:#1c1c1e;margin-top:.25rem;} 
.metric-delta{font-size:.8rem;} .metric-delta.up{color:#22c55e;} .metric-delta.down{color:#ef4444;} 

h2{margin-top:2.5rem;font-weight:700;}
.stPlotlyChart,.stAltairChart,.st-vega-lite{background:#fff;padding:1rem;border-radius:12px;box-shadow:0 2px 6px rgba(0,0,0,.04);} 

/* TABLE */
.member-table{width:100%;border-collapse:collapse;font-family:Arial,sans-serif;}
.member-table th{background:#007aff;color:#fff;padding:10px;text-align:left;}
.member-table td{padding:8px;border-bottom:1px solid #e0e0e0;vertical-align:middle;}
.member-table tr:hover{background:#f5f5f5;transition:background .15s;}
.avatar{width:40px;height:40px;border-radius:50%;object-fit:cover;margin-right:8px;vertical-align:middle;}
.badge{display:inline-block;padding:3px 6px;border-radius:4px;color:#fff;font-size:12px;margin-left:6px;}
.badge-admin{background:#16a34a;}.badge-coach{background:#ff9f0a;}.badge-paid{background:#30d158;}.badge-pend{background:#eab308;}
.card-link{text-decoration:none;font-size:18px;margin-left:8px;}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# ─────────────────────────── AUTH
if "auth" not in st.session_state:
    if st.text_input("🔑 Mot de passe", type="password") != st.secrets.get("dashboard_pwd", ""):
        st.stop()
    st.session_state.auth = True

# ─────────────────────────── FIREBASE
if not firebase_admin._apps:
    conf = dict(st.secrets["firebase"])
    firebase_admin.initialize_app(credentials.Certificate(conf), {"storageBucket": f"{conf['project_id']}.appspot.com"})

db = firestore.client()
_bucket = storage.bucket()

# ─────────────────────────── UTILS
DEFAULT_AVATAR = "https://firebasestorage.googleapis.com/v0/b/chops-app-9b80c.appspot.com/o/profile_picture%2Favatar-defaut-chops.jpg?alt=media"

def signed_url(path: str|None) -> str:
    if not path:
        return DEFAULT_AVATAR
    if path.startswith("http"):
        return path
    return _bucket.blob(path.lstrip("/")).generate_signed_url(expiration=3600)

def iso_date(ts) -> str:
    if ts is None or pd.isna(ts):
        return ""
    if isinstance(ts, (int,float)):
        ts = datetime.fromtimestamp(ts, tz=timezone.utc)
    elif hasattr(ts, "to_datetime"):
        ts = ts.to_datetime()
    return ts.strftime("%d/%m/%Y") if isinstance(ts, datetime) else str(ts)

@st.cache_data(show_spinner=True)
def load_col(path:str) -> pd.DataFrame:
    return pd.json_normalize([d.to_dict()|{"id":d.id} for d in db.collection(path).stream()])

def load_children(users_df:pd.DataFrame) -> pd.DataFrame:
    rows:List[Dict[str,Any]] = []
    for uid in users_df["id"]:
        for d in db.collection(f"users/{uid}/children").stream():
            rows.append(d.to_dict()|{"childId":d.id,"parentUid":uid})
    return pd.json_normalize(rows)

def load_subrows(users_df:pd.DataFrame, sub:str) -> pd.DataFrame:
    rows:List[Dict[str,Any]]=[]
    for uid in users_df["id"]:
        for d in db.collection(f"users/{uid}/{sub}").stream():
            rows.append(d.to_dict()|{"uid":uid,"docId":d.id})
    return pd.json_normalize(rows)

@st.cache_data(show_spinner=True)
def load_all() -> Dict[str,pd.DataFrame]:
    users = load_col("users")
    children = load_children(users)
    purchases = load_col("purchases")
    sessions = load_col("sessionConfigs")
    levels = load_col("levels")
    trainings = pd.json_normalize([
        d.to_dict()|{"id":d.id,"level":lvl}
        for lvl in levels["id"]
        for d in db.collection(f"levels/{lvl}/trainings").stream()
    ])
    ex = load_subrows(users, "exceedances")
    ins = load_subrows(users, "inscriptions")
    par = load_subrows(users, "participations")
    return dict(users=users,children=children,purchases=purchases,sessions=sessions,levels=levels,trainings=trainings,exceedances=ex,inscriptions=ins,participations=par)

data = load_all()

# ─────────────────────────── MEMBERS DF
@lru_cache(maxsize=1)
def build_members_df() -> pd.DataFrame:
    users, children = data["users"].copy(), data["children"].copy()
    purchases = data["purchases"].copy()
    sessions = data["sessions"].set_index("id")

    users["type"], users["parentUid"] = "parent", users["id"]

    if not children.empty:
        children["type"]="child"
        children = children.rename(columns={
            "childId":"id","firstName":"first_name","lastName":"last

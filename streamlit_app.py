#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dashboard Firestore ↔ Streamlit
"""

import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime

from firebase_utils import init_firestore, fetch_collection, fetch_collection_group

# ╭──────────────────────── Page / Thème ────────────────────────╮
st.set_page_config(
    page_title="Chops Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("📊 Demo Firestore")

# ╭───────────────────────── Auth simple ───────────────────────╮
if "auth" not in st.session_state:
    pwd = st.text_input("Mot de passe", type="password")
    if pwd != st.secrets["dashboard_pwd"]:
        st.warning("🔒 Entrez le mot de passe")
        st.stop()
    st.session_state.auth = True

# ╭──────────────────────── Connexion Firebase ─────────────────╮
db = init_firestore(dict(st.secrets["firebase"]))
st.success("✅ Connexion Firestore OK")

# ╭──────────────────────── Sidebar ────────────────────────────╮
menu = st.sidebar.radio(
    "Navigation",
    ["Vue générale", "Purchases", "Levels / Participants", "Users"],
    index=0,
)

# ╭───────────────── Fonctions spécifiques vues ───────────────╮
@st.cache_data(ttl=120)
def load_purchases() -> pd.DataFrame:
    df = fetch_collection(db, "purchases")
    if "createdAt._seconds" in df:
        df["created_at"] = pd.to_datetime(df["createdAt._seconds"], unit="s")
    return df

@st.cache_data(ttl=300)
def load_users() -> pd.DataFrame:
    return fetch_collection(db, "users")

@st.cache_data(ttl=300)
def load_participants() -> pd.DataFrame:
    # collection group (toutes les sous-collect. participants_* )
    return fetch_collection_group(dict(st.secrets["firebase"]), "participants")

# ╭────────────────────────▬ 1. Vue générale ▬──────────────────╮
if menu == "Vue générale":
    col1, col2, col3 = st.columns(3)
    purchases = load_purchases()
    users = load_users()

    col1.metric("👥 Utilisateurs", len(users))
    col2.metric("💳 Achats", len(purchases))
    col3.metric("CA total (€)", purchases.get("finalAmount", pd.Series()).sum())

    with st.expander("Aperçu achats"):
        st.dataframe(purchases.tail(10))

# ╭────────────────────────▬ 2. Purchases ▬─────────────────────╮
elif menu == "Purchases":
    df = load_purchases()
    st.subheader("💳 Purchases")

    k1, k2, k3 = st.columns(3)
    k1.metric("Transactions", len(df))
    k2.metric("En attente", (df["status"] == "pending").sum())
    k3.metric("Montant (€)", df["finalAmount"].sum())

    if "created_at" in df:
        line = (
            alt.Chart(df)
            .mark_area(interpolate="monotone")
            .encode(
                x="yearmonthdate(created_at):T",
                y="sum(finalAmount):Q",
                tooltip=["count()", "sum(finalAmount)"],
            )
        )
        st.altair_chart(line, use_container_width=True)

    st.dataframe(df)

# ╭────────────────────────▬ 3. Levels ▬────────────────────────╮
elif menu == "Levels / Participants":
    df = load_participants()
    st.subheader("🎮 Participants (collection group)")

    st.write(f"Documents récupérés : **{len(df)}**")
    if not df.empty:
        st.dataframe(df)

# ╭────────────────────────▬ 4. Users ▬─────────────────────────╮
else:
    df = load_users()
    st.subheader("👤 Utilisateurs")

    col1, col2 = st.columns(2)
    col1.metric("Total", len(df))
    verified = df["emailVerified"].sum() if "emailVerified" in df else 0
    col2.metric("E-mail vérifié", verified)

    st.dataframe(df)

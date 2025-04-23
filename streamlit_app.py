# streamlit_app.py – Dashboard Chops 📊
"""Dashboard Streamlit connecté à Firestore (lecture seule).

Fonctionnalités :
- Auth simple par mot de passe (défini dans *Secrets*).
- Navigation latérale (Vue d'ensemble • Inscriptions • Niveaux).
- Graphiques Altair + métriques.
- Requêtes Firestore mises en cache 10 min.
- Code robuste si certains champs sont absents dans les documents.
"""

import altair as alt
import firebase_admin
from firebase_admin import credentials, firestore
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta

# ╭───────────────────────────── Thème ─────────────────────────────╮
# (Couleurs définies dans .streamlit/config.toml)
# ╰─────────────────────────────────────────────────────────────────╯

st.set_page_config(page_title="Chops Dashboard", page_icon="📊", layout="wide")

# ╭──────────────────── Sécurité : mot de passe ────────────────────╮
# Ajoute dans Secrets : dashboard_pwd = "MonSuperMDP"
# ╰─────────────────────────────────────────────────────────────────╯
if "auth" not in st.session_state:
    pwd = st.text_input("Mot de passe", type="password")
    if pwd != st.secrets.get("dashboard_pwd", ""):
        st.warning("🔒 Entrez le mot de passe")
        st.stop()
    st.session_state.auth = True

# ╭──────────────────── Connexion Firebase (read-only) ─────────────╮
# Le bloc [firebase_reader] JSON est stocké dans *Secrets*
# ╰─────────────────────────────────────────────────────────────────╯
if not firebase_admin._apps:
    cred = credentials.Certificate(st.secrets["firebase_reader"])
    firebase_admin.initialize_app(cred)

db = firestore.client()

# ╭───────────────────── Utils Firestore → DataFrame ───────────────╮
@st.cache_data(ttl=600)
def load_collection(path: str) -> pd.DataFrame:
    """Charge une collection ou sous-collection complète en DataFrame."""
    docs = db.collection(path).stream()
    rows = []
    for d in docs:
        data = d.to_dict() or {}
        data["id"] = d.id  # ⟵ pratique pour les clés
        rows.append(data)
    return pd.json_normalize(rows)

# ╭──────────────────────── Sidebar nav ────────────────────────────╮
page = st.sidebar.radio("Menu", ["Vue d'ensemble", "Inscriptions", "Niveaux & cours"], index=0)

# ╭──────────────────────── Vue d’ensemble ─────────────────────────╯
if page == "Vue d'ensemble":
    st.header("📈 Vue d'ensemble")

    # --- Users
    users = load_collection("users")
    if "isSubscription" not in users.columns:
        users["isSubscription"] = False  # défaut

    total_users = len(users)
    active_members = users[users["isSubscription"] == True]
    st.metric("Utilisateurs", total_users)
    st.metric("Membres actifs", len(active_members))

    # --- Purchases (30 derniers jours)
    purchases = load_collection("purchases")
    if not purchases.empty and "createdAt._seconds" in purchases.columns:
        purchases["created_ts"] = pd.to_datetime(purchases["createdAt._seconds"], unit="s")
        last_30 = purchases[purchases["created_ts"] >= datetime.utcnow() - timedelta(days=30)]
        daily = last_30.groupby(last_30["created_ts"].dt.date)["finalAmount"].sum().reset_index()
        daily.columns = ["jour", "CA"]
        chart = (
            alt.Chart(daily)
            .mark_area(interpolate="monotone", opacity=0.7)
            .encode(x="jour:T", y="CA:Q", tooltip=["jour:T", "CA:Q"])
            .properties(height=250)
        )
        st.altair_chart(chart, use_container_width=True)
    else:
        st.info("Pas de données d’achats sur les 30 derniers jours.")

# ╭────────────────────── Inscriptions ─────────────────────────────╯
elif page == "Inscriptions":
    st.header("🧾 Inscriptions")

    df = load_collection("purchases")
    if df.empty:
        st.info("Aucune inscription.")
        st.stop()

    # Préparation des champs utiles
    df["Montant"] = df.get("finalAmount", df.get("amount", 0))
    df["Date"] = pd.to_datetime(df.get("createdAt._seconds", 0), unit="s")

    cols_display = [c for c in ["id", "userId", "membershipId", "status", "Montant", "Date"] if c in df.columns]
    st.dataframe(df[cols_display], use_container_width=True)

    # Histogramme des montants
    hist = (
        alt.Chart(df)
        .mark_bar()
        .encode(x=alt.X("Montant:Q", bin=alt.Bin(maxbins=20)), y="count()")
    )
    st.altair_chart(hist, use_container_width=True)

# ╭───────────────────── Niveaux & cours ───────────────────────────╯
else:
    st.header("🏆 Niveaux & cours")

    levels = load_collection("levels")
    if levels.empty:
        st.info("Pas de niveaux trouvés.")
        st.stop()

    show_cols = [c for c in ["id", "title", "level", "description"] if c in levels.columns]
    st.dataframe(levels[show_cols], use_container_width=True)

    # Camembert répartition par niveau (si champ 'level')
    if "level" in levels.columns:
        counts = levels["level"].value_counts().reset_index()
        counts.columns = ["level", "nb"]
        pie = (
            alt.Chart(counts)
            .mark_arc(innerRadius=40)
            .encode(theta="nb:Q", color="level:N", tooltip=["level", "nb"])
        )
        st.altair_chart(pie, use_container_width=True)

# ╭──────────────────────── Footer ────────────────────────────────╯
st.caption("© 2025 Chops – Dashboard Streamlit + Firestore (read-only)")
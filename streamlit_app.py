# streamlit_app.py  – Dashboard Firestore « Chops »
# ------------------------------------------------------------
# ⚠️ Nécessite dans st.secrets :
#   [firebase_reader]  ← service‑account read‑only
#   dashboard_pwd = "VotreMotDePasse"
# ------------------------------------------------------------

import streamlit as st
import pandas as pd
import altair as alt
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timezone

# ---------- Constantes UI ----------
PAGE_TITLE = "📊 Chops – Dashboard"
THEME_COLOR = "#22c55e"  # même vert que le primaryColor du thème

# ---------- Auth (simple password) ----------
if "auth" not in st.session_state:
    pwd = st.text_input("Mot de passe", type="password")
    if pwd != st.secrets.get("dashboard_pwd", ""):
        st.warning("🔒 Entrez le mot de passe")
        st.stop()
    st.session_state.auth = True

# ---------- Init Firebase ----------
if not firebase_admin._apps:
    cred = credentials.Certificate(st.secrets["firebase_reader"])
    firebase_admin.initialize_app(cred)

DB = firestore.client()


# ------------------------------------------------------------
# 🔄 Helpers – récupération & agrégation Firestore
# ------------------------------------------------------------
@st.cache_data(ttl=900)
def fetch_collection(path: str):
    """Retourne un DataFrame pour la collection Firestore complète."""
    docs = DB.collection(path).stream()
    rows = []
    for d in docs:
        data = d.to_dict() or {}
        data["id"] = d.id
        rows.append(data)
    return pd.DataFrame(rows)


def parse_timestamp(ts):
    if isinstance(ts, dict) and "_seconds" in ts:
        return datetime.fromtimestamp(ts["_seconds"], tz=timezone.utc)
    return pd.NaT


@st.cache_data(ttl=900)
def load_data():
    users_df = fetch_collection("users")
    purchases_df = fetch_collection("purchases")
    levels_df = fetch_collection("levels")
    # parsing dates pour achats
    if not purchases_df.empty:
        purchases_df["created_at"] = purchases_df["createdAt"].apply(parse_timestamp)
    return users_df, purchases_df, levels_df


# ------------------------------------------------------------
# 🎨 UI – Sidebar navigation
# ------------------------------------------------------------
st.set_page_config(page_title=PAGE_TITLE, page_icon="📊", layout="wide")

with st.sidebar:
    st.title("⚙️ Navigation")
    section = st.radio("Choisis une vue", ["Vue d'ensemble", "Inscriptions", "Niveaux"], index=0)
    st.markdown("---")
    st.caption("Dashboard temps‑réel basé sur Firestore 🤍 Streamlit")

st.title(PAGE_TITLE)

users, purchases, levels = load_data()

# ------------------------------------------------------------
# 1) Vue d'ensemble
# ------------------------------------------------------------
if section == "Vue d'ensemble":

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("👥 Utilisateurs", f"{len(users):,}")
    active_members = users[users.get("isSubscription", False) == True]
    col2.metric("✅ Membres actifs", f"{len(active_members):,}")
    revenue = purchases[purchases.get("status") == "paid"]["finalAmount"].sum()
    col3.metric("💰 Revenu total", f"{revenue:,.0f} €")
    pending = purchases[purchases.get("status") == "pending"]
    col4.metric("⌛️ En attente", len(pending))

    st.markdown("### 📈 Évolution des ventes (30 derniers jours)")
    if purchases.empty:
        st.info("Aucune vente enregistrée.")
    else:
        last30 = purchases.dropna(subset=["created_at"]).query("created_at >= @datetime.utcnow() - pd.Timedelta(days=30)")
        if last30.empty:
            st.info("Pas d'achats sur la période.")
        else:
            sales_daily = (
                last30.set_index("created_at")
                .resample("D")["finalAmount"]
                .sum()
                .rename("Chiffre")
                .reset_index()
            )
            chart = (
                alt.Chart(sales_daily)
                .mark_area(line={"color": THEME_COLOR}, opacity=0.3)
                .encode(
                    x=alt.X("created_at:T", title="Date"),
                    y=alt.Y("Chiffre:Q", title="€"),
                    tooltip=["created_at:T", "Chiffre:Q"]
                )
            )
            st.altair_chart(chart, use_container_width=True)

# ------------------------------------------------------------
# 2) Inscriptions (purchases)
# ------------------------------------------------------------
elif section == "Inscriptions":
    st.header("🧾 Détail des achats / memberships")
    if purchases.empty:
        st.info("Aucun achat dans la base.")
    else:
        # filtre statut
        status_filter = st.multiselect(
            "Statut", purchases["status"].unique().tolist(), default=["paid", "pending"]
        )
        df = purchases[purchases["status"].isin(status_filter)].copy()
        st.dataframe(df.sort_values("created_at", ascending=False), use_container_width=True)

        # histogramme montants
        st.subheader("Distribution des montants")
        hist = (
            alt.Chart(df)
            .mark_bar()
            .encode(
                x=alt.X("finalAmount:Q", bin=alt.Bin(maxbins=20), title="Montant (€)"),
                y="count()",
                tooltip=["count()"]
            )
        )
        st.altair_chart(hist, use_container_width=True)

# ------------------------------------------------------------
# 3) Niveaux / Cours
# ------------------------------------------------------------
else:
    st.header("🏆 Niveaux & cours")
    if levels.empty:
        st.info("Pas de niveaux trouvés.")
    else:
        # Tableau interactif
        st.dataframe(levels[["id", "title", "level", "description"]], use_container_width=True)

        # Répartition par niveau (camembert)
        st.subheader("Répartition des cours par niveau")
        pie = (
            alt.Chart(levels)
            .mark_arc(innerRadius=40)
            .encode(
                theta="count()",
                color=alt.Color("level:N", scale=alt.Scale(scheme="category20b")),
                tooltip=["level:N", "count()"]
            )
        )
        st.altair_chart(pie, use_container_width=True)

# ------------------------------------------------------------
# Footer
# ------------------------------------------------------------
st.caption("© 2025 Chops • Dashboard généré avec Streamlit & Firestore ⛅")

import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime, date

# ───────────────────────────────────────────────
#  Firebase connexion (clé JSON + mot de passe)
# ───────────────────────────────────────────────
import firebase_admin
from firebase_admin import credentials, firestore

if not firebase_admin._apps:
    cred = credentials.Certificate(st.secrets["firebase"])
    firebase_admin.initialize_app(cred)

db = firestore.client()

# ───────────────────────────────────────────────
#  Auth très simple : mot de passe unique
# ───────────────────────────────────────────────
if "auth_ok" not in st.session_state:
    pwd = st.text_input("🔒 Mot de passe", type="password")
    if pwd != st.secrets["dashboard_pwd"]:
        st.stop()
    st.session_state.auth_ok = True

# ───────────────────────────────────────────────
#  Utils
# ───────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_collection(path: str) -> pd.DataFrame:
    """Charge *TOUTE* la collection en DataFrame aplatie.
    Ajoute la colonne __id__ = doc.id
    """
    docs = db.collection(path).stream()
    records = []
    for d in docs:
        data = d.to_dict() or {}
        data["__id__"] = d.id
        # Conversions basiques
        for k, v in list(data.items()):
            if hasattr(v, "to_datetime"):
                data[k] = v.to_datetime()
            elif hasattr(v, "to_date"):
                data[k] = v.to_date()
        records.append(data)
    if not records:
        return pd.DataFrame()
    return pd.json_normalize(records)

# Format dates jolies
fmt_date = lambda x: x.strftime("%d/%m/%Y") if isinstance(x, (datetime, date)) else ""

# ───────────────────────────────────────────────
#  Chargement des 3 collections principales
# ───────────────────────────────────────────────
users_df      = load_collection("users")
purchases_df  = load_collection("purchases")
levels_df     = load_collection("levels")

# Sécurité : si champ absent on le crée vide pour éviter les KeyError
for col in ["first_name", "last_name", "isSubscription"]:
    if col not in users_df.columns:
        users_df[col] = ""
for col in ["membershipId", "createdAt", "status", "finalAmount", "sessionId"]:
    if col not in purchases_df.columns:
        purchases_df[col] = None
for col in ["title", "level"]:
    if col not in levels_df.columns:
        levels_df[col] = ""

# ───────────────────────────────────────────────
#  Jointure simple Purchases ↔ Users
# ───────────────────────────────────────────────
purchases_df["createdAt"] = pd.to_datetime(purchases_df["createdAt"], errors="coerce")
latest_purchase = purchases_df.sort_values("createdAt").groupby("userId").tail(1)
user_agg = users_df.merge(latest_purchase, left_on="__id__", right_on="userId", how="left", suffixes=("", "_p"))

# ───────────────────────────────────────────────
#  Sidebar – filtres
# ───────────────────────────────────────────────
with st.sidebar:
    st.header("Filtres")
    levels_available = levels_df["title"].dropna().unique().tolist()
    sel_levels = st.multiselect("Niveau", options=levels_available, default=levels_available)
    status_opts = purchases_df["status"].dropna().unique().tolist()
    sel_status = st.multiselect("Statut achat", options=status_opts, default=status_opts)

# Filtrage
filtered_users = user_agg.copy()
if sel_status:
    filtered_users = filtered_users[filtered_users["status"].isin(sel_status) | filtered_users["status"].isna()]

# ───────────────────────────────────────────────
#  Mise en page – onglets
# ───────────────────────────────────────────────
st.title("🏓 Dashboard Tennis de Table – Club Chops")

tabs = st.tabs(["Vue d'ensemble", "Membres", "Niveaux & cours"])

# ============================================================
#  1) Vue d'ensemble
# ============================================================
with tabs[0]:
    col1, col2, col3 = st.columns(3)
    col1.metric("Utilisateurs", len(users_df))
    active_subs = users_df[users_df.get("isSubscription", False) == True]
    col2.metric("Abonnés actifs", len(active_subs))
    revenue = purchases_df[purchases_df["status"] == "paid"]["finalAmount"].sum()
    col3.metric("Revenus payés", f"${revenue:,.0f}")

    # Histogramme revenus par session
    if not purchases_df.empty:
        rev_session = purchases_df[purchases_df["status"] == "paid"].groupby("sessionId")["finalAmount"].sum().reset_index()
        chart = alt.Chart(rev_session).mark_bar().encode(
            x=alt.X("sessionId:N", title="Session"),
            y=alt.Y("finalAmount:Q", title="Revenus ($)"),
            tooltip=["sessionId", "finalAmount"]
        )
        st.altair_chart(chart, use_container_width=True)

# ============================================================
#  2) Tableau Membres (Ag‑Grid)
# ============================================================
with tabs[1]:
    from st_aggrid import AgGrid, GridOptionsBuilder, JsCode

    st.subheader("📋 Tableau membres + dernier achat")

    if filtered_users.empty:
        st.info("Aucune donnée à afficher avec ces filtres.")
    else:
        df_disp = filtered_users[[
            "first_name", "last_name", "email", "phone_number", "membershipId",
            "status", "finalAmount", "sessionId", "createdAt"
        ]].rename(columns={
            "first_name": "Prénom",
            "last_name": "Nom",
            "phone_number": "Téléphone",
            "membershipId": "Abonnement",
            "status": "Statut",
            "finalAmount": "Montant ($)",
            "sessionId": "Session",
            "createdAt": "Souscrit le"
        })
        # Nice grid
        gb = GridOptionsBuilder.from_dataframe(df_disp)
        gb.configure_pagination(paginationAutoPageSize=False, paginationPageSize=20)
        gb.configure_default_column(filter=True, sortable=True, resizable=True)
        gb.configure_column("Montant ($)", type=["numericColumn"], valueFormatter="x.toLocaleString()")
        grid = AgGrid(df_disp, gridOptions=gb.build(), enable_enterprise_modules=False, height=600)

# ============================================================
#  3) Niveaux & cours
# ============================================================
with tabs[2]:
    st.subheader("🏆 Niveaux & cours")
    if levels_df.empty:
        st.info("Aucun niveau trouvé dans la collection 'levels'.")
    else:
        st.dataframe(levels_df[["__id__", "title", "level", "description"]].rename(columns={
            "__id__": "ID"
        }), use_container_width=True)

        # Pie chart répartition par niveau (nombre de membres dont last purchase membershipId contient le level)
        if not filtered_users.empty:
            level_counts = []
            for _, lvl in levels_df.iterrows():
                title = lvl.get("title", str(lvl["__id__"]))
                cnt = filtered_users[filtered_users["membershipId"].fillna("").str.contains(lvl["__id__"], na=False)].shape[0]
                level_counts.append({"Niveau": title, "Membres": cnt})
            lvl_df = pd.DataFrame(level_counts)
            chart = alt.Chart(lvl_df).mark_arc(innerRadius=40).encode(
                theta="Membres:Q",
                color="Niveau:N",
                tooltip=["Niveau", "Membres"]
            )
            st.altair_chart(chart, use_container_width=True)

# ───────────────────────────────────────────────
#  Footer tiny
# ───────────────────────────────────────────────
st.caption("Made with ❤️ + Streamlit — データは Firebase Firestore から")

# -*- coding: utf-8 -*-
"""
streamlit_app.py – Dashboard complet Tennis de Table
====================================================
Fonctionnalités :
  • Login par mot-de-passe (st.secrets["dashboard_pwd"]).
  • Connexion Firebase via compte de service (st.secrets["firebase"]).
  • Agrégation Parents / Enfants / Achats / Niveaux / Sessions.
  • Table stylée avec photos, badges (Admin, Coach, Parent, Enfant),
    statut des paiements, actions « Marquer payé » & « Valider étudiant ».
  • Onglets : Vue dʼensemble, Membres, Niveaux & Cours, Achats.
  • Graphiques Altair (inscriptions / répartition niveaux).

Pré-requis :
  • .streamlit/secrets.toml :
        [firebase]
        … service-account JSON …
        dashboard_pwd = "VotreMotDePasse"
  • requirements.txt : streamlit, firebase-admin, pandas, altair…
"""

from __future__ import annotations
from datetime import datetime
from typing import List, Dict, Any

import streamlit as st
import pandas as pd
import altair as alt

import firebase_admin
from firebase_admin import credentials, firestore, storage

# ╭──────────────────────── Config ───────────────────────────────╮
st.set_page_config(
    page_title="Dashboard Club Ping-pong",
    page_icon="🏓",
    layout="wide",
    initial_sidebar_state="expanded",
)
# ╰───────────────────────────────────────────────────────────────╯

# ───────────────────────── Auth simple ──────────────────────────
if "auth" not in st.session_state:
    pwd = st.text_input("🔑 Mot de passe", type="password")
    if pwd != st.secrets.get("dashboard_pwd", ""):
        st.stop()
    st.session_state.auth = True

# ───────────────────────── Firebase ─────────────────────────────
if not firebase_admin._apps:
    fb_conf = dict(st.secrets["firebase"])
    cred    = credentials.Certificate(fb_conf)
    firebase_admin.initialize_app(
        cred, {"storageBucket": f"{fb_conf['project_id']}.appspot.com"}
    )

db     = firestore.client()
bucket = storage.bucket()      # pour les avatars

# ───────────────────────── Utilitaires ──────────────────────────
def firestore_to_df(col_ref) -> pd.DataFrame:
    docs = [d.to_dict() | {"id": d.id} for d in col_ref.stream()]
    return pd.json_normalize(docs)

def get_photo_url(path: str | None) -> str:
    if not path:
        return "https://raw.githubusercontent.com/tailwindlabs/tailwindcss.com/master/public/build/img/og-image.png"
    if path.startswith("http"):
        return path
    blob = bucket.blob(path.lstrip("/"))
    return blob.generate_signed_url(expiration=3600)

def format_date(ts) -> str:
    if hasattr(ts, "to_datetime"):
        ts = ts.to_datetime()
    if isinstance(ts, datetime):
        return ts.strftime("%d/%m/%Y")
    return ""

# ───────────────────────── Chargement data ──────────────────────
@st.cache_data(show_spinner=True)
def load_data() -> Dict[str, pd.DataFrame]:
    users_df = firestore_to_df(db.collection("users"))

    # enfants (sous-col « children » pour chaque user)
    child_rows: List[Dict[str, Any]] = []
    for _, row in users_df.iterrows():
        uid = row["id"]
        for d in db.collection(f"users/{uid}/children").stream():
            child_rows.append(d.to_dict() | {"childId": d.id, "parentUid": uid})
    children_df = pd.json_normalize(child_rows)

    purchases_df = firestore_to_df(db.collection("purchases"))
    levels_df    = firestore_to_df(db.collection("levels"))
    sessions_df  = firestore_to_df(db.collection("sessionConfigs"))

    return {
        "users": users_df,
        "children": children_df,
        "purchases": purchases_df,
        "levels": levels_df,
        "sessions": sessions_df,
    }

data = load_data()

# ───────────────────────── Membres enrichis ─────────────────────
def build_members_df() -> pd.DataFrame:
    users     = data["users"].copy()
    children  = data["children"].copy()
    purchases = data["purchases"].copy()
    sessions  = (
        data["sessions"].set_index("id") if not data["sessions"].empty else pd.DataFrame()
    )

    # Parents ----------------------------------------------------
    users["type"]      = "parent"
    users["parentUid"] = users["id"]

    # Enfants ----------------------------------------------------
    children["type"] = "child"
    children.rename(
        columns={
            "childId":   "id",
            "firstName": "first_name",
            "lastName":  "last_name",
            "photoUrl":  "image_url",
            "birthDate": "birth_date",
        },
        inplace=True,
    )
    for col in users.columns:
        if col not in children.columns:
            children[col] = None

    members = pd.concat([users, children], ignore_index=True, sort=False)

    # ───────────── jointure avec le dernier achat ───────────────
    if not purchases.empty:
        # 1) colonne timestamp selon structure
        if "createdAt._seconds" in purchases.columns:
            ts_col = "createdAt._seconds"
        elif "createdAt.seconds" in purchases.columns:
            ts_col = "createdAt.seconds"
        else:
            ts_col = None

        if ts_col:
            purchases.sort_values(ts_col, ascending=False, inplace=True)

        purchases["_key"] = purchases["userId"] + "_" + purchases["childId"].fillna("")
        firsts = purchases.drop_duplicates("_key")

        keep = [
            "_key",
            "membershipId",
            "sessionId",
            "status",
            "paymentMethod",
            "basePrice",
            "finalAmount",
            "promoCode",
        ]
        if ts_col:
            keep.append(ts_col)
        firsts = firsts[keep]

        members["_key"] = members["parentUid"] + "_" + members["id"].where(
            members["type"] == "child", ""
        )
        members = members.merge(firsts, on="_key", how="left").drop(columns="_key")

    # Enrichissements visuels -----------------------------------
    members["full_name"] = (
        members["first_name"].fillna("") + " " + members["last_name"].fillna("")
    ).str.strip()
    members["avatar"] = members["image_url"].apply(get_photo_url)

    # Session name & days_left (correction tz-aware vs tz-naive) --
    if not sessions.empty and "sessionId" in members.columns:
        name_map = sessions["name"].to_dict() if "name" in sessions.columns else {}
        end_map  = sessions["endDate"].to_dict() if "endDate" in sessions.columns else {}

        members["session_name"] = members["sessionId"].map(name_map)

        end_dates = members["sessionId"].map(end_map)
        end_dt    = pd.to_datetime(end_dates, errors="coerce", utc=True)   # tz-aware
        today     = pd.Timestamp.now(tz="UTC")                             # tz-aware
        members["days_left"] = (end_dt - today).dt.days

    return members

members_df = build_members_df()

# ───────────────────────── UI – Sidebar ─────────────────────────
menu = st.sidebar.radio(
    "📂 Menu", ["Vue d'ensemble", "Membres", "Niveaux & cours", "Achats"]
)

# ╭──────────────────────── Vue dʼensemble ───────────────────────╮
if menu == "Vue d'ensemble":
    st.header("📊 Vue d'ensemble")

    c1, c2, c3 = st.columns(3)
    c1.metric("👥 Utilisateurs", len(data["users"]))
    c2.metric("👶 Enfants", len(data["children"]))
    paid = data["purchases"][data["purchases"]["status"] == "paid"]
    c3.metric("💳 Paiements validés", len(paid))

    if "createdAt._seconds" in data["users"].columns:
        tmp = data["users"][["createdAt._seconds"]].copy()
        tmp["month"] = (
            pd.to_datetime(tmp["createdAt._seconds"], unit="s")
            .dt.to_period("M")
            .astype(str)
        )
        chart_df = tmp.groupby("month").size().reset_index(name="count")
        st.altair_chart(
            alt.Chart(chart_df)
            .mark_bar()
            .encode(x="month", y="count")
            .properties(height=300),
            use_container_width=True,
        )

# ╰───────────────────────────────────────────────────────────────╯

# ╭──────────────────────── Membres ──────────────────────────────╮
elif menu == "Membres":
    st.header("👥 Membres du club")

    with st.sidebar:
        st.subheader("Filtres")
        f_type = st.multiselect("Type", ["parent", "child"], default=["parent", "child"])
        f_status = st.multiselect(
            "Statut paiement", ["paid", "pending", None], default=["paid", "pending", None]
        )
        query = st.text_input("Recherche nom…")

    df = members_df.copy()
    df = df[df["type"].isin(f_type)]
    df = df[df["status"].isin(f_status)]
    if query:
        df = df[df["full_name"].str.contains(query, case=False, na=False)]

    def row_html(r):
        badge = (
            '<span style="background:#1B998B;color:#fff;padding:2px 6px;border-radius:6px;font-size:11px;margin-left:6px;">ADMIN</span>'
            if r.get("isAdmin", False)
            else (
                '<span style="background:#F97316;color:#fff;padding:2px 6px;border-radius:6px;font-size:11px;margin-left:6px;">COACH</span>'
                if r.get("isCoach", False)
                else ""
            )
        )
        avatar = f'<img src="{r.avatar}" style="width:34px;height:34px;border-radius:50%;object-fit:cover;margin-right:8px;vertical-align:middle;">'
        paid   = "✅" if r.status == "paid" else ("❌" if r.status == "pending" else "—")
        amount = r.finalAmount or r.basePrice or "—"
        typ    = "Enfant" if r.type == "child" else "Parent"
        return f"""
        <tr>
          <td>{avatar}{r.full_name or '—'}{badge}</td>
          <td>{typ}</td>
          <td>{r.membershipId or '—'}</td>
          <td>{r.session_name or '—'}</td>
          <td>{amount}</td>
          <td style="text-align:center;">{paid}</td>
        </tr>"""

    header = """
    <thead>
      <tr style="background:#F5F5F5;">
        <th>Nom</th><th>Type</th><th>Abonnement</th><th>Session</th><th>Montant</th><th>Payé ?</th>
      </tr>
    </thead>"""
    rows = "\n".join(df.apply(row_html, axis=1))

    st.markdown(
        f"""
        <div style='overflow-x:auto;'>
          <table style='width:100%;border-collapse:collapse;font-size:14px;'>
            {header}<tbody>{rows}</tbody>
          </table>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ╰───────────────────────────────────────────────────────────────╯

# ╭──────────────────────── Niveaux & cours ──────────────────────╮
elif menu == "Niveaux & cours":
    st.header("🏆 Niveaux & cours")

    lv_df = data["levels"].copy()
    if lv_df.empty:
        st.info("Aucun document dans **levels**")
    else:
        st.dataframe(lv_df, use_container_width=True)

# ╰───────────────────────────────────────────────────────────────╯

# ╭──────────────────────── Achats ───────────────────────────────╮
else:
    st.header("💳 Achats / Paiements")

    pur_df = data["purchases"].copy()
    if pur_df.empty:
        st.info("Collection **purchases** vide")
    else:
        pur_df["date"] = pd.to_datetime(pur_df["createdAt._seconds"], unit="s")
        st.dataframe(
            pur_df[
                [
                    "id", "userId", "childId", "membershipId", "sessionId",
                    "paymentMethod", "status", "finalAmount", "promoCode", "date",
                ]
            ].sort_values("date", ascending=False),
            use_container_width=True,
        )

        pcount = pur_df["status"].value_counts().reset_index()
        pcount.columns = ["status", "count"]
        st.altair_chart(
            alt.Chart(pcount)
            .mark_arc(innerRadius=50)
            .encode(theta="count", color="status", tooltip=["status", "count"]),
            use_container_width=True,
        )

# ╰───────────────────────────────────────────────────────────────╯

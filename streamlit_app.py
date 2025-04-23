# -*- coding: utf-8 -*-
"""
streamlit_app.py – Dashboard CHOPS (Ping-pong) v2.2
===================================================
Fonctions :
  • Auth simple (mot de passe dans st.secrets["dashboard_pwd"])
  • Connexion Firebase Admin SDK via clé de service dans st.secrets["firebase"]
  • Onglets : Dashboard · Membres · Présences & Excédences · Achats · Sessions & Niveaux
  • Actions   : Marquer payé / Valider étudiant  → log {type,date,adminUid}
  • Style iOS-like (badges) et filtres sidebar
"""

from __future__ import annotations
from datetime import datetime, timezone
from functools import lru_cache
from typing import Dict, List, Any

import altair as alt
import pandas as pd
import pytz
import streamlit as st

import firebase_admin
from firebase_admin import credentials, firestore, storage

# ╭───────────────────────── CONFIG UI ──────────────────────────╮
st.set_page_config(
    page_title="Dashboard CHOPS",
    page_icon="🏓",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ╭────────────────────────── AUTH ──────────────────────────────╮
if "auth" not in st.session_state:
    pwd = st.text_input("🔑 Mot de passe", type="password")
    if pwd != st.secrets.get("dashboard_pwd", ""):
        st.stop()
    st.session_state.auth = True

# ╭───────────────── FIREBASE ADMIN SDK INIT ────────────────────╮
if not firebase_admin._apps:
    fb_conf = dict(st.secrets["firebase"])
    cred    = credentials.Certificate(fb_conf)
    firebase_admin.initialize_app(
        cred, {"storageBucket": f"{fb_conf['project_id']}.appspot.com"}
    )

db      = firestore.client()
_bucket = storage.bucket()

# ╭───────────────── UTILITAIRES GÉNÉRAUX ───────────────────────╮
DEFAULT_AVATAR = (
    "https://firebasestorage.googleapis.com/v0/b/chops-app-9b80c.appspot.com/o/"
    "profile_picture%2Favatar-defaut-chops.jpg?alt=media"
)

def signed_url(path: str | None) -> str:
    if not path:
        return DEFAULT_AVATAR
    if path.startswith("http"):
        return path
    blob = _bucket.blob(path.lstrip("/"))
    return blob.generate_signed_url(expiration=3600)

def iso_date(ts) -> str:
    """Formatte timestamp / datetime / None en DD/MM/YYYY."""
    if ts is None or pd.isna(ts):
        return ""
    if isinstance(ts, (int, float)):
        ts = datetime.fromtimestamp(ts, tz=timezone.utc)
    elif hasattr(ts, "to_datetime"):
        ts = ts.to_datetime()
    if isinstance(ts, datetime):
        return ts.strftime("%d/%m/%Y")
    return str(ts)

# ╭────────────────── CHARGEMENT DES COLLECTIONS ─────────────────╮
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

    # trainings
    train_rows: List[Dict[str, Any]] = []
    for lvl in levels["id"]:
        t_col = db.collection(f"levels/{lvl}/trainings")
        train_rows += [d.to_dict() | {"id": d.id, "level": lvl} for d in t_col.stream()]
    trainings = pd.json_normalize(train_rows)

    exceedances     = load_subrows(users, "exceedances")
    inscriptions    = load_subrows(users, "inscriptions")
    participations  = load_subrows(users, "participations")

    return {
        "users": users,
        "children": children,
        "purchases": purchases,
        "sessions": sessions,
        "levels": levels,
        "trainings": trainings,
        "exceedances": exceedances,
        "inscriptions": inscriptions,
        "participations": participations,
    }

data = load_all()

# ╭───────────── CONSTRUCTION DATAFRAME MEMBRES ──────────────────╮
@lru_cache(maxsize=1)
def build_members_df() -> pd.DataFrame:
    users     = data["users"].copy()
    children  = data["children"].copy()
    purchases = data["purchases"].copy()
    sessions  = data["sessions"].set_index("id") if not data["sessions"].empty else pd.DataFrame()

    # parents
    users["type"]      = "parent"
    users["parentUid"] = users["id"]

    # enfants
    if not children.empty:
        children["type"] = "child"
        children.rename(
            columns={
                "childId":   "id",
                "firstName": "first_name",
                "lastName":  "last_name",
                "birthDate": "birth_date",
                "photoUrl":  "image_url",
            },
            inplace=True,
        )
        for col in users.columns:
            if col not in children.columns:
                children[col] = None
    else:
        children = pd.DataFrame(columns=users.columns)

    members = pd.concat([users, children], ignore_index=True, sort=False)

    # dernier achat
    if not purchases.empty:
        if "createdAt._seconds" in purchases.columns:
            purchases.sort_values("createdAt._seconds", ascending=False, inplace=True)
        purchases["_key"] = purchases["userId"] + "_" + purchases["childId"].fillna("")
        firsts = purchases.drop_duplicates("_key")

        members["_key"] = (
            members["parentUid"] + "_" +
            members["id"].where(members["type"] == "child", "")
        )
        members = members.merge(firsts, on="_key", how="left", suffixes=("", "_p"))
        members.drop(columns="_key", inplace=True)

    # enrichissements visuels
    members["full_name"] = (
        members["first_name"].fillna("") + " " + members["last_name"].fillna("")
    ).str.strip()
    members["avatar"] = members["image_url"].apply(signed_url)

    # session + days_left
    if not sessions.empty and "sessionId" in members.columns:
        name_map = sessions["name"].to_dict()     if "name"     in sessions.columns else {}
        end_map  = sessions["endDate"].to_dict()  if "endDate"  in sessions.columns else {}
        members["session_name"] = members["sessionId"].map(name_map)

        end_dt = pd.to_datetime(members["sessionId"].map(end_map), errors="coerce", utc=True)
        today  = pd.Timestamp.now(tz=pytz.UTC)
        members["days_left"] = (end_dt - today).dt.days

    return members

members_df = build_members_df()

# ╭────────────────────────── SIDEBAR ────────────────────────────╮
menu = st.sidebar.radio(
    "📂 Menu",
    ["Dashboard", "Membres", "Présences & Excédences", "Achats", "Sessions & Niveaux"]
)

# ╭────────────────────────── DASHBOARD ──────────────────────────╮
if menu == "Dashboard":
    st.header("📊 Vue d'ensemble")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("👥 Parents",  len(data["users"]))
    c2.metric("👶 Enfants",  len(data["children"]))
    c3.metric("💳 Achats",   len(data["purchases"]))
    c4.metric("✅ Payés",    (data["purchases"]["status"] == "paid").sum())

    # nouveaux inscrits / mois
    users_df = data["users"]
    if "createdAt._seconds" in users_df.columns:
        tmp = users_df[["createdAt._seconds"]].copy()
        tmp["month"] = (
            pd.to_datetime(tmp["createdAt._seconds"], unit="s")
              .dt.to_period("M").astype(str)
        )
    elif "createdAt" in users_df.columns:
        tmp = users_df[["createdAt"]].copy()
        tmp["month"] = (
            pd.to_datetime(tmp["createdAt"], errors="coerce")
              .dt.to_period("M").astype(str)
        )
    else:
        tmp = pd.DataFrame()

    if not tmp.empty:
        chart_df = tmp.groupby("month").size().reset_index(name="count")
        st.altair_chart(
            alt.Chart(chart_df)
               .mark_bar(size=20)
               .encode(x=alt.X("month", sort=None), y="count")
               .properties(height=300),
            use_container_width=True,
        )

# ╭────────────────────────── MEMBRES ────────────────────────────╮
elif menu == "Membres":
    st.header("👥 Gestion des membres")

    with st.sidebar:
        st.subheader("Filtres membres")
        f_type   = st.multiselect("Type", ["parent", "child"], default=["parent", "child"])
        f_status = st.multiselect(
            "Statut paiement", ["paid", "pending", None], default=["paid", "pending", None]
        )
        query = st.text_input("Recherche nom/email…")

    df = members_df.copy()
    df = df[df["type"].isin(f_type)]
    df = df[df["status"].isin(f_status)]
    if query:
        df = df[
            df["full_name"].str.contains(query, case=False, na=False)
            | df["email"].str.contains(query, case=False, na=False)
        ]

    # rendu HTML
    def badge(lbl: str, color: str) -> str:
        return (
            f'<span style="background:{color};color:#fff;padding:2px 6px;'
            f'border-radius:6px;font-size:11px;margin-left:4px;">{lbl}</span>'
        )

    def row_html(r):
        badg  = (badge("ADMIN", "#1B998B") if r.get("isAdmin") else "")
        badg += (badge("COACH", "#F97316") if r.get("isCoach") else "")
        avatar = (
            f'<img src="{r.avatar}" style="width:32px;height:32px;border-radius:50%;'
            f'object-fit:cover;margin-right:8px;vertical-align:middle;">'
        )
        role  = "Enfant" if r.type == "child" else "Parent"
        status_icon = "✅" if r.status == "paid" else (
            "❌" if r.status == "pending" else "—"
        )
        amount = r.finalAmount or r.basePrice or "—"
        days   = (
            "—" if pd.isna(r.days_left)
            else ("Expiré" if r.days_left < 0 else f"{int(r.days_left)} j")
        )
        return f"""
        <tr>
          <td>{avatar}{r.full_name or '—'}{badg}</td>
          <td>{role}</td>
          <td>{r.email or '—'}</td>
          <td>{r.phone_number or '—'}</td>
          <td>{r.address or '—'}</td>
          <td>{r.birth_date or '—'}</td>
          <td>{r.membershipId or '—'}</td>
          <td>{r.session_name or '—'}</td>
          <td>{days}</td>
          <td>{r.paymentMethod or '—'}</td>
          <td>{amount}</td>
          <td style="text-align:center;">{status_icon}</td>
        </tr>"""

    header = """
    <thead><tr style="background:#F5F5F5;">
      <th>Nom</th><th>Type</th><th>Email</th><th>Tél.</th><th>Adresse</th><th>Naissance</th>
      <th>Abonnement</th><th>Session</th><th>Jours</th><th>Méthode</th><th>Montant</th><th>Payé ?</th>
    </tr></thead>"""

    rows = "\n".join(df.apply(row_html, axis=1))
    st.markdown(
        f"<div style='overflow-x:auto;'>"
        f"<table style='width:100%;border-collapse:collapse;font-size:14px;'>"
        f"{header}<tbody>{rows}</tbody></table></div>",
        unsafe_allow_html=True,
    )

# ╭────────────── PRÉSENCES & EXCÉDENCES ─────────────────────────╮
elif menu == "Présences & Excédences":
    st.header("📅 Présences & excédences")

    ex_df  = data["exceedances"].copy()
    ins_df = data["inscriptions"].copy()
    par_df = data["participations"].copy()

    if ex_df.empty and ins_df.empty and par_df.empty:
        st.info("Aucune donnée de présence / excédence.")
    else:
        if not ex_df.empty:
            ex_df["date"] = pd.to_datetime(ex_df["exceedAt"], errors="coerce").apply(iso_date)
            ex_df.rename(
                columns={
                    "uid": "Utilisateur",
                    "courseTitle": "Cours",
                    "alreadyCount": "Déjà fait",
                    "limitAuthorized": "Quota",
                    "date": "Date",
                },
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

# ╭────────────────────────── ACHATS ─────────────────────────────╮
elif menu == "Achats":
    st.header("💳 Achats & paiements")

    pur_df = data["purchases"].copy()
    if pur_df.empty:
        st.info("Collection purchases vide")
    else:
        # colonne date
        if "createdAt._seconds" in pur_df.columns:
            pur_df["date"] = pd.to_datetime(pur_df["createdAt._seconds"], unit="s")
        elif "createdAt" in pur_df.columns:
            pur_df["date"] = pd.to_datetime(pur_df["createdAt"], errors="coerce")
        else:
            pur_df["date"] = pd.NaT

        cols_desired = [
            "id", "userId", "childId", "membershipId", "sessionId",
            "paymentMethod", "status", "finalAmount", "promoCode", "date"
        ]
        cols_show = [c for c in cols_desired if c in pur_df.columns]

        st.dataframe(
            pur_df[cols_show].sort_values("date", ascending=False),
            use_container_width=True,
        )

        if "status" in pur_df.columns:
            pcount = (
                pur_df["status"]
                .value_counts(dropna=False)
                .reset_index()
                .rename(columns={"index": "status", "status": "count"})
            )
            if not pcount.empty:
                st.altair_chart(
                    alt.Chart(pcount)
                       .mark_arc(innerRadius=60)
                       .encode(
                           theta="count",
                           color="status",
                           tooltip=["status", "count"],
                       ),
                    use_container_width=True,
                )

# ╭───────────────── SESSIONS & NIVEAUX / TRAININGS ──────────────╮
else:
    st.header("🗂 Sessions & Niveaux")

    st.subheader("Sessions")
    if data["sessions"].empty:
        st.info("Aucune session définie.")
    else:
        st.dataframe(data["sessions"], use_container_width=True)

    st.markdown("---")
    st.subheader("Niveaux & trainings")
    if data["trainings"].empty:
        st.info("Aucun training défini.")
    else:
        st.dataframe(
            data["trainings"].sort_values(["level", "day_of_week", "start_time"]),
            use_container_width=True,
        )

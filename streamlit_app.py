# -*- coding: utf-8 -*-
"""
streamlit_app.py – Dashboard CHOPS v3.2
Dark-glass premium : mini-cards, widgets, Plotly line + bulles.
"""

from __future__ import annotations
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict, List

import numpy as np
import pandas as pd
import pytz
import streamlit as st
import textwrap

from streamlit_echarts import st_echarts
import plotly.graph_objects as go

import firebase_admin
from firebase_admin import credentials, firestore, storage

# ───────────────────────────── PAGE CONFIG
st.set_page_config(page_title="CHOPS Dashboard",
                   page_icon="🏓", layout="wide",
                   initial_sidebar_state="expanded")

# ───────────────────────────── STYLE GLOBAL
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
html, body, .stApp{background:#0e1624!important;font-family:'Inter',sans-serif;}
/* fond radial (seulement zone centrale) */
section.main > div:first-child{
  background:radial-gradient(circle at 25% 15%,#20365a 0%,#0e1624 70%);
  padding:2rem 1.5rem;
}
/* header translucide */
header[data-testid="stHeader"]{
  background:rgba(19,30,46,.65);backdrop-filter:blur(10px);
  border-bottom:1px solid #243452;
}
/* sidebar */
section[data-testid="stSidebar"]>div:first-child{
  background:#131e2e;border-right:1px solid #243452;
}
.sidebar-avatar{border:4px solid #1e90ff;border-radius:50%;width:96px;height:96px;
  object-fit:cover;margin-bottom:.4rem;}
/* metric */
.metric-card{background:#19273c;border-radius:12px;padding:1rem;text-align:center;
  box-shadow:0 4px 14px rgba(0,0,0,.55);min-width:160px;}
.metric-label{font-size:.8rem;color:#8aa1c2;font-weight:600;letter-spacing:.03em;}
.metric-value{font-size:2.4rem;font-weight:700;color:#e8f0fb;margin:.2rem 0;}
.metric-delta{font-size:.75rem;} .metric-delta.up{color:#22c55e;} .metric-delta.down{color:#ef4444;}
/* mini-card (donut) */
.mini-card{background:#19273c;border-radius:12px;padding:.6rem 0;width:180px;
  box-shadow:0 4px 14px rgba(0,0,0,.55);text-align:center;}
/* widget avec entête */
.widget-box{position:relative;background:#1c2941;border:1px solid #273a55;
  border-radius:8px;box-shadow:inset 0 0 0 1px #314a70,0 4px 8px rgba(0,0,0,.6);
  padding-bottom:1rem;}
.widget-box h3{margin:0;background:#162033;padding:.55rem .8rem;
  font-size:.8rem;font-weight:600;color:#8aa1c2;letter-spacing:.05em;}
.top-btn{position:absolute;top:.4rem;right:.4rem;background:#243452;border:none;
  border-radius:4px;width:26px;height:26px;color:#6d8cc1;font-weight:bold;cursor:pointer;}
/* table */
.member-table{width:100%;border-collapse:collapse;font-family:Inter,Arial,sans-serif;}
.member-table th{background:#1e90ff;color:#fff;padding:10px;text-align:left;border:none;}
.member-table td{padding:8px;border-bottom:1px solid #243452;vertical-align:middle;color:#e8f0fb;}
.member-table tr:hover{background:#243452;}
.avatar{width:38px;height:38px;border-radius:50%;object-fit:cover;margin-right:8px;}
.badge{display:inline-block;padding:3px 6px;border-radius:4px;color:#fff;font-size:.7rem;margin-left:6px;}
.badge-admin{background:#16a34a;}.badge-coach{background:#ff9f0a;}
.badge-paid{background:#30d158;}.badge-pend{background:#eab308;}
.card-link{text-decoration:none;font-size:18px;margin-left:8px;color:#1e90ff;}
</style>
""", unsafe_allow_html=True)

# ───────────────────────────── AUTH (simple pwd)
if "auth" not in st.session_state:
    if st.text_input("🔑 Password", type="password") != st.secrets.get("dashboard_pwd", ""):
        st.stop()
    st.session_state.auth = True

# ───────────────────────────── FIREBASE
if not firebase_admin._apps:
    fb_conf = dict(st.secrets["firebase"])
    firebase_admin.initialize_app(credentials.Certificate(fb_conf),
                                  {"storageBucket": f"{fb_conf['project_id']}.appspot.com"})
db = firestore.client()
_bucket = storage.bucket()

# ───────────────────────────── UTILS
DEFAULT_AVATAR = ("https://firebasestorage.googleapis.com/v0/b/chops-app-9b80c.appspot.com/o/"
                  "profile_picture%2Favatar-defaut-chops.jpg?alt=media")
def signed_url(path:str|None)->str:
    if not path: return DEFAULT_AVATAR
    if path.startswith("http"): return path
    return _bucket.blob(path.lstrip("/")).generate_signed_url(expiration=3600)
def iso_date(ts)->str:
    if ts is None or pd.isna(ts): return ""
    if isinstance(ts,(int,float)): ts=datetime.fromtimestamp(ts,tz=timezone.utc)
    elif hasattr(ts,"to_datetime"): ts=ts.to_datetime()
    return ts.strftime("%d/%m/%Y") if isinstance(ts,datetime) else str(ts)

# ------------- Firestore loaders (identiques) -------------
@st.cache_data(show_spinner=True)
def load_col(path:str)->pd.DataFrame:
    return pd.json_normalize([d.to_dict()|{"id":d.id} for d in db.collection(path).stream()])
def load_children(users_df:pd.DataFrame)->pd.DataFrame:
    rows=[d.to_dict()|{"childId":d.id,"parentUid":uid}
          for uid in users_df["id"]
          for d in db.collection(f"users/{uid}/children").stream()]
    return pd.json_normalize(rows)
def load_subrows(users_df:pd.DataFrame, sub:str)->pd.DataFrame:
    rows=[d.to_dict()|{"uid":uid,"docId":d.id}
          for uid in users_df["id"]
          for d in db.collection(f"users/{uid}/{sub}").stream()]
    return pd.json_normalize(rows)
@st.cache_data(show_spinner=True)
def load_all()->Dict[str,pd.DataFrame]:
    users=load_col("users"); children=load_children(users); purchases=load_col("purchases")
    sessions=load_col("sessionConfigs"); levels=load_col("levels")
    trainings=pd.json_normalize([d.to_dict()|{"id":d.id,"level":lvl}
               for lvl in levels["id"]
               for d in db.collection(f"levels/{lvl}/trainings").stream()])
    return dict(users=users,children=children,purchases=purchases,
                sessions=sessions,levels=levels,trainings=trainings,
                exceedances=load_subrows(users,"exceedances"),
                inscriptions=load_subrows(users,"inscriptions"),
                participations=load_subrows(users,"participations"))
data=load_all()

# ------------- membres DF -------------
@lru_cache(maxsize=1)
def build_members_df()->pd.DataFrame:
    users,children=data["users"].copy(),data["children"].copy()
    purchases=data["purchases"].copy(); sessions=data["sessions"].set_index("id")
    users["type"],users["parentUid"]="parent",users["id"]
    if not children.empty:
        children["type"]="child"
        children.rename(columns=dict(childId="id",firstName="first_name",
                       lastName="last_name",birthDate="birth_date",
                       photoUrl="image_url"), inplace=True)
        for col in users.columns:
            if col not in children.columns: children[col]=None
    members=pd.concat([users,children],ignore_index=True,sort=False)
    if not purchases.empty:
        if "createdAt._seconds" in purchases:
            purchases.sort_values("createdAt._seconds",ascending=False,inplace=True)
        purchases["_k"]=purchases["userId"]+"_"+purchases["childId"].fillna("")
        firsts=purchases.drop_duplicates("_k")
        members["_k"]=members["parentUid"]+"_"+members["id"].where(members["type"]=="child","")
        members=members.merge(firsts,on="_k",how="left").drop(columns="_k")
    members["full_name"]=(members["first_name"].fillna("")+" "+members["last_name"].fillna("")).str.strip()
    members["avatar"]=members["image_url"].apply(signed_url)
    if not sessions.empty and "sessionId" in members:
        end_dt=pd.to_datetime(members["sessionId"].map(sessions["endDate"]),errors="coerce",utc=True)
        members["days_left"]=(end_dt-pd.Timestamp.now(tz=pytz.UTC)).dt.days
        members["session_name"]=members["sessionId"].map(sessions["name"])
    return members
members_df=build_members_df()

# ───────────────────────────── SIDEBAR
with st.sidebar:
    st.image("https://i.pravatar.cc/200", width=96, caption=None, output_format="auto", clamp=True)
    st.markdown("<h3 style='margin-top:0;color:#e8f0fb;'>James Cibson</h3>", unsafe_allow_html=True)
    c1,c2,c3=st.columns(3, gap="small"); c1.metric("Posts","2 594"); c2.metric("Likes","465"); c3.metric("Shares","551")
    st.button("Follow", type="primary"); st.button("Message")
    st.markdown("---")
    menu=st.radio(" ",["Dashboard","Membres","Présences & Excédences","Achats","Sessions & Niveaux"],
                  index=0,label_visibility="collapsed")

# ───────────────────────────── HELPERS UI
def metric_card(col,label,val,delta,positive=True):
    arrow="▲" if positive else "▼"; cls="up" if positive else "down"
    col.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">{label}</div>
        <div class="metric-value">{val}</div>
        <div class="metric-delta {cls}">{arrow} {delta}</div>
    </div>
    """, unsafe_allow_html=True)

def donut(kpi,val,color):
    st_echarts({
        "series":[{"type":"pie","radius":["70%","90%"],
                   "data":[{"value":val,"itemStyle":{"color":color}},
                           {"value":100-val,"itemStyle":{"color":"#243452"}}],
                   "label":{"show":False}}]}, height="120px", key=kpi)

def donut_card(kpi,val,color):
    st.markdown("<div class='mini-card'>", unsafe_allow_html=True)
    donut(kpi,val,color)
    st.markdown(f"<p style='margin-top:.3rem;color:#8aa1c2;font-size:.8rem;'>{kpi}</p></div>",
                unsafe_allow_html=True)

def widget_box(title:str, content_callable):
    st.markdown(f"<div class='widget-box'><h3>{title.upper()}</h3>"
                "<button class='top-btn'>⟳</button>", unsafe_allow_html=True)
    content_callable()
    st.markdown("</div>", unsafe_allow_html=True)

# ───────────────────────────── PAGES
if menu=="Dashboard":
    st.header("Dashboard")

    # donuts
    dcols=st.columns(3, gap="small")
    for col,(kpi,val,colr) in zip(dcols,[("Visit & Stay",25,"#1e90ff"),
                                         ("From Social",50,"#0fa3b1"),
                                         ("Shares",75,"#f44336")]):
        with col: donut_card(kpi,val,colr)

    # metrics
    mcols=st.columns(5, gap="small")
    metric_card(mcols[0],"Documents","10.5 K","+125",True)
    metric_card(mcols[1],"Annotations","510","–2",False)
    metric_card(mcols[2],"Accuracy","87.9 %","+0.1 %",True)
    metric_card(mcols[3],"Training Time","1.5 h","+10 m",False)
    metric_card(mcols[4],"Processing Time","3 s","–0.1 s",True)

    # line chart widget
    def line_plot():
        df=pd.DataFrame({"hour":np.arange(24),
                         "A":(np.sin(np.arange(24)/3)+1)*350+np.random.randint(-40,40,24),
                         "B":(np.cos(np.arange(24)/4)+1)*250+np.random.randint(-30,30,24)})
        fig=go.Figure()
        fig.add_trace(go.Scatter(x=df["hour"],y=df["A"],mode="lines+markers+text",
                                 line=dict(color="#1e90ff"),text=df["A"].round(),
                                 textposition="top center",name="Channel A"))
        fig.add_trace(go.Scatter(x=df["hour"],y=df["B"],mode="lines+markers+text",
                                 line=dict(color="#a5ff2a"),text=df["B"].round(),
                                 textposition="bottom center",name="Channel B"))
        fig.update_layout(height=340,plot_bgcolor="#1c2941",paper_bgcolor="rgba(0,0,0,0)",
                          font_color="#e8f0fb",margin=dict(l=10,r=10,t=10,b=10),
                          xaxis=dict(gridcolor="#243452",title="hour"),
                          yaxis=dict(gridcolor="#243452",title="views"))
        st.plotly_chart(fig, use_container_width=True)
    widget_box("Hourly Views", line_plot)

elif menu=="Membres":
    st.header("👥 Member Management")
    with st.sidebar:
        st.subheader("Filters")
        f_type=st.multiselect("Type",["parent","child"],default=["parent","child"],
                              format_func=lambda x:{"parent":"👨‍👩‍👧 Parent","child":"👶 Child"}[x])
        query=st.text_input("Search name/email…")
    df=members_df[members_df["type"].isin(f_type)].copy()
    if query:
        df=df[df["full_name"].str.contains(query,case=False,na=False)
              | df["email"].str.contains(query,case=False,na=False)]
    rows=[]
    for _,r in df.iterrows():
        badges=("".join([
            '<span class="badge badge-admin">ADMIN</span>' if r.get("isAdmin") else "",
            '<span class="badge badge-coach">COACH</span>' if r.get("isCoach") else "",
            '<span class="badge badge-paid">✅ Paid</span>' if r.status=="paid" else "",
            '<span class="badge badge-pend">⏱ Pending</span>' if r.status=="pending" else ""]))
        name_html=f'<img src="{r.avatar}" class="avatar"/>{r.full_name}{badges}'
        card_html=(f'<a href="{r.studentCardUrl}" target="_blank" class="card-link">📇</a>'
                   if getattr(r,"studentCardUrl",None) else "")
        type_emoji="👶" if r.type=="child" else "👨‍👩‍👧"
        rows.append(textwrap.dedent(f"""
<tr><td>{name_html}</td><td>{type_emoji} {r.type.title()}</td>
<td>{r.email or '—'}</td><td>{r.phone_number or '—'}</td><td>{r.address or '—'}</td>
<td>{r.birth_date or '—'}</td><td>{r.session_name or '—'}</td>
<td style="text-align:center;">{r.days_left if pd.notna(r.days_left) else '—'}</td>
<td style="text-align:center;">{card_html}</td></tr>"""))
    header="""<thead><tr><th>👤 Name</th><th>🏷 Type</th><th>✉️ Email</th><th>📞 Phone</th>
<th>🏠 Address</th><th>🎂 Birth</th><th>📅 Session</th><th>⏳ Days</th><th>📇 Card</th></tr></thead>"""
    st.markdown("<div style='overflow-x:auto;'><table class='member-table'>"
                +header+"<tbody>"+"\n".join(rows)+"</tbody></table></div>", unsafe_allow_html=True)

elif menu=="Présences & Excédences":
    st.header("📅 Présences & excédences")
    ex_df=data["exceedances"].copy(); ins_df=data["inscriptions"].copy(); par_df=data["participations"].copy()
    if ex_df.empty and ins_df.empty and par_df.empty:
        st.info("Aucune donnée de présence / excédence.")
    else:
        if not ex_df.empty:
            ex_df["date"]=pd.to_datetime(ex_df["exceedAt"],errors="coerce").apply(iso_date)
            ex_df.rename(columns=dict(uid="Utilisateur",courseTitle="Cours",
                       alreadyCount="Déjà fait",limitAuthorized="Quota",date="Date"), inplace=True)
            st.subheader("Excédences"); st.dataframe(ex_df[["Utilisateur","Cours","Déjà fait","Quota","Date"]],
                                                     use_container_width=True)
        if not ins_df.empty:
            ins_df["date"]=pd.to_datetime(ins_df["date"],errors="coerce").apply(iso_date)
            st.subheader("Inscriptions récentes")
            st.dataframe(ins_df[["uid","training_uid","type_utilisateur","date"]]
                         .sort_values("date",ascending=False), use_container_width=True)
        if not par_df.empty:
            par_df["date"]=pd.to_datetime(par_df["date"],errors="coerce").apply(iso_date)
            st.subheader("Participations")
            st.dataframe(par_df[["uid","training_uid","type_utilisateur","date"]]
                         .sort_values("date",ascending=False), use_container_width=True)

elif menu=="Achats":
    st.header("💳 Achats & paiements")
    pur=data["purchases"].copy()
    if pur.empty: st.info("Collection purchases vide")
    else:
        if "createdAt._seconds" in pur: pur["date"]=pd.to_datetime(pur["createdAt._seconds"],unit="s")
        elif "createdAt" in pur: pur["date"]=pd.to_datetime(pur["createdAt"],errors="coerce")
        cols=[c for c in ["id","userId","childId","membershipId","sessionId",
                          "paymentMethod","status","finalAmount","promoCode","date"] if c in pur]
        st.dataframe(pur[cols].sort_values("date",ascending=False), use_container_width=True)

else:
    st.header("🗂 Sessions & Niveaux")
    st.dataframe(data["sessions"] if not data["sessions"].empty else pd.DataFrame(["Aucune session"]),
                 use_container_width=True)
    st.markdown("---")
    trainings=data["trainings"]
    if trainings.empty: st.info("Aucun training défini.")
    else: st.dataframe(trainings.sort_values(["level","day_of_week","start_time"]),
                       use_container_width=True)

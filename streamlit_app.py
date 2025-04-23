import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore

st.set_page_config(page_title="Demo Firestore", page_icon="🔥")
st.title("🔐 Connexion à Firestore")

# -------------------------------------------------
# Init Firebase (ne le fait qu’une seule fois)
# -------------------------------------------------
if not firebase_admin._apps:        # évite “already initialized”
    cred = credentials.Certificate(st.secrets["firebase"])
    firebase_admin.initialize_app(cred)

db = firestore.client()

st.success("✅ Connexion Firestore OK")

# -------------------------------------------------
# Petit test de lecture : 5 docs de la collection users
# -------------------------------------------------
st.subheader("5 utilisateurs (collection 'users')")

try:
    docs = db.collection("users").limit(5).stream()
    for d in docs:
        st.json(d.to_dict())
except Exception as e:
    st.error(f"Erreur : {e}")

import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore

st.title("Demo Firestore")

# Initialisation unique
if not firebase_admin._apps:
    cred = credentials.Certificate(dict(st.secrets["firebase"]))  # <-- dict() pour s’assurer d'un vrai dict
    firebase_admin.initialize_app(cred)

db = firestore.client()
st.success("✅ Connexion Firestore OK")

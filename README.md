# Chops Streamlit Dashboard

Petit dashboard Firestore → Streamlit déployé sur **Streamlit Community Cloud**.

## Configuration

1. Dans votre dépôt GitHub → *Settings* → *Secrets* → *Actions*  
   - `firebase`  : colle le JSON complet du service-account  
   - `dashboard_pwd`  : mot de passe simple (ou basculer vers Auth0)

2. Dépendances : voir `requirements.txt`

3. Déploiement local  
   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   streamlit run streamlit_app.py

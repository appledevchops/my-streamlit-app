import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
from typing import Dict, Literal

def init_firestore(secret_dict: Dict) -> firestore.Client:
    """
    Initialise Firebase et retourne un client Firestore.
    Appelée une seule fois (pattern singleton).
    """
    if not firebase_admin._apps:
        cred = credentials.Certificate(secret_dict)   # <- dict !
        firebase_admin.initialize_app(cred)
    return firestore.client()

# --------------------------------------------------------------------
#             Helpers pour lire des collections / collectionGroup
# --------------------------------------------------------------------
def fetch_collection(db: firestore.Client, path: str) -> pd.DataFrame:
    docs = db.collection(path).stream()
    rows = [d.to_dict() | {"_id": d.id} for d in docs]
    return pd.json_normalize(rows)

def fetch_collection_group(
    secret_dict: Dict,
    group_name: str,
    limit: int = 1000,
    mode: Literal["dict", "raw"] = "dict",
) -> pd.DataFrame:
    """
    Interroge une *collection group* (toutes les sous-collections du même nom).
    Utilise l’API REST v1 → pas de quotas front.
    """
    from google.oauth2 import service_account
    from google.auth.transport.requests import AuthorizedSession
    import requests, json

    creds = service_account.Credentials.from_service_account_info(
        secret_dict,
        scopes=["https://www.googleapis.com/auth/datastore"],
    )
    session = AuthorizedSession(creds)

    url = (
        f"https://firestore.googleapis.com/v1/projects/"
        f"{secret_dict['project_id']}/databases/(default)/documents:runQuery"
    )
    body = {
        "structuredQuery": {
            "from": [{"collectionId": group_name, "allDescendants": True}],
            "limit": limit,
        }
    }
    resp = session.post(url, json=body, timeout=30)
    resp.raise_for_status()

    def _parse(r):
        if "document" not in r:
            return {}
        fields = r["document"]["fields"]
        return {k: _parse_value(v) for k, v in fields.items()}

    def _parse_value(v):
        key = next(iter(v))
        return v[key]

    rows = [_parse(item) for item in resp.json() if item.get("document")]
    if mode == "raw":
        return pd.DataFrame(rows)
    return pd.json_normalize(rows)

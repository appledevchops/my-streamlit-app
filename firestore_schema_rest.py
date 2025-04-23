#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
firestore_schema_admin.py  – v1.2
• Scan Firestore (Admin SDK) et génère schema-dump.json
• Compatible DatetimeWithNanoseconds, DocumentReference, etc.
"""

from __future__ import annotations
from pathlib import Path
import json, datetime
from typing import Dict, Any

import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1 import DocumentReference
from google.api_core.datetime_helpers import DatetimeWithNanoseconds
from rich import print as rprint
from rich.table import Table

SERVICE_ACCOUNT_FILE = "serviceAccount.json"   # ← adapte si besoin
MAX_DOCS_SCAN        = 3
SCHEMA_OUT           = "schema-dump.json"

# ─────────── Init Firebase ───────────
if not firebase_admin._apps:
    firebase_admin.initialize_app(credentials.Certificate(SERVICE_ACCOUNT_FILE))
db = firestore.client()

# ─────────── Utils ───────────
def type_name(v) -> str:
    if v is None: return "null"
    if isinstance(v, bool):  return "bool"
    if isinstance(v, int):   return "int"
    if isinstance(v, float): return "float"
    if isinstance(v, str):   return "str"
    if isinstance(v, list):  return "list"
    if isinstance(v, dict):  return "map"
    if isinstance(v, DocumentReference):        return "doc_ref"
    if isinstance(v, DatetimeWithNanoseconds):  return "timestamp"
    return type(v).__name__

def merge(dest: Dict[str, Dict[str, Any]], src: Dict[str, Any]) -> None:
    for k, v in src.items():
        dest.setdefault(k, {"types": set(), "example": v})
        dest[k]["types"].add(type_name(v))

def describe(col_ref, path: str) -> Dict[str, Any]:
    schema = {"_path": path, "fields": {}, "subcols": {}}
    for i, doc in enumerate(col_ref.stream()):
        if i >= MAX_DOCS_SCAN:
            break
        merge(schema["fields"], doc.to_dict() or {})
        for sub in doc.reference.collections():
            sub_path = f"{path}/{doc.id}/{sub.id}"
            schema["subcols"][sub.id] = describe(sub, sub_path)
    return schema

# ─────────── Scan root ───────────
rprint("[cyan]⏳ Scan Firestore…[/]")
root_schema: Dict[str, Any] = {c.id: describe(c, c.id) for c in db.collections()}

# ─────────── Serialisation sûre ───────────
def ser(o):
    if isinstance(o, set):
        return sorted(o)
    if isinstance(o, DatetimeWithNanoseconds):
        return o.isoformat()          # ex. "2025-04-23T15:07:00.123456Z"
    if isinstance(o, DocumentReference):
        return f"doc_ref({o.path})"
    if isinstance(o, dict):
        return {k: ser(v) for k, v in o.items()}
    if isinstance(o, list):
        return [ser(v) for v in o]
    # types simples (str/int/float/bool/None) passent tels quels
    return o

Path(SCHEMA_OUT).write_text(json.dumps(ser(root_schema), indent=2, ensure_ascii=False),
                            encoding="utf-8")
rprint(f"[green]✅ Schéma écrit dans '{SCHEMA_OUT}'[/]")

# ─────────── Console overview ───────────
def overview(sch: Dict[str, Any], ind: int = 0):
    pad = " " * ind
    for col, info in sch.items():
        rprint(f"{pad}📂 [bold]{col}[/]")
        tbl = Table(show_header=False, box=None, padding=(0,1))
        for field, meta in info["fields"].items():
            tbl.add_row(f"{pad}  • {field}", ", ".join(sorted(meta["types"])))
        if tbl.row_count:
            rprint(tbl)
        if info["subcols"]:
            overview(info["subcols"], ind + 2)

overview(root_schema)

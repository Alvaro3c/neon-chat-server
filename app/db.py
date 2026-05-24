"""Firestore client — module-level singleton.

Import ``db`` from here wherever Firestore access is needed.  Firebase Admin
*must* have been initialised before this module is first imported; that
happens as a side-effect of importing ``app.auth``, which is always done
earlier in the import chain (``app.ws.router`` pulls it in at the top).
"""
from firebase_admin import firestore

db = firestore.client()

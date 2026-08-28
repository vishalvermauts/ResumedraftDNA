import firebase_admin
import os
from firebase_admin import auth, credentials
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Initialize Firebase Admin
cred = credentials.Certificate("serviceAccountKey.json") # Need to ensure this is present in prod
firebase_admin.initialize_app(cred)

security = HTTPBearer()

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        token = credentials.credentials
        if os.getenv("LOCAL_AUTH_BYPASS") == "true" and token.startswith("dev-bypass"):
            # Local certification runs use the Firebase Auth emulator. Preserve the
            # emulator user's UID so API/Mongo/Celery writes land in the same user
            # partition that the browser reads.
            uid = token.partition(":")[2] or "dev-user-1"
            return {"uid": uid, "email": "dev@local.test"}
        decoded_token = auth.verify_id_token(token)
        return decoded_token
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        )

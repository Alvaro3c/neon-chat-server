To verify (Step 4)
Download your service account JSON from Firebase Console → Project Settings → Service Accounts → Generate new private key, save it as backend/service-account.json
Get a live token from the browser console after signing in:

await firebase.auth().currentUser.getIdToken(true)
Run from the backend/ directory:

python scripts/test_token.py <paste-token-here>
Test the error path:

python scripts/test_token.py garbage_string
Expected: ❌ Verification failed: ID token is invalid: … — no traceback.
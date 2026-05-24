You are building the FastAPI backend for a real-time emo/2007 chat app called
xX_DarkMessenger_Xx. Read every section carefully before writing a single line.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. PROJECT CONTEXT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

The app is a nostalgic MSN Messenger / AIM clone with a heavy emo/scene kid 2007
aesthetic. Think black backgrounds, neon cyan glows, skull emojis, and band names
in display names. The chat experience is centered around a draggable floating
window system — multiple chat windows can be open simultaneously on screen,
exactly like MSN Messenger.

CURRENT FRONTEND STACK:
  - React 18 + JSX (no TypeScript)
  - Plain CSS per component (no Tailwind)
  - Vite as bundler
  - Firebase Authentication (Google OAuth only)
  - Firebase Firestore for persistent data (user profiles, conversation metadata)
  - react-router-dom for routing
  - No real-time backend yet — messages are currently ephemeral React state

FIRESTORE SCHEMA (already in use, do not change):
  /users/{uid}
    name        : string   — Google display name
    email       : string   — Google email
    photoURL    : string   — Google profile photo URL
    createdAt   : timestamp

  /conversations/{conversationId}
    participants : [uid, uid]          — exactly two UIDs
    initiatedBy  : uid                 — who sent the request
    status       : 'pending' | 'active'
    createdAt    : timestamp

CURRENT MESSAGE SHAPE (frontend React state):
  {
    id        : string,          // e.g. "1717000000000-0.123"
    text      : string,
    sender    : 'me' | 'them',  // relative to the viewing user
    timestamp : Date,
    reaction  : string | undefined   // single emoji
  }

KEY FRONTEND BEHAVIORS TO KNOW:
  - ConversationSidebar has three tabs: All, Online, Requests (pending conversations)
  - Users can accept or decline conversation requests
  - Users can set their own status: online / away / busy / offline (+ funny custom options)
  - Users can edit their display nickname and mood message in the sidebar footer
  - ChatWindow is draggable, minimizable, and maximizable
  - Multiple ChatWindows can be open at the same time (openChats[] in ChatContext)
  - "New Conversation" flow: user types a contact's email → look up by email → create conversation


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2. BACKEND REQUIREMENTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

FRAMEWORK: FastAPI (Python 3.11+)
REAL-TIME:  WebSockets (built into FastAPI via Starlette)
PERSISTENCE: None — messages are ephemeral and exist only in server RAM while
             both participants are connected. No database for messages.
             Firestore remains the source of truth for user profiles and
             conversation metadata only (the frontend writes to it directly).

AUTHENTICATION:
  Every WebSocket client must authenticate using a Firebase ID token.
  On connection, the first message the client sends must be:
    { "type": "auth", "token": "<Firebase ID Token>" }
  The server verifies this token using the firebase-admin Python SDK.
  If verification fails, the server sends { "type": "auth_error", "message": "..." }
  and closes the connection.
  If verification succeeds, the server sends:
    { "type": "auth_ok", "uid": "...", "displayName": "...", "email": "...", "photoURL": "..." }

TOKEN REFRESH:
  Firebase ID tokens expire after 1 hour. The client may send at any time:
    { "type": "refresh_token", "token": "<new Firebase ID Token>" }
  The server re-verifies and responds with auth_ok or auth_error.
  This keeps long-lived sessions alive without disconnecting.

WEBSOCKET ARCHITECTURE — USE A SINGLE MULTIPLEXED CONNECTION:
  Each authenticated user opens exactly ONE WebSocket connection to the server,
  regardless of how many chat windows they have open simultaneously.
  Messages for all conversations flow over this single connection, distinguished
  by a conversationId field.
  Rationale: matches the MSN Messenger model, avoids connection-per-window
  overhead, and simplifies presence/status broadcasting.

CORS: Allow the Vite dev origin (http://localhost:5173) and the production
      frontend origin (configurable via env var). WebSocket upgrade requests
      must also pass CORS.

FIREBASE ADMIN SDK: Initialize with a service account JSON file whose path
is provided via the env var FIREBASE_SERVICE_ACCOUNT_PATH. Never hardcode
credentials.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3. FOLDER STRUCTURE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Create the backend as a sibling directory to the existing frontend:

  neon-chat/
  ├── frontend/          ← existing React app (do not touch)
  └── backend/           ← new FastAPI backend
      ├── app/
      │   ├── __init__.py
      │   ├── main.py            # FastAPI app instance + lifespan + CORS
      │   ├── config.py          # pydantic-settings Settings model (reads .env)
      │   ├── auth.py            # Firebase token verification helper
      │   ├── ws/
      │   │   ├── __init__.py
      │   │   ├── manager.py     # ConnectionManager: registry of active connections
      │   │   ├── router.py      # WebSocket endpoint /ws
      │   │   └── events.py      # All message type definitions (TypedDict or dataclasses)
      │   └── api/
      │       ├── __init__.py
      │       └── health.py      # GET /health
      ├── requirements.txt
      ├── .env                   # never committed
      └── .env.example           # committed template

RULES:
  - No single file longer than ~200 lines; split if needed
  - Type-annotate everything
  - Use async/await throughout (no blocking calls)
  - manager.py must be the only place that holds connection state


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
4. ENDPOINTS & WEBSOCKET EVENTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

── HTTP ENDPOINTS ────────────────────────────────────────

GET /health
  Response: { "status": "ok", "connected_users": <int> }
  No auth required.

── WEBSOCKET ENDPOINT ────────────────────────────────────

WS /ws
  Single persistent connection per user.
  All payloads are JSON objects with a mandatory "type" field (string).

── CLIENT → SERVER EVENTS ────────────────────────────────

{ "type": "auth",
  "token": "<Firebase ID token>" }
  → Must be the very first message. Server authenticates the user.

{ "type": "refresh_token",
  "token": "<new Firebase ID token>" }
  → Re-authenticate with a fresh token to prevent session expiry.

{ "type": "message",
  "conversationId": "<Firestore conversation doc ID>",
  "text": "<string, max 2000 chars>" }
  → Send a message to the other participant of the conversation.
    Server validates that the sender is in participants[] (via Firestore lookup).
    Server generates a server-side messageId and timestamp.

{ "type": "reaction",
  "conversationId": "<string>",
  "messageId": "<string>",
  "emoji": "<single emoji string>" }
  → Add/replace a reaction on a specific message.
    Server relays it to both participants.

{ "type": "typing",
  "conversationId": "<string>" }
  → Typing indicator. Server relays to the other participant only.
    No "stopped typing" event — frontend uses a 2-second debounce timer.

{ "type": "status_update",
  "status": "online" | "away" | "busy" | "offline" }
  → User changed their status. Server broadcasts to all users who share
    at least one active conversation with the sender.

{ "type": "mood_update",
  "mood": "<string, max 140 chars>" }
  → User changed their mood message. Same broadcast rules as status_update.

── SERVER → CLIENT EVENTS ────────────────────────────────

{ "type": "auth_ok",
  "uid": "<string>",
  "displayName": "<string>",
  "email": "<string>",
  "photoURL": "<string>" }

{ "type": "auth_error",
  "message": "<string>" }
  → Server closes the connection after sending this.

{ "type": "message",
  "conversationId": "<string>",
  "messageId": "<string>",     // server-generated UUID
  "senderUid": "<string>",
  "senderName": "<string>",
  "text": "<string>",
  "timestamp": "<ISO-8601 UTC string>" }
  → Delivered to BOTH participants (including the sender, for confirmation).

{ "type": "reaction",
  "conversationId": "<string>",
  "messageId": "<string>",
  "emoji": "<string>",
  "reactorUid": "<string>" }

{ "type": "typing",
  "conversationId": "<string>",
  "senderUid": "<string>" }
  → Delivered to the OTHER participant only.

{ "type": "contact_status",
  "uid": "<string>",
  "status": "online" | "away" | "busy" | "offline",
  "mood": "<string>" }
  → A contact came online, changed status, or disconnected.

{ "type": "error",
  "code": "<string>",           // e.g. "NOT_PARTICIPANT", "MESSAGE_TOO_LONG"
  "message": "<string>" }
  → Non-fatal error in response to a client action. Connection stays open.

── IMPLICIT PRESENCE EVENTS ──────────────────────────────
When a user connects and passes auth, the server broadcasts
{ "type": "contact_status", "uid": "...", "status": "online", "mood": "..." }
to all their known contacts who are currently connected.

When a user disconnects, the server broadcasts
{ "type": "contact_status", "uid": "...", "status": "offline", "mood": "" }
to those same contacts.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
5. FRONTEND INTEGRATION NOTES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

NEW ENV VARS — add to frontend/.env:
  VITE_WS_URL=ws://localhost:8000/ws

NEW FILE — src/services/chatSocket.js:
  Encapsulates all WebSocket logic. Exports:
    connect(idToken)              → opens WS, sends auth event
    disconnect()                  → clean close
    sendMessage(conversationId, text)
    sendReaction(conversationId, messageId, emoji)
    sendTyping(conversationId)
    updateStatus(status)
    updateMood(mood)
    refreshToken(newIdToken)
    onMessage(handler)            → register a callback for incoming events
    offMessage(handler)           → unregister
  Use a singleton pattern (one module-level WebSocket instance).
  Auto-reconnect with exponential backoff (max 5 retries).
  Before sending auth, call firebase.getIdToken(true) to get a fresh token.

CHANGES TO src/services/firebase.js:
  Export a new helper:
    export async function getIdToken() {
      const user = auth.currentUser
      if (!user) throw new Error('Not authenticated')
      return user.getIdToken(/* forceRefresh */ false)
    }
  No other changes needed — Firestore calls remain as-is.

CHANGES TO src/context/ChatContext.jsx:
  Replace the local sendMessage implementation with a call to
  chatSocket.sendMessage(conversationId, text).
  Replace the local addReaction implementation with chatSocket.sendReaction(...).
  Listen for incoming events via chatSocket.onMessage and dispatch them into
  the existing messages state. The message payload from the server maps to:
    { id: messageId, text, sender: senderUid === currentUser.uid ? 'me' : 'them',
      timestamp: new Date(timestamp) }

CHANGES TO src/context/AuthContext.jsx:
  After onAuthStateChanged resolves a logged-in user:
    const token = await getIdToken()
    chatSocket.connect(token)
  On signOut:
    chatSocket.disconnect()

CHANGES TO src/components/features/ConversationSidebar/index.jsx:
  Contact status dots (online/away/busy/offline) should be driven by
  contact_status events from the WebSocket, not hardcoded mock data.
  Store live statuses in a contactStatuses map in ChatContext.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
6. IMPLEMENTATION ORDER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Build and verify each step before moving to the next.
The frontend should remain functional (with mock data) throughout.

STEP 1 — Project scaffold
  Create backend/ with the folder structure from section 3.
  Write requirements.txt:
    fastapi>=0.111
    uvicorn[standard]>=0.29
    firebase-admin>=6.5
    pydantic-settings>=2.2
    python-dotenv>=1.0
  Create .env.example with all required vars.
  Verify: uvicorn app.main:app --reload starts without errors.

STEP 2 — Health endpoint
  Implement GET /health → { "status": "ok", "connected_users": 0 }.
  Verify: curl http://localhost:8000/health returns 200.

STEP 3 — Firebase Admin init
  In app/auth.py, initialize firebase_admin with the service account.
  Write verify_id_token(token: str) -> dict (returns decoded token claims).
  Verify: write a one-off test script that calls verify_id_token with a
  real token grabbed from the browser console (firebase.auth().currentUser.getIdToken()).

STEP 4 — ConnectionManager
  In app/ws/manager.py implement ConnectionManager:
    - connect(uid, websocket)
    - disconnect(uid)
    - send_to(uid, payload: dict)
    - broadcast_to(uids: list[str], payload: dict)
    - get_connected_uids() -> list[str]
    - get_user_data(uid) -> dict | None   (stores displayName, photoURL, status, mood)
  All state is a plain dict in memory (no Redis yet).
  Verify: unit test connect/disconnect/send logic with mock WebSocket objects.

STEP 5 — WebSocket endpoint (auth only)
  In app/ws/router.py add WS /ws.
  Handle the auth handshake:
    - Accept the connection
    - Wait for the first message (5-second timeout, else close)
    - Call verify_id_token; on failure send auth_error and close
    - On success register in ConnectionManager, send auth_ok
    - Broadcast contact_status online to known contacts
    - On disconnect broadcast contact_status offline
  Verify: connect from the browser console with a valid Firebase token and
  confirm auth_ok is received.

STEP 6 — Message relay
  Handle incoming { type: "message" } events:
    - Validate text length (max 2000 chars)
    - Look up the conversation in Firestore to confirm the sender is a participant
      and status is 'active'
    - Generate a UUID messageId and UTC timestamp
    - Call manager.send_to(uid, payload) for BOTH participants (sender gets confirmation)
  Verify: open two browser tabs, each signed in as a different user with an
  active conversation. Send a message from tab A and confirm it appears in tab B.

STEP 7 — Typing indicators
  Handle { type: "typing" } — relay to the other participant only.
  Verify: typing in one window shows a typing indicator in the other
  (wire up a simple console.log on the frontend side for now).

STEP 8 — Reactions
  Handle { type: "reaction" } — relay to both participants.
  Verify: clicking a reaction in one window updates it in the other.

STEP 9 — Status & mood updates
  Handle { type: "status_update" } and { type: "mood_update" }.
  For each, fetch all conversations where the sender is a participant (Firestore
  query), collect the other participant UIDs that are currently connected, and
  broadcast contact_status to them.
  Verify: changing status in one tab updates the contact dot in the other tab.

STEP 10 — Token refresh
  Handle { type: "refresh_token" } — re-verify the new token.
  On success, update the stored user data in ConnectionManager and respond with auth_ok.
  On failure, send auth_error but keep the connection open (the client will retry).
  Verify: simulate an expired token scenario using a token with a very short TTL.

STEP 11 — Frontend wiring
  Implement src/services/chatSocket.js as described in section 5.
  Wire ChatContext.sendMessage and addReaction through the socket.
  Wire AuthContext to call connect/disconnect.
  Verify: full end-to-end test — two users, send messages, reactions,
  status changes, all flowing over the WebSocket with no mock data.

STEP 12 — Hardening
  Add input validation (Pydantic models) to every incoming event type.
  Add a global exception handler so unhandled errors send { type: "error" }
  instead of crashing the connection.
  Add structured logging (use Python's logging module, not print).
  Verify: send a malformed payload and confirm the connection survives.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ENV VAR REFERENCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

backend/.env:
  FIREBASE_SERVICE_ACCOUNT_PATH=./service-account.json
  ALLOWED_ORIGINS=http://localhost:5173,https://your-prod-domain.com
  HOST=0.0.0.0
  PORT=8000

frontend/.env (additions):
  VITE_WS_URL=ws://localhost:8000/ws

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HARD CONSTRAINTS — NEVER VIOLATE THESE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  - No message database. Messages live only in server RAM during the session.
  - No hardcoded credentials or Firebase keys anywhere.
  - Do not modify the Firestore schema or write to Firestore from the backend
    (the frontend owns Firestore writes).
  - One WebSocket connection per user — never one per conversation.
  - All async — no synchronous I/O or blocking calls.
  - Keep the frontend working with its existing mock data until Step 11.
# Neon Chat — Backend

Backend en tiempo real para **Neon Chat**, un cliente de mensajería inspirado en la estética emo/MSN Messenger de 2007. Gestiona conexiones WebSocket multiplexadas, autenticación con Firebase y presencia de usuarios en tiempo real.

![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-009688?logo=fastapi&logoColor=white)
![Firebase](https://img.shields.io/badge/Firebase-Admin_SDK-FFCA28?logo=firebase&logoColor=black)
![License](https://img.shields.io/badge/license-MIT-green)

---

## Descripción general

El backend expone un único endpoint WebSocket (`/ws`) que actúa como canal multiplexado para todos los eventos de chat de un usuario: mensajes, indicadores de escritura, reacciones, buzzes y actualizaciones de presencia. Los mensajes son **efímeros** (almacenados en RAM, no persistidos); Firestore se usa exclusivamente para metadata de conversaciones y usuarios.

---

## Tech Stack

| Tecnología | Rol |
|---|---|
| **FastAPI** | Framework web asincrónico |
| **Uvicorn** | Servidor ASGI |
| **Firebase Admin SDK** | Verificación de ID tokens y acceso a Firestore |
| **Google Firestore** | Metadata de conversaciones y usuarios |
| **Pydantic v2** | Validación de eventos WebSocket |
| **pydantic-settings** | Configuración desde variables de entorno |
| **asyncio** | I/O no bloqueante |

---

## Arquitectura

```
Cliente (React + Firebase Auth)
        │
        │  Firebase ID Token (JWT)
        ▼
┌──────────────────────────────┐
│          FastAPI             │
│                              │
│   GET /health                │
│   WS  /ws  ◄──── único WS por usuario, eventos multiplexados
│                              │
│   ConnectionManager (RAM)    │  ← WebSocket connections + user metadata
│                              │
│   Firestore (read-only)      │  ← conversaciones, participantes
└──────────────────────────────┘
```

**Principios clave:**

- **Un WebSocket por usuario**, no uno por conversación. El campo `conversationId` en el payload distingue el contexto.
- **Mensajes efímeros**: el servidor relaya mensajes en tiempo real pero no los persiste. El historial vive en el frontend (Firestore).
- **Firestore en lectura**: el backend consulta Firestore para validar membresía en conversaciones y resolver contactos para broadcast de presencia. El frontend escribe en Firestore.
- **Presencia broadcast**: al conectar, desconectar o cambiar estado, el servidor notifica en tiempo real a todos los contactos conectados que comparten al menos una conversación activa.

---

## WebSocket Protocol

### Conexión y autenticación

Tras abrir la conexión en `ws://<host>/ws`, el cliente tiene **5 segundos** para enviar un evento `auth`. Si no lo hace, la conexión se cierra.

```json
// Cliente → Servidor
{ "type": "auth", "token": "<Firebase ID Token>" }

// Servidor → Cliente (éxito)
{
  "type": "auth_ok",
  "uid": "uid123",
  "displayName": "xX_darkUser_Xx",
  "email": "user@example.com",
  "photoURL": "https://..."
}

// Servidor → Cliente (fallo)
{ "type": "auth_error", "reason": "Token inválido o expirado" }
```

---

### Eventos que envía el cliente

| Tipo | Payload requerido | Notas |
|---|---|---|
| `auth` | `token` | Primer mensaje obligatorio |
| `message` | `conversationId`, `text` | Máx. 2000 caracteres |
| `typing` | `conversationId` | Best-effort, no genera error |
| `reaction` | `conversationId`, `messageId`, `emoji` | Emoji máx. 10 chars |
| `buzz` | `conversationId` | Best-effort |
| `status_update` | `status` | `"online"`, `"away"`, `"busy"`, `"offline"` u otro string custom |
| `mood_update` | `mood` | Máx. 140 caracteres |
| `profile_update` | `displayName` | Máx. 100 caracteres |
| `refresh_token` | `token` | Renueva el token de autenticación sin reconectar |

---

### Eventos que emite el servidor

| Tipo | Descripción | Destinatarios |
|---|---|---|
| `auth_ok` | Autenticación correcta | Sender |
| `auth_error` | Autenticación fallida | Sender |
| `message` | Mensaje de chat con UUID y timestamp UTC | Todos los participantes (incluido sender) |
| `typing` | Indicador de escritura | Otros participantes |
| `reaction` | Reacción emoji a un mensaje | Todos los participantes |
| `buzz` | Poke / notificación | Otros participantes |
| `contact_status` | Cambio de presencia, estado o mood de un contacto | Contactos conectados |
| `contact_profile` | Cambio de nickname o foto de un contacto | Contactos conectados |
| `error` | Error de negocio (conversación no encontrada, no autorizado, etc.) | Sender |

**Ejemplo — evento `message` emitido por el servidor:**

```json
{
  "type": "message",
  "messageId": "550e8400-e29b-41d4-a716-446655440000",
  "conversationId": "conv_abc123",
  "senderUid": "uid123",
  "senderName": "xX_darkUser_Xx",
  "text": "oye sigues ahí?",
  "timestamp": "2024-11-01T21:30:00.000Z"
}
```

**Ejemplo — evento `contact_status`:**

```json
{
  "type": "contact_status",
  "uid": "uid456",
  "status": "away",
  "mood": "escuchando MCR",
  "online": true
}
```

---

## Variables de entorno

Crea un archivo `.env` en la raíz del proyecto. Puedes usar `.env.example` como base:

| Variable | Requerida | Descripción | Ejemplo |
|---|---|---|---|
| `HOST` | No | Dirección de escucha | `0.0.0.0` |
| `PORT` | No | Puerto del servidor | `8000` |
| `ALLOWED_ORIGINS` | Sí | CORS: orígenes permitidos, separados por coma | `http://localhost:5173,https://tu-app.vercel.app` |
| `FIREBASE_SERVICE_ACCOUNT_PATH` | Sí* | Ruta al archivo `service-account.json` (desarrollo) | `./service-account.json` |
| `FIREBASE_SERVICE_ACCOUNT_JSON` | Sí* | Contenido JSON de las credenciales en string (producción) | `{"type":"service_account",...}` |

*Una de las dos variables de credenciales Firebase es obligatoria. `FIREBASE_SERVICE_ACCOUNT_JSON` tiene prioridad sobre `FIREBASE_SERVICE_ACCOUNT_PATH`.

---

## Instalación y ejecución local

### Prerrequisitos

- Python 3.11+
- Una proyecto Firebase con Firestore habilitado
- El archivo `service-account.json` descargado desde Firebase Console → Configuración del proyecto → Cuentas de servicio

### Pasos

```bash
# 1. Clonar el repositorio
git clone https://github.com/tu-usuario/neon-chat-backend.git
cd neon-chat-backend

# 2. Crear y activar entorno virtual
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Configurar variables de entorno
cp .env.example .env
# Edita .env con tus valores

# 5. Colocar las credenciales de Firebase
# Descarga service-account.json desde Firebase Console y colócalo en la raíz

# 6. Ejecutar el servidor
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

El servidor estará disponible en `http://localhost:8000`.

---

## Endpoints HTTP

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| `GET` | `/health` | No | Estado del servidor y número de usuarios conectados |
| `WS` | `/ws` | Firebase ID Token | Canal WebSocket principal |

**Respuesta de `/health`:**

```json
{
  "status": "ok",
  "connected_users": 3
}
```

---

## Testing

### Tests unitarios

```bash
pytest
```

Los tests en `tests/` cubren validación de schemas Pydantic (valores de status canónicos, valores custom, límites de longitud).

### Verificación de token Firebase

Para comprobar que las credenciales de Firebase están bien configuradas:

```bash
python scripts/test_token.py <firebase-id-token>
```

Obtén un token válido desde el frontend: en la consola del navegador, ejecuta `await firebase.auth().currentUser.getIdToken()`.

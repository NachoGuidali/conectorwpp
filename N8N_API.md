# Waply — Documentación de API para n8n

**Base URL:** `https://ras.supregsolutions.com`

---

## Índice

- [Autenticación](#autenticación)
- [Webhook entrante (trigger)](#webhook-entrante-trigger)
- [Enviar mensajes](#enviar-mensajes)
- [Handoff bot → agente](#handoff-bot--agente)
- [Flujo típico en n8n](#flujo-típico-en-n8n)
- [Configuración en n8n](#configuración-en-n8n)
- [Errores comunes](#errores-comunes)

---

## Autenticación

Todos los endpoints de API requieren el header:

```
X-Api-Key: TU_CRM_API_KEY
Content-Type: application/json
```

El valor de `CRM_API_KEY` está configurado en el `.env` del servidor.  
Generarlo con: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`

---

## Webhook entrante (trigger)

Evolution API llama automáticamente a este endpoint cuando llega un mensaje de WhatsApp.  
Configurarlo en n8n como nodo **Webhook** o **HTTP Request** de tipo trigger.

### URL del webhook
```
POST https://ras.supregsolutions.com/whatsapp/webhook/
```

### Header requerido por Evolution API
```
apikey: TU_WHATSAPP_WEBHOOK_TOKEN
```

> **Nota:** `WHATSAPP_WEBHOOK_TOKEN` y `CRM_API_KEY` son claves distintas.  
> El webhook token lo usa Evolution API para autenticarse con el CRM.  
> El API key lo usa n8n para llamar a los endpoints del CRM.

---

### Payload — Mensaje de texto entrante

```json
{
  "event": "message_received",
  "phone": "+5491122334455",
  "contact_name": "Juan García",
  "message": "Hola, necesito información",
  "message_type": "text",
  "message_id": "3AB0DF989633B9AF",
  "conversation_id": 42,
  "timestamp": "2026-06-04T10:30:00",
  "crm_reply_url": "https://ras.supregsolutions.com/whatsapp/api/enviar/",
  "crm_api_key": "TU_CRM_API_KEY"
}
```

### Payload — Imagen / audio / documento entrante

```json
{
  "event": "message_received",
  "phone": "+5491122334455",
  "contact_name": "Juan García",
  "message": "caption del archivo (si tiene)",
  "message_type": "image",
  "message_id": "3AB0DF989633B9AF",
  "conversation_id": 42,
  "timestamp": "2026-06-04T10:30:00",
  "crm_reply_url": "https://ras.supregsolutions.com/whatsapp/api/enviar/",
  "crm_api_key": "TU_CRM_API_KEY"
}
```

`message_type` puede ser: `text` | `image` | `audio` | `video` | `document` | `sticker`

### Campos importantes del payload

| Campo | Tipo | Descripción |
|---|---|---|
| `conversation_id` | number | ID de la conversación en el CRM — guardar para usar en handoff |
| `phone` | string | Teléfono con código de país |
| `contact_name` | string | Nombre del contacto si existe en la base |
| `message` | string | Texto del mensaje o caption del archivo |
| `message_type` | string | Tipo de mensaje |
| `crm_reply_url` | string | URL para responder (siempre `/whatsapp/api/enviar/`) |
| `crm_api_key` | string | La misma key del CRM, incluida para comodidad |

---

## Enviar mensajes

### Enviar texto
```
POST /whatsapp/api/enviar/
```

**Body:**
```json
{
  "phone": "+5491122334455",
  "message": "Hola, ¿cómo te puedo ayudar?"
}
```

**Respuesta exitosa:**
```json
{
  "ok": true,
  "message_id": "3AB0DF989633B9AF",
  "conversacion_id": 42
}
```

**Respuesta de error:**
```json
{
  "ok": false,
  "error": "descripción del error"
}
```

---

### Enviar imagen
```
POST /whatsapp/api/enviar/
```

```json
{
  "phone": "+5491122334455",
  "message": "Mirá esta imagen",
  "media_url": "https://ejemplo.com/imagen.jpg",
  "media_type": "image"
}
```

---

### Enviar documento / PDF
```
POST /whatsapp/api/enviar/
```

```json
{
  "phone": "+5491122334455",
  "message": "Adjunto tu presupuesto",
  "media_url": "https://ejemplo.com/presupuesto.pdf",
  "media_type": "document"
}
```

---

### Enviar audio
```
POST /whatsapp/api/enviar/
```

```json
{
  "phone": "+5491122334455",
  "media_url": "https://ejemplo.com/audio.mp3",
  "media_type": "audio"
}
```

---

### Enviar video
```
POST /whatsapp/api/enviar/
```

```json
{
  "phone": "+5491122334455",
  "message": "Mirá este video",
  "media_url": "https://ejemplo.com/video.mp4",
  "media_type": "video"
}
```

### Valores de `media_type`

| Valor | Descripción |
|---|---|
| `image` | Imagen (jpg, png, gif, webp) |
| `document` | Documento (pdf, docx, xlsx, etc.) |
| `audio` | Audio (mp3, ogg, wav) |
| `video` | Video (mp4, 3gp) |

---

## Handoff bot → agente

Llamar cuando el bot termina la atención y quiere que un agente humano tome la conversación.

```
POST /whatsapp/api/handoff/
```

**Por conversation_id (recomendado):**
```json
{
  "conversation_id": 42
}
```

**Por teléfono (alternativo):**
```json
{
  "phone": "+5491122334455"
}
```

**Respuesta exitosa:**
```json
{
  "ok": true,
  "conversation_id": 42,
  "estado": "pendiente"
}
```

**Respuesta si no se encuentra la conversación:**
```json
{
  "ok": false,
  "error": "Conversación no encontrada"
}
```

### Qué hace el handoff en el CRM

1. Desactiva el bot (`bot_n8n_activo = false`)
2. Cambia el estado de la conversación a **Pendiente de agente**
3. El agente asignado recibe una notificación en tiempo real con badge **LISTO** y sonido
4. La conversación sube al tope de la lista del agente
5. El título del tab del navegador parpadea con el nombre del contacto
6. Cuando el agente abre la conversación, el estado cambia a **Abierta**

---

## Flujo típico en n8n

```
┌─────────────────────────────────────────────────────┐
│  Webhook trigger                                     │
│  Recibe payload con conversation_id, phone, message  │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│  Set node                                            │
│  Guardar: conversation_id, phone, contact_name       │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│  Switch / IF                                         │
│  Según el contenido del mensaje, decidir qué hacer   │
└──────────┬──────────────────────┬───────────────────┘
           │                      │
           ▼                      ▼
    [Respuesta 1]           [Respuesta 2]
           │                      │
           └──────────┬───────────┘
                      ▼
┌─────────────────────────────────────────────────────┐
│  HTTP Request — Enviar mensaje                       │
│  POST /whatsapp/api/enviar/                          │
│  Body: { phone, message }                            │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│  [Cuando el bot termina]                             │
│  HTTP Request — Mensaje de cierre                    │
│  Body: { phone, message: "Un asesor te contacta..." }│
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│  HTTP Request — Handoff                              │
│  POST /whatsapp/api/handoff/                         │
│  Body: { conversation_id }                           │
└─────────────────────────────────────────────────────┘
```

---

## Configuración en n8n

### Credencial reutilizable (recomendado)

Crear una credencial de tipo **Header Auth**:
- **Name:** `X-Api-Key`
- **Value:** `TU_CRM_API_KEY`

Usar esta credencial en todos los nodos HTTP Request que llamen al CRM.

### Nodo HTTP Request — configuración base

| Campo | Valor |
|---|---|
| Method | `POST` |
| URL | `https://ras.supregsolutions.com/whatsapp/api/enviar/` |
| Authentication | Header Auth → credencial creada arriba |
| Body Content Type | `JSON` |
| Send Body | ✅ |

### Webhook trigger — configuración

| Campo | Valor |
|---|---|
| HTTP Method | `POST` |
| Path | `/webhook-waply` (o el que elijas en n8n) |

> **Importante:** La URL que hay que registrar en el CRM (Configuración → Guardar webhook) es la URL **de Evolution API hacia el CRM**, no la URL del webhook de n8n.  
> El flujo es: `WhatsApp → Evolution API → CRM → n8n`  
> El CRM llama a n8n usando la `N8N_WEBHOOK_URL` del `.env`.

---

## Variables de entorno del CRM relacionadas

```env
# n8n
N8N_WEBHOOK_URL=https://tu-n8n.com/webhook/tu-trigger-id

# Clave para que n8n llame al CRM
CRM_API_KEY=un-token-largo-y-secreto

# Clave para que Evolution API llame al webhook del CRM
WHATSAPP_WEBHOOK_TOKEN=otro-token-secreto
```

---

## Errores comunes

| Error | Causa | Solución |
|---|---|---|
| `401 Unauthorized` | `X-Api-Key` incorrecto o faltante | Verificar que `CRM_API_KEY` en `.env` coincide con el header |
| `404 Not Found` | `conversation_id` no existe | Verificar que se guardó el ID del webhook inicial |
| `400 Bad Request` | JSON malformado o campo faltante | Verificar que `phone` tiene código de país (+549...) |
| `500 Internal Server Error` | Error en Evolution API | Verificar que WhatsApp está conectado en Configuración |

---

## Referencia rápida

```
# Enviar texto
POST /whatsapp/api/enviar/
{ "phone": "+549...", "message": "..." }

# Enviar archivo
POST /whatsapp/api/enviar/
{ "phone": "+549...", "message": "caption", "media_url": "https://...", "media_type": "document" }

# Handoff al agente
POST /whatsapp/api/handoff/
{ "conversation_id": 42 }
```

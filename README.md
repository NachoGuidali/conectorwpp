# Waply — Plataforma WhatsApp Multi-agente

Plataforma de WhatsApp tipo WATI, construida con Django + Evolution API (sin verificación de Meta).

## Stack

- **Backend:** Django 5.1 + Celery + Redis
- **DB:** PostgreSQL 15
- **WhatsApp:** Evolution API (Baileys)
- **Frontend:** Django Templates (sin frameworks JS)
- **Infra:** Docker + docker-compose

## Setup rápido

### 1. Clonar y configurar variables de entorno

```bash
cp .env.example .env
# Editar .env con tus datos
```

### 2. Levantar servicios

```bash
docker-compose up --build
```

### 3. Crear superusuario (admin)

```bash
docker-compose exec web python manage.py createsuperuser
```

### 4. Acceder

- **App:** http://localhost:8000
- **Admin:** http://localhost:8000/admin

## Roles de usuario

| Rol | Permisos |
|---|---|
| `admin` | Todo, incluyendo gestión de usuarios |
| `supervisor` | Ve todas las conversaciones, puede reasignar agentes, configura Evolution API |
| `agente` | Solo sus conversaciones asignadas |

## Módulos

| Módulo | URL | Descripción |
|---|---|---|
| Inbox | `/whatsapp/inbox/` | Bandeja principal multi-agente |
| Plantillas | `/whatsapp/plantillas/` | Plantillas de mensajes |
| Config | `/whatsapp/config/` | Evolution API + QR de conexión |
| Usuarios | `/usuarios/` | ABM de usuarios y roles |

## Conectar WhatsApp

1. Ir a `/whatsapp/config/`
2. Configurar URL y API Key de Evolution API
3. Escanear el QR con WhatsApp → Dispositivos vinculados

## API para n8n

```http
POST /whatsapp/api/enviar/
X-Api-Key: <CRM_API_KEY>
Content-Type: application/json

{"phone": "+5491112345678", "message": "Hola!"}
```

## Variables de entorno

| Variable | Descripción |
|---|---|
| `SECRET_KEY` | Clave secreta Django |
| `POSTGRES_*` | Credenciales PostgreSQL |
| `REDIS_URL` | URL de Redis |
| `EVOLUTION_API_URL` | URL de Evolution API |
| `EVOLUTION_API_KEY` | API Key de Evolution API |
| `EVOLUTION_INSTANCE_NAME` | Nombre de la instancia (default: waply) |
| `WHATSAPP_WEBHOOK_TOKEN` | Token para verificar webhooks |
| `N8N_WEBHOOK_URL` | URL de n8n (opcional) |
| `CRM_API_KEY` | API Key para envío externo desde n8n |

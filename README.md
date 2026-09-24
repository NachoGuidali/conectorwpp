# SPwap — Plataforma WhatsApp Multi-agente

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
| Pipeline | `/contactos/pipeline/` | Kanban de contactos por etapa. Cada agente ve solo sus contactos |
| Etapas | `/contactos/etapas/` | Etapas del pipeline (solo admin) |
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

## Agente dueño del contacto

Todo contacto y toda conversación tienen un agente, y es el mismo para ambos:

- **Entrantes:** van al dueño del contacto; si no tiene, al agente con menos carga.
- **Salientes** (nueva conversación, deep link, API, difusiones): quedan para el agente que las
  inicia, salvo que el contacto ya tenga dueño, que lo conserva.
- **Solo un supervisor** cambia el dueño (inbox, ficha del contacto o dashboard).
- Al **desactivar o borrar** un agente, toda su cartera se reparte entre los demás.
- Una tarea periódica (cada 10 min) asigna cualquier conversación que haya quedado sin agente.

La lógica vive en `apps/contacts/asignacion.py`. Para revisar datos viejos:

```bash
python manage.py asignar_sin_agente            # diagnóstico, no cambia nada
python manage.py asignar_sin_agente --aplicar  # asigna lo huérfano repartiendo por carga
python manage.py asignar_sin_agente --aplicar --agente <username>  # todo a un agente
```

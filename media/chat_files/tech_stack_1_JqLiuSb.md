# Channel-Based Communication System
## Tech Stack Reference

> This document defines the complete technology stack for the communication platform. It is intended as a reference for the coding agent, architects, and developers. All decisions here are final unless marked as TBD.

> **Target Scale:** 200–300 concurrent users. Architecture decisions are optimised for this scale — simplicity and maintainability are prioritised over hyperscale complexity.

---

## 1. Stack Summary

| Layer | Technology |
|---|---|
| Frontend Framework | Next.js (React) |
| Frontend Language | TypeScript |
| UI Library | Tailwind CSS + ShadCN UI |
| Frontend State | Zustand |
| Server State / Data Fetching | TanStack Query |
| Backend Framework | Django + Django REST Framework |
| Realtime Layer | Django Channels (ASGI) |
| ASGI Server | Daphne or Uvicorn |
| WebSocket Broker | Redis |
| Session Store | Redis |
| Database | PostgreSQL |
| Background Jobs | Celery + Redis |
| Authentication | Session-based auth (HttpOnly cookies) |
| File Storage | Local (dev) / S3-compatible (prod) |
| Reverse Proxy | Nginx |
| Containerisation | Docker + Docker Compose |
| Monitoring | Sentry + Grafana + Prometheus (optional initially) |
| Deployment | AWS / Hetzner / DigitalOcean |

---

## 2. Architecture Style

**Modular Monolith** — one codebase, one deployment, one database, internally separated by business domain.

### Why Not Microservices
Microservices introduce distributed transactions, network failures, service discovery, and DevOps overhead. For this project the data is highly relational (users ↔ channels ↔ permissions ↔ memberships) and business rules are tightly shared across domains. A modular monolith gives enterprise-grade organisation without that complexity.

Microservices can be considered later only if there are genuine independent scaling needs (e.g. notifications at 10M+ users).

### Monorepo Structure
```
project/
├── backend/
│   ├── apps/
│   │   ├── accounts/
│   │   ├── channels_app/
│   │   ├── messaging/
│   │   ├── dms/
│   │   ├── notifications/
│   │   ├── attachments/
│   │   ├── websocket/
│   │   └── permissions/
│   ├── config/
│   └── requirements/
│
├── frontend/
│   ├── app/
│   ├── components/
│   ├── stores/
│   ├── hooks/
│   └── services/
│
├── docker/
├── nginx/
└── docs/
```

Each backend app owns its own `models.py`, `services.py`, `serializers.py`, `views.py`, `urls.py`, and `permissions.py`. Business logic lives in `services.py`, not in views.

---

## 3. Frontend

### 3.1 Next.js + TypeScript
**Next.js** is used as a structured React framework, not as an SSR/SEO platform. It provides:
- Built-in routing and layouts
- Middleware for auth guards and role-based access
- Scalable project architecture
- Enterprise-grade ecosystem

**TypeScript** is mandatory. This system has many API payloads, WebSocket event types, permission schemas, and notification structures. TypeScript prevents payload mismatches, permission bugs, and websocket event errors at compile time.

> Alternative considered: Vite + React (lighter but weaker structure for enterprise scale). Next.js is the better long-term choice here.

### 3.2 Tailwind CSS + ShadCN UI
Best combination for rapidly building:
- Admin dashboards
- Channel sidebars
- Notification panels
- Modals and forms
- Role-based layout components

### 3.3 Zustand — UI State Management
Zustand manages **frontend UI state** — lightweight, no boilerplate, no Redux overhead.

**What Zustand stores in this app:**
| Store | Contents |
|---|---|
| Auth store | current user, role, session |
| Channel store | active channel, sidebar state |
| WebSocket store | connection status, event queue |
| Notification store | unread counts, popup state |
| DM store | active DM thread |

**What Zustand does NOT store:** server data (messages, channel lists, API responses). That is TanStack Query's responsibility.

### 3.4 TanStack Query — Server State Management
TanStack Query manages **server state** — all data that comes from the API.

**What it handles automatically:**
- Response caching
- Pagination and infinite scroll (for message history)
- Loading and error states
- Background refetching
- Optimistic updates
- Request deduplication

**Used for:**
- `/channels/{id}/messages/` — paginated message history
- `/channels/` — channel list
- `/notifications/` — notification feed
- `/dms/{user_id}/` — DM history

---

## 4. Backend

### 4.1 Django + Django REST Framework
Django is the ideal backend framework for this system because the application is:
- RBAC-heavy (three roles with complex permissions)
- Relational-data-heavy (memberships, channels, DMs, notifications)
- Admin-workflow-heavy (user creation, role assignment, archiving)
- Audit-sensitive (persistent messages, immutable history)

DRF adds structured serializers, validation, permission classes, pagination, and auto-generated OpenAPI/Swagger documentation.

> FastAPI was considered and rejected for this project. FastAPI excels at high-performance API-first microservices and ML inference. Django is the stronger choice for enterprise business systems with complex RBAC, admin tooling, and relational workflows.

### 4.2 Backend Module Responsibilities

| Module | Owns |
|---|---|
| `accounts` | Auth, user lifecycle, role management, permissions |
| `channels_app` | Channel creation, archiving, renaming, visibility rules |
| `memberships` | Channel assignment, implicit Management membership |
| `messaging` | Message creation, broadcast logic, retrieval, websocket events |
| `dms` | Direct message creation, inbox, thread history |
| `notifications` | Notification creation, delivery, read status, offline queuing |
| `attachments` | File upload handling, file type validation, storage routing |
| `websocket` | Consumer definitions, group management, event dispatch |
| `permissions` | Shared permission classes used across modules |

**Key principle:** modules communicate through service functions, not by importing each other's models directly.

---

## 5. Realtime Layer

### 5.1 Django Channels
Normal Django handles a request → response → close-connection cycle. Chat systems need persistent two-way connections. Django Channels extends Django to support WebSockets using ASGI.

**Channels concepts used:**
- **Consumers** — async WebSocket controllers (connect, disconnect, receive, send)
- **Channel Groups** — logical groups per channel room (e.g. `channel_42`); all members of a channel join the same group
- **ASGI** — replaces WSGI to support async + WebSocket traffic

### 5.2 Redis as WebSocket Broker
Redis acts as the pub/sub layer between multiple ASGI workers. Without Redis, a message received by worker A cannot be pushed to a user connected to worker B. Redis solves this by routing events across all workers.

Redis is also used for:
- Session storage
- Celery task queue
- Caching

### 5.3 Realtime Message Delivery Flow
```
User sends message
       ↓
Django saves message to PostgreSQL
       ↓
Django Channels publishes event
       ↓
Redis distributes event via Pub/Sub
       ↓
Connected users receive WebSocket update instantly
```

> **Important:** Celery is NOT responsible for realtime message delivery. Realtime delivery is handled entirely by Django Channels + Redis WebSocket pub/sub. Celery handles only background and async tasks (see Section 8).

### 5.4 Server Architecture
At the target scale of 200–300 users, a separate Gunicorn process is not required. Daphne or Uvicorn (ASGI servers) handle both HTTP and WebSocket traffic cleanly.

```
Browser
   ↓
Nginx
   ↓
Daphne / Uvicorn  (handles both HTTP + WebSocket)
   ↓
Django + Channels
   ↓
Redis
   ↓
PostgreSQL
```

**Nginx routing:**
```
Nginx
 ├── /api/  → Daphne  (REST over HTTP)
 └── /ws/   → Daphne  (WebSocket / ASGI)
```

A separate Gunicorn layer can be introduced later if REST and WebSocket traffic need to scale independently, but it is unnecessary at this stage.

---

## 6. Authentication & Sessions

### Strategy: Session-Based Auth with Redis-Backed Sessions

| Property | Decision |
|---|---|
| Mechanism | Username + password |
| Session storage | Redis |
| Cookie type | HttpOnly (secure) |
| CSRF protection | Enabled |
| Session lifetime | 24-hour inactivity timeout |
| On inactivity (24h) | Session expires, re-login required |
| On browser/tab close | Session remains active (user does not need to re-login) |
| Remember me | Not implemented |
| SSO / OAuth | Out of scope for current phase |

> **Session decision rationale:** A 24-hour inactivity timeout gives better UX than logout-on-tab-close. For a workplace communication tool where users switch tabs and return throughout the day, forcing re-login on every tab close would be disruptive. The 24h window is long enough to cover a full working day, while still enforcing session expiry for security.

### Why Session Auth Over JWT
- Easier session invalidation (deactivate a user → their session is immediately killed)
- Simpler WebSocket integration (Channels can read the session cookie directly)
- Better security for internal enterprise apps
- No token refresh complexity

---

## 7. Database

### PostgreSQL
The application is highly relational:
- Users ↔ Channels (via memberships)
- Messages → Channels → Users
- Notifications → Users
- Attachments → Messages or DirectMessages
- Role-based access across all entities

PostgreSQL handles all of this with full transactional consistency.

**Schema design decisions:**
- UUID primary keys on all tables
- Soft delete pattern (`is_active`, `archived_at`) — no hard deletes
- `deleted_at` / `deleted_by` fields reserved for future compliance/audit use
- GIN index on message content field to be added when full-text search is introduced

---

## 8. Background Jobs

### Celery + Redis
Celery handles async background tasks that must not block API responses. It is **not** used for realtime message delivery — that is handled by Django Channels + Redis pub/sub.

**Current use cases:**
- Broadcast fanout to large channel sets
- Notification delivery (offline queuing, retry logic)
- File processing after upload

**Future use cases:**
- Audit log writes
- Email alerts
- Scheduled cleanup jobs
- Analytics aggregation
- AI-related async tasks

---

## 9. File Storage

| Environment | Storage |
|---|---|
| Development | Local filesystem |
| Production | S3-compatible (AWS S3 / Cloudflare R2 / MinIO) |

Local storage is not used in production because it breaks in containerised and multi-replica environments. S3-compatible storage solves persistence, scaling, and multi-server access.

Supported file types: `PDF`, `DOC`, `DOCX`, `XLS`, `XLSX`, `PPT`, `PPTX`, `PNG`, `JPG`, `JPEG`, `GIF`

File size and storage quota limits: **not defined — to be decided.**

---

## 10. Reverse Proxy — Nginx

Nginx sits between users and the backend. It handles:

| Function | Detail |
|---|---|
| SSL termination | Handles HTTPS, encrypts all traffic |
| REST routing | `/api/` → Daphne/Uvicorn |
| WebSocket routing | `/ws/` → Daphne/Uvicorn |
| Static file serving | Faster than Django for JS, CSS, images |
| Rate limiting | Protection against request abuse |
| Security | Upload size limits, traffic filtering |

> At 200–300 user scale, both REST and WebSocket traffic route to the same Daphne/Uvicorn ASGI server. A split into separate Gunicorn (REST) + Daphne (WS) processes is a future scaling option, not a day-one requirement.

---

## 11. Deployment

### Container Architecture
Docker Compose is the deployment tool. At 200–300 users, Docker Compose is simple, production-capable, and easy to debug. Kubernetes is unnecessary at this scale.

```
Docker Compose
├── nginx        → reverse proxy (SSL, routing, static files)
├── asgi         → Daphne/Uvicorn (HTTP + WebSocket)
├── worker       → Celery worker (background tasks)
├── db           → PostgreSQL
└── redis        → Redis (sessions, pub/sub broker, Celery queue, cache)
```

> A separate `web` (Gunicorn) container is not needed at this scale. The single `asgi` container handles all traffic.

### Hosting Options
| Option | Suitable For |
|---|---|
| AWS | Full enterprise deployment, managed RDS, S3 native |
| Hetzner | Cost-efficient, EU hosting, self-managed |
| DigitalOcean | Simple managed DBs and droplets |
| Azure | Enterprise environments with existing Microsoft stack |

---

## 12. Monitoring *(Optional Initially)*

Can be added after the core system is stable. Not required for initial launch.

| Tool | Purpose |
|---|---|
| Sentry | Backend crash tracking, frontend error capture, WebSocket failures |
| Prometheus | Metrics collection — API latency, WebSocket count, Redis health |
| Grafana | Dashboards built on Prometheus metrics |

---

## 13. Technologies Explicitly Rejected

| Technology | Reason |
|---|---|
| MongoDB | Poor fit for a highly relational RBAC system |
| Firebase | Insufficient backend control for complex permissions |
| Supabase | Not flexible enough for complex realtime RBAC workflows |
| JWT-only auth | WebSocket integration and token revocation complexity |
| Socket.IO | Unnecessary abstraction over native WebSockets; Channels handles it |
| Microservices | Premature complexity; shared data and rules fit a monolith better |
| Kubernetes | Overkill for 200–300 users; Docker Compose is sufficient |
| Kafka | Hyperscale message broker; unnecessary at this scale |
| RabbitMQ clusters | Unnecessary; Redis handles the broker role cleanly |
| FastAPI | Strong for ML/inference APIs, weaker for enterprise RBAC/admin workflows |
| Redux | Overkill; Zustand is lighter and sufficient for this app's UI state needs |
| Gunicorn (separate) | Not needed at this scale; Daphne/Uvicorn handles both HTTP and WebSocket |

---

## 14. Open Decisions

| # | Topic | Status |
|---|---|---|
| OD-01 | Production file storage provider (AWS S3 vs Cloudflare R2 vs MinIO) | Not decided |
| OD-02 | Hosting provider | Not decided |
| OD-03 | File size and upload quotas | Not decided |
| OD-04 | Audit log events and viewer access | Not decided |

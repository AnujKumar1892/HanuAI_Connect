# Channel-Based Communication System
## Project Requirements & Technical Specification
> This document is the authoritative reference for the coding agent building this system. All architectural decisions, data models, API contracts, and business rules are defined here.

---

## 1. Project Overview

### 1.1 Purpose
A structured internal office communication platform for controlled, auditable messaging within an organisation. All communication flows through admin-managed channels. There is no open messaging, no self-signup, and no self-managed access.

### 1.2 Core Philosophy
- Top-down communication model — admins control structure, access, and roles
- Employees cannot create channels, initiate DMs, or discover channels they are not assigned to
- File sharing is channel-only
- Real-time notifications are mandatory for all users
- No message editing or deletion by anyone

### 1.3 Tech Stack (Recommended)
| Layer | Technology |
|---|---|
| Backend | Django + Django REST Framework |
| Real-time | Django Channels + Redis (ASGI/WebSocket) |
| Database | PostgreSQL |
| Auth | Session-based (username + password) |
| File Storage | Local or S3-compatible (to be decided) |
| Frontend | To be decided (React recommended) |

---

## 2. Roles & Permissions

### 2.1 Role Overview
Three roles exist: **Admin**, **Management**, and **Employee**. Roles are assigned at account creation by an Admin. Only an Admin can change a user's role.

### 2.2 Permissions Table

| Permission | Admin | Management | Employee |
|---|:---:|:---:|:---:|
| **Channel Management** | | | |
| Create channels | ✓ | ✕ | ✕ |
| Rename / update channel description | ✓ | ✕ | ✕ |
| Archive channels | ✓ | ✕ | ✕ |
| View archived channels | ✓ | ✓ | ✕ |
| View all active channels | ✓ | ✓ | ✕ |
| View assigned channels only | — | — | ✓ |
| **Messaging** | | | |
| Post in any channel | ✓ | ✓ | ✕ |
| Post in assigned channels | ✓ | ✓ | ✓ |
| Share files in channels | ✓ | ✓ | ✓ |
| Edit or delete messages | ✕ | ✕ | ✕ |
| View full message history (all channels) | ✓ | ✓ | ✕ |
| View message history (assigned channels) | ✓ | ✓ | ✓ |
| **Broadcasting** | | | |
| Broadcast to all channels | ✓ | ✓ | ✕ |
| Broadcast to selected channels | ✓ | ✓ | ✕ |
| Send DM to employee | ✕ | ✓ | ✕ |
| Send DM to Admin | ✕ | ✓ | ✕ |
| Send DM to Management | ✓ | ✓ | ✕ |
| Receive DMs | ✓ | ✓ | ✓ |
| Receive broadcast messages | — | — | ✓ |
| **User & Access Management** | | | |
| Create user accounts | ✓ | ✕ | ✕ |
| Assign / revoke channel membership | ✓ | ✕ | ✕ |
| Assign Admin or Management role | ✓ | ✕ | ✕ |
| Deactivate user accounts | ✓ | ✕ | ✕ |
| **Search** | | | |
| Search channels by name | ✓ | ✓ | ✓ |
| Search employees by name | ✓ | ✓ | ✕ |
| **Notifications** | | | |
| Real-time channel notifications | ✓ | ✓ | ✓ |
| DM notifications | ✓ | ✓ | ✓ |
| Offline notification queuing | ✓ | ✓ | ✓ |

### 2.3 Role Notes
- **Management** is automatically a member of every channel, including newly created ones. This membership is implicit — it does not appear as a manual assignment.
- **Admin** has full system control but cannot send DMs to employees. Admin communicates via channels and broadcasts only.
- **Admin and Management** can exchange DMs with each other.
- **Employees** can only receive DMs (from Management). They cannot initiate any direct contact.

---

## 3. Functional Requirements

### FR-01 · Channel Management
1. Admin can create a channel with a name and optional description at any time.
2. Admin can rename a channel or update its description.
3. Admin can archive a channel. Archived channels are hidden from the main UI sidebar for all users.
4. Archived channels are accessible from a dedicated archived section visible only to Admin and Management.
5. Archived channels retain all message history. No new posts are permitted in archived channels.
6. Members assigned to a channel before archiving retain read access to that channel's history via the archived section (Admin and Management only — employees lose visibility on archive).
7. Channels cannot be permanently deleted — only archived.
8. Admin and Management see all active channels in the sidebar. Employees see only their assigned channels.
9. On channel creation, Management is automatically added as a member.

### FR-02 · Messaging
10. Users can post text messages in channels they have access to. Basic text formatting (bold, italic, bullet lists) is supported.
11. File attachments are supported within channels: `PDF`, `DOC`, `DOCX`, `XLS`, `XLSX`, `PPT`, `PPTX`, `PNG`, `JPG`, `JPEG`, `GIF`.
12. No file size or storage limits are defined at this stage.
13. No message editing or deletion is permitted for any role.
14. All messages display: sender name, sender role badge, timestamp, and the channel context.
15. Messages are stored persistently. Messages from deactivated users remain visible in channel history with the original sender name preserved.
16. Employees cannot send direct messages to anyone.
17. Admin can post in any channel regardless of assignment.

### FR-03 · Direct Messages
18. Management can send DMs to any Employee.
19. Management can send DMs to Admins.
20. Admin can send DMs to Management users.
21. DMs are displayed in a dedicated inbox separate from channel messaging.
22. DMs support text and file attachments (same file types as channels).
23. DM history is visible to both the sender and recipient.
24. No group DMs — DMs are strictly one-to-one.

### FR-04 · Broadcasting
25. Admin and Management can send a broadcast to all channels simultaneously (Mode A — All-channel broadcast).
26. Admin and Management can select a subset of channels for a targeted broadcast (Mode B — Selected-channel broadcast).
27. Broadcast messages appear inline within the targeted channels, visually distinguished from regular messages (e.g. highlighted banner or special badge).
28. Employees in targeted channels automatically receive priority notifications for broadcast messages.
29. Broadcast messages are immutable — they cannot be edited or deleted.
30. Broadcast metadata (sender, timestamp, channels targeted) is recorded.

### FR-05 · Real-Time Notifications
31. All users receive real-time push notifications for new messages in their accessible channels (WebSocket via Django Channels + Redis).
32. All users receive real-time notifications for new DMs.
33. Broadcast messages trigger priority notifications for all affected users.
34. If a user is offline, notifications are queued and delivered on reconnect.
35. The UI displays an unread message count badge per channel and per DM thread.
36. Users can optionally enable or disable sound alerts for notifications (user-configurable setting).

### FR-06 · User & Access Management
37. Only admins can create user accounts. No self-signup is permitted.
38. Admin assigns role (Admin / Management / Employee) at account creation.
39. Admin assigns employees to one or more channels at account creation or at any subsequent time.
40. Admin can remove a user from a channel at any time.
41. Admin can deactivate a user account. Deactivated users cannot log in. Their messages are preserved.
42. Role changes require admin action; no user can elevate their own role.
43. Management users are automatically added to all channels on account creation.

### FR-07 · Search
44. All users can search channels by name (used for navigating to a channel).
45. Admin and Management can search users by name (used for targeting DMs and broadcasts).
46. Search is not full-text message search — it is limited to channel names and user names.

### FR-08 · Authentication & Session
47. Login is username + password based. No SSO or OAuth at this stage.
48. Session is active as long as the browser tab or window remains open.
49. Closing the tab or window ends the session (no persistent remember-me).
50. No self-registration. All accounts are created by Admin.

---

## 4. Data Models

### 4.1 User
```
User
├── id                  UUID, primary key
├── username            string, unique
├── password            hashed string
├── full_name           string
├── role                enum: ADMIN | MANAGEMENT | EMPLOYEE
├── is_active           boolean, default true
├── created_at          datetime
└── created_by          FK → User (the admin who created this account)
```

### 4.2 Channel
```
Channel
├── id                  UUID, primary key
├── name                string, unique
├── description         string, optional
├── is_archived         boolean, default false
├── created_at          datetime
├── created_by          FK → User (Admin)
└── archived_at         datetime, nullable
```

### 4.3 ChannelMembership
```
ChannelMembership
├── id                  UUID, primary key
├── channel             FK → Channel
├── user                FK → User
├── is_implicit         boolean  (true for Management auto-membership)
└── assigned_at         datetime
```
> Unique constraint on (channel, user).

### 4.4 Message
```
Message
├── id                  UUID, primary key
├── channel             FK → Channel
├── sender              FK → User
├── content             text
├── is_broadcast        boolean, default false
├── broadcast_mode      enum: ALL | SELECTED | null
├── created_at          datetime
└── attachments         reverse FK → Attachment
```

### 4.5 DirectMessage
```
DirectMessage
├── id                  UUID, primary key
├── sender              FK → User
├── recipient           FK → User
├── content             text
├── created_at          datetime
└── attachments         reverse FK → Attachment
```

### 4.6 Attachment
```
Attachment
├── id                  UUID, primary key
├── file                file path / storage URL
├── file_name           string
├── file_type           string (mime type)
├── uploaded_at         datetime
├── message             FK → Message, nullable
└── direct_message      FK → DirectMessage, nullable
```
> Exactly one of (message, direct_message) must be non-null.

### 4.7 Notification
```
Notification
├── id                  UUID, primary key
├── recipient           FK → User
├── type                enum: CHANNEL_MESSAGE | BROADCAST | DIRECT_MESSAGE
├── reference_id        UUID (FK to Message or DirectMessage)
├── is_read             boolean, default false
├── created_at          datetime
└── delivered_at        datetime, nullable
```

---

## 5. API Endpoints

All endpoints are prefixed with `/api/v1/`. Authentication is session-based. All responses are JSON.

### Auth
| Method | Endpoint | Description | Access |
|---|---|---|---|
| POST | `/auth/login/` | Login with username + password | Public |
| POST | `/auth/logout/` | End session | Authenticated |
| GET | `/auth/me/` | Get current user info | Authenticated |

### Users
| Method | Endpoint | Description | Access |
|---|---|---|---|
| GET | `/users/` | List all users | Admin |
| POST | `/users/` | Create a user | Admin |
| GET | `/users/{id}/` | Get user detail | Admin |
| PATCH | `/users/{id}/` | Update user (role, active status) | Admin |
| DELETE | `/users/{id}/` | Deactivate user (soft delete) | Admin |
| GET | `/users/search/?q=name` | Search users by name | Admin, Management |

### Channels
| Method | Endpoint | Description | Access |
|---|---|---|---|
| GET | `/channels/` | List accessible channels | All |
| POST | `/channels/` | Create a channel | Admin |
| GET | `/channels/{id}/` | Get channel detail | Members, Admin, Management |
| PATCH | `/channels/{id}/` | Rename / update description | Admin |
| POST | `/channels/{id}/archive/` | Archive a channel | Admin |
| GET | `/channels/archived/` | List archived channels | Admin, Management |
| GET | `/channels/search/?q=name` | Search channels by name | All |

### Channel Membership
| Method | Endpoint | Description | Access |
|---|---|---|---|
| GET | `/channels/{id}/members/` | List channel members | Admin |
| POST | `/channels/{id}/members/` | Add member to channel | Admin |
| DELETE | `/channels/{id}/members/{user_id}/` | Remove member from channel | Admin |

### Messages
| Method | Endpoint | Description | Access |
|---|---|---|---|
| GET | `/channels/{id}/messages/` | Get paginated message history | Members, Admin, Management |
| POST | `/channels/{id}/messages/` | Post a message | Members, Admin, Management |
| POST | `/channels/{id}/messages/broadcast/` | Send broadcast to channel(s) | Admin, Management |

### Direct Messages
| Method | Endpoint | Description | Access |
|---|---|---|---|
| GET | `/dms/` | List DM threads (inbox) | Admin, Management, Employee |
| GET | `/dms/{user_id}/` | Get DM history with a user | Sender or Recipient |
| POST | `/dms/{user_id}/` | Send a DM | Management (to Employee/Admin), Admin (to Management) |

### Notifications
| Method | Endpoint | Description | Access |
|---|---|---|---|
| GET | `/notifications/` | List notifications for current user | All |
| POST | `/notifications/mark-read/` | Mark notifications as read | All |

---

## 6. WebSocket Events

Connection endpoint: `ws://host/ws/`

### Client → Server (outgoing events)
| Event | Payload | Description |
|---|---|---|
| `join_channel` | `{ channel_id }` | Subscribe to a channel's real-time feed |
| `leave_channel` | `{ channel_id }` | Unsubscribe from a channel feed |
| `ping` | — | Keep-alive |

### Server → Client (incoming events)
| Event | Payload | Description |
|---|---|---|
| `new_message` | `{ channel_id, message }` | New message posted in a channel |
| `new_broadcast` | `{ channel_id, message }` | Broadcast message posted in a channel |
| `new_dm` | `{ dm }` | New direct message received |
| `notification` | `{ notification }` | Generic notification push |
| `user_deactivated` | `{ user_id }` | Admin deactivated a user (force logout that user) |
| `channel_archived` | `{ channel_id }` | A channel was archived |

---

## 7. Business Rules Summary

| # | Rule |
|---|---|
| BR-01 | No user (any role) can edit or delete a message once posted |
| BR-02 | Employees cannot create channels, DMs, or broadcasts |
| BR-03 | Management is implicitly a member of every channel (past and future) |
| BR-04 | Archived channels are hidden from employee view entirely |
| BR-05 | Broadcast messages appear inside the target channel's message feed with a visual distinction |
| BR-06 | DMs exist in a separate inbox, not inside channel feeds |
| BR-07 | Sessions expire when the browser tab/window is closed |
| BR-08 | Deactivated users' messages persist under their original name |
| BR-09 | Admin cannot send DMs to employees — only Management can |
| BR-10 | Admin ↔ Management DMs are permitted |
| BR-11 | Only Admin can assign, change, or revoke any user role |
| BR-12 | No self-signup — all accounts are admin-created |
| BR-13 | Supported file types: PDF, DOC, DOCX, XLS, XLSX, PPT, PPTX, PNG, JPG, JPEG, GIF |
| BR-14 | No file size or storage limits are enforced at this stage |
| BR-15 | Search is scoped to channel names and user names only — no full-text message search |

---

## 8. Out of Scope (for current phase)
- SSO / OAuth / third-party auth
- Message edit or delete for any role
- File size or upload quotas
- Audit log (parameters TBD, implementation deferred)
- Full-text message search
- Mobile app
- Self-signup or open registration
- Group DMs
- Read receipts within channels
- Typing indicators
- Message reactions or threads

---

## 9. Open Decisions
| # | Topic | Status |
|---|---|---|
| OD-01 | File storage backend (local disk vs S3-compatible) | Not decided |
| OD-02 | Audit log — which events to log, who can view | Not decided |
| OD-03 | Frontend framework | Not decided (React recommended) |
| OD-04 | Deployment environment | Not decided |

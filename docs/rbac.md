# Role-Based Access Control

HRPulsar ships with four built-in role codes. Roles are tenant-scoped (except `platform_admin`, which is platform-wide). Permissions follow the matrices below.

## Role codes

| Code             | Scope            | Notes |
|------------------|------------------|-------|
| `platform_admin` | Platform-wide    | Operates across tenants. Cannot be self-assigned. |
| `admin`          | Tenant           | Full tenant access. |
| `hr`             | Tenant           | Same write surface as `admin` for employees, dictionaries, assessments, PDPs. |
| `manager`        | Tenant + division subtree | Read/write limited to employees in managed division subtree. |
| `employee`       | Self             | Read own data; write only via `/auth/me` allowlist. |

## `/employees/*` write matrix

`x` = allowed, `—` = `403`, `s` = allowed but limited (see notes).

| Actor             | In-scope target | Out-of-scope target | Self via `/employees` | Self via `/auth/me` |
|-------------------|-----------------|---------------------|-----------------------|---------------------|
| `platform_admin`  | x               | x                   | x                     | x                   |
| `admin` / `hr`    | x               | x                   | x                     | x                   |
| `manager`         | x               | — (`outside_division_scope`) | — (`cannot_edit_self_status`) | x (allowlist)        |
| `employee`        | —               | —                   | —                     | x (allowlist)        |

**Endpoints covered by this matrix:**

- `POST/PUT/DELETE /api/employees`, `PUT /api/employees/{id}`, `DELETE /api/employees/{id}`
- `POST /api/employees/{id}/events`
- `POST/PUT/DELETE /api/employees/{id}/work-experience`
- `POST/PUT/DELETE /api/employees/{id}/previous-employment`
- `POST/PUT/DELETE /api/employees/{id}/education`
- `POST/PUT/DELETE /api/employees/{id}/courses`
- `POST/PUT/DELETE /api/employees/{id}/compensation` — admin-only (manager `403`)

**In-scope** for a `manager` means the target employee belongs to a division that the manager (or their deputy) manages — directly or through any descendant in the division tree (`Division.parent_id`).

## Error codes returned on `/employees/*` write rejections

| HTTP | `error_code`                | Reason |
|------|-----------------------------|--------|
| 401  | `employee_status_blocked`   | Actor's own employee card is `terminated`/`inactive` (auth-guard layer). |
| 403  | `outside_division_scope`    | Manager attempted to write a target outside their managed subtree. |
| 403  | `cannot_edit_self_status`   | Manager attempted to mutate their own employee card; use `PUT /auth/me`. |
| 403  | `employee_write_forbidden`  | Defence-in-depth fallback when a non-admin/non-manager role bypasses router guards. |

## Self-edit policy

- `PUT /auth/me` accepts only allowlisted profile fields (first/last name, avatar, phone, language). Status, role, email, and tenant cannot be changed via this endpoint — the schema rejects unknown fields with `extra='forbid'`.
- All organisational fields (`division_id`, `position_id`, `position_title`, `status`) are mutated through `/employees/*` and require `admin`/`hr` for self-edits; managers and below cannot mutate their own card here.

## Role lifecycle

Roles attached to a user evolve as their assignments change. The platform enforces this automatically; no admin step is required to keep roles consistent with `Division.manager_id` / `deputy_manager_id`.

### Auto-upgrade on assignment

When a user is set as `Division.manager_id` or `deputy_manager_id` (via `POST` or `PUT /api/divisions[/{id}]`):

- If the user's only tier role is `employee`, the `manager` role is added.
- If the user already holds `manager`, `admin`, `hr`, or `platform_admin`, no change is made.
- The original `employee` role is preserved; `manager` is granted in addition.

### Confirmed downgrade on unassignment

When a manager assignment changes (reassign, set to `null`, division deletion), the response from `update_division` includes a `pending_role_downgrade` array: zero or more entries describing users who, after the change, no longer manage **any** division of the tenant. Each entry contains `employee_id`, `user_id`, `current_role`, `user_name`. The UI shows a confirm-dialog from this list and lets an admin call:

```
POST /api/employees/{employee_id}/downgrade-role
```

The endpoint re-checks server-side that the user no longer manages any division, then strips the `manager` role. It is callable only by `admin` / `hr` / `platform_admin`. Users holding `admin`, `hr`, or `platform_admin` are never downgraded by this call (they return `422 cannot_downgrade_admin`).

### Invitation role hierarchy

`POST /api/invitations` and `POST /api/invitations/bulk` reject any `role_code` above the inviter's tier:

| Inviter role           | May invite                                                  |
|------------------------|-------------------------------------------------------------|
| `platform_admin`       | `platform_admin`, `admin`, `hr`, `manager`, `employee`      |
| `admin` / `hr`         | `admin`, `hr`, `manager`, `employee`                        |
| `manager`              | `employee` (only)                                           |
| `employee`             | nothing — `403 role_above_inviter`                          |

Same matrix applies to `PATCH /api/invitations/{id}` when changing `role_code`.

### Error codes

| HTTP | `error_code`                  | Reason |
|------|-------------------------------|--------|
| 403  | `role_above_inviter`          | Inviter attempted to grant a role above their own tier. |
| 409  | `still_manages_divisions`     | Downgrade refused — user still set as manager / deputy on at least one division. |
| 422  | `cannot_downgrade_admin`      | Downgrade refused — user holds `admin` / `hr` / `platform_admin`. |

### One-shot reconciliation

For tenants whose data predates the auto-upgrade rule, run:

```bash
python -m backend.scripts.emp3_role_consistency [--dry-run]
```

The script iterates all divisions and adds the `manager` role to any assigned user who lacks it. Idempotent. See `docs/ops/migrations/EMP3_role_consistency_2026-05-05.md` for run instructions and log format.

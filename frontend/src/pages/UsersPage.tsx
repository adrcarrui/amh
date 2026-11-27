import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";

import {
  ArrowUpRight,
  ChevronLeft,
  ChevronRight,
  Plus,
  X,
} from "lucide-react";

import "./UsersPage.css";

const PAGE_SIZE = 50;
const EMPTY_FILTERS = {
  name: "",
  email: "",
  secondary_email: "",
  status: "",
  no_application_access: "",
  nfc: "",
};

type User = {
  id: string;
  name: string;
  surname: string | null;
  is_blocked: boolean;
  primary_email: string | null;
  secondary_email: string | null;
  primary_email_verified: boolean;
  application_count: number;
  has_nfc_card: boolean;
};

type CreatedUser = {
  user_id: string;
  username: string;
  temporary_password: string;
};

type Props = {
  onSessionExpired: () => void;
  onManageUser: (userId: string) => void;
};

function isUser(value: unknown): value is User {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const user = value as Record<string, unknown>;

  return (
    typeof user.id === "string" &&
    typeof user.name === "string" &&
    (typeof user.surname === "string" || user.surname === null) &&
    typeof user.is_blocked === "boolean" &&
    (typeof user.primary_email === "string" ||
      user.primary_email === null) &&
    (typeof user.secondary_email === "string" || user.secondary_email === null) &&
    typeof user.primary_email_verified === "boolean" &&
    typeof user.application_count === "number" &&
    Number.isInteger(user.application_count) &&
    user.application_count >= 0 &&
    typeof user.has_nfc_card === "boolean"
  );
}

function isCreatedUser(value: unknown): value is CreatedUser {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const user = value as Record<string, unknown>;

  return (
    typeof user.user_id === "string" &&
    typeof user.username === "string" &&
    typeof user.temporary_password === "string" &&
    user.temporary_password.length > 0
  );
}

export function UsersPage({
  onSessionExpired,
  onManageUser,
}: Props) {
  const [users, setUsers] = useState<User[]>([]);
  const [offset, setOffset] = useState(0);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [hasMore, setHasMore] = useState(false);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState("");

  const [creating, setCreating] = useState(false);
  const [formError, setFormError] = useState("");
  const [createdUser, setCreatedUser] = useState<CreatedUser | null>(null);

  const dialogRef = useRef<HTMLDialogElement>(null);
  const tableRef = useRef<HTMLDivElement>(null);

  const hasFilters = Object.values(filters).some((value) => value.trim());

  useEffect(() => {
    const controller = new AbortController();
    let disposed = false;

    const timeout = window.setTimeout(() => controller.abort(), 10000);

    async function loadUsers() {
      setLoading(true);
      setListError("");
      if (tableRef.current) {
        tableRef.current.scrollTop = 0;
      }

      try {
        const params = new URLSearchParams({
          limit: String(PAGE_SIZE),
          offset: String(offset),
        });
        for (const [field, value] of Object.entries(filters)) {
          if (value.trim()) params.set(field, value.trim());
        }

        const response = await fetch(
          `/api/v1/admin/users?${params}`,
          {
            credentials: "include",
            cache: "no-store",
            signal: controller.signal,
          },
        );

        if (disposed) return;

        if (response.status === 401) {
          onSessionExpired();
          return;
        }

        if (response.status === 403) {
          throw new Error("Administrator access is required.");
        }

        if (!response.ok) {
          throw new Error("We couldn't load the users.");
        }

        const data: unknown = await response.json();

        if (
          typeof data !== "object" ||
          data === null ||
          !("items" in data) ||
          !Array.isArray(data.items) ||
          !data.items.every(isUser)
        ) {
          throw new Error("We couldn't read the user list.");
        }

        if (!disposed) {
          setUsers(data.items);
          setHasMore(
            "has_more" in data && typeof data.has_more === "boolean"
              ? data.has_more
              : data.items.length === PAGE_SIZE,
          );
        }
      } catch (error) {
        if (!disposed) {
          setListError(
            controller.signal.aborted
              ? "AMH took too long to respond. Please try again."
              : error instanceof Error
                ? error.message
                : "We couldn't load the users.",
          );
        }
      } finally {
        window.clearTimeout(timeout);

        if (!disposed) {
          setLoading(false);
        }
      }
    }

    const debounce = window.setTimeout(() => void loadUsers(), 250);

    return () => {
      disposed = true;
      window.clearTimeout(debounce);
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [filters, offset, revision, onSessionExpired]);

  function updateFilter(field: keyof typeof EMPTY_FILTERS, value: string) {
    setLoading(true);
    setFilters((current) => ({ ...current, [field]: value }));
    setOffset(0);
  }

  function clearFilters() {
    setLoading(true);
    setFilters(EMPTY_FILTERS);
    setOffset(0);
  }

  function openCreateDialog() {
    setCreatedUser(null);
    setFormError("");
    dialogRef.current?.showModal();
  }

  function closeCreateDialog() {
    if (!creating) {
      dialogRef.current?.close();
    }
  }

  function manageCreatedUser() {
    if (!createdUser || creating) return;

    const userId = createdUser.user_id;
    dialogRef.current?.close();
    onManageUser(userId);
  }

  async function createUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (creating) return;

    const form = event.currentTarget;
    const fields = new FormData(form);

    setCreating(true);
    setFormError("");

    try {
      const response = await fetch("/api/v1/admin/users", {
        method: "POST",
        credentials: "include",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: String(fields.get("username") ?? "").trim(),
          name: String(fields.get("name") ?? "").trim(),
          surname: String(fields.get("surname") ?? "").trim(),
          email: String(fields.get("email") ?? "").trim(),
        }),
      });

      if (response.status === 401) {
        dialogRef.current?.close();
        onSessionExpired();
        return;
      }

      if (!response.ok) {
        const messages: Record<number, string> = {
          403: "You don't have permission to create users.",
          409: "The username or email is already registered.",
          422: "Please check the information entered.",
          503: "The identity service is unavailable. Please try again later.",
        };

        throw new Error(
          messages[response.status] ?? "The user could not be created.",
        );
      }

      const data: unknown = await response.json();

      if (!isCreatedUser(data)) {
        throw new Error(
          "The user may have been created, but the temporary password " +
            "could not be retrieved. Check the user list before retrying.",
        );
      }

      setCreatedUser(data);
      form.reset();
      setOffset(0);
      setRevision((value) => value + 1);
    } catch (error) {
      setFormError(
        error instanceof Error
          ? error.message
          : "The request could not be confirmed. Check the user list " +
              "before retrying.",
      );
    } finally {
      setCreating(false);
    }
  }

  return (
    <section className="users-page" aria-label="User management">
      <div className="users-toolbar">
        <h1 className="users-title">Users</h1>

        <button
          className="users-primary-button"
          onClick={openCreateDialog}
          type="button"
        >
          <Plus size={16} aria-hidden="true" />
          Create user
        </button>

        <div className="users-quick-filters" role="group" aria-label="Quick filters">
          <button
            type="button"
            className="users-secondary-button"
            aria-pressed={filters.no_application_access === "true"}
            onClick={() => updateFilter(
              "no_application_access", filters.no_application_access ? "" : "true",
            )}
          >
            No application access
          </button>
          <button
            type="button"
            className="users-secondary-button"
            aria-pressed={filters.nfc === "not_linked"}
            onClick={() => updateFilter("nfc", filters.nfc === "not_linked" ? "" : "not_linked")}
          >
            No NFC card
          </button>
        </div>
      </div>

      <div
        className="table-container users-table"
        ref={tableRef}
        role="region"
        aria-label="Users table"
        tabIndex={0}
      >
        <table aria-busy={loading}>
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Primary email</th>
              <th scope="col">Secondary email</th>
              <th scope="col">Status</th>
              <th scope="col">Access</th>
              <th scope="col">NFC</th>
              <th scope="col">Actions</th>
            </tr>
            <tr className="users-filters">
              <td>
                <input
                  type="search"
                  aria-label="Filter by name"
                  placeholder="Search name"
                  value={filters.name}
                  maxLength={251}
                  onChange={(event) => updateFilter("name", event.target.value)}
                />
              </td>
              <td>
                <input
                  type="search"
                  aria-label="Filter by primary email"
                  placeholder="Search email"
                  value={filters.email}
                  maxLength={320}
                  onChange={(event) => updateFilter("email", event.target.value)}
                />
              </td>
              <td>
                <input
                  type="search"
                  aria-label="Filter by secondary email"
                  placeholder="Search email"
                  value={filters.secondary_email}
                  maxLength={320}
                  onChange={(event) => updateFilter("secondary_email", event.target.value)}
                />
              </td>
              <td>
                <select
                  aria-label="Filter by status"
                  value={filters.status}
                  onChange={(event) => updateFilter("status", event.target.value)}
                >
                  <option value="">All statuses</option>
                  <option value="active">Active</option>
                  <option value="blocked">Blocked</option>
                </select>
              </td>
              <td />
              <td>
                <select
                  aria-label="Filter by NFC"
                  value={filters.nfc}
                  onChange={(event) => updateFilter("nfc", event.target.value)}
                >
                  <option value="">All</option>
                  <option value="linked">Linked</option>
                  <option value="not_linked">Not linked</option>
                </select>
              </td>
              <td>
                <button
                  type="button"
                  className="users-secondary-button users-clear-filters"
                  onClick={clearFilters}
                  disabled={!hasFilters}
                >
                  Clear filters
                </button>
              </td>
            </tr>
          </thead>

          <tbody>
            {(loading || listError || users.length === 0) && (
              <tr>
                <td colSpan={7} className="users-empty">
                  {loading ? (
                    <span role="status">Loading users…</span>
                  ) : listError ? (
                    <div className="users-list-error" role="alert">
                      <p>{listError}</p>
                      <button
                        type="button"
                        className="users-secondary-button"
                        onClick={() => setRevision((value) => value + 1)}
                      >
                        Try again
                      </button>
                    </div>
                  ) : hasFilters ? (
                    "No users match these filters."
                  ) : (
                    "No users on this page."
                  )}
                </td>
              </tr>
            )}

            {!loading && !listError && users.map((user) => (
              <tr key={user.id}>
                <td>
                  <span className="users-name">
                    {user.name} {user.surname}
                  </span>
                </td>

                <td>{user.primary_email ?? "—"}</td>
                <td>{user.secondary_email ?? "—"}</td>

                <td>
                  <span
                    className={`users-status ${
                      user.is_blocked ? "blocked" : "active"
                    }`}
                  >
                    {user.is_blocked ? "Blocked" : "Active"}
                  </span>
                </td>

                <td>
                  {user.application_count === 0
                    ? "No access"
                    : `${user.application_count} ${user.application_count === 1 ? "app" : "apps"}`}
                </td>

                <td>
                  {user.has_nfc_card ? (
                    <span className="users-status active">Linked</span>
                  ) : (
                    <button
                      type="button"
                      className="users-detail-link"
                      aria-label={`Manage NFC for ${user.name} ${user.surname ?? ""}`.trim()}
                      onClick={() => onManageUser(user.id)}
                    >
                      Not linked
                    </button>
                  )}
                </td>

                <td>
                  <button
                    type="button"
                    className="users-detail-link"
                    onClick={() => onManageUser(user.id)}
                    aria-label={`Manage ${user.name} ${
                      user.surname ?? ""
                    }`}
                  >
                    Manage
                    <ArrowUpRight size={14} aria-hidden="true" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="users-pagination">
        <span>Page {Math.floor(offset / PAGE_SIZE) + 1}</span>

        <div>
          <button
            type="button"
            className="users-secondary-button"
            disabled={loading || offset === 0}
            onClick={() => {
              setLoading(true);
              setOffset((value) => Math.max(0, value - PAGE_SIZE));
            }}
          >
            <ChevronLeft size={15} aria-hidden="true" />
            Previous
          </button>

          <button
            type="button"
            className="users-secondary-button"
            disabled={loading || Boolean(listError) || !hasMore}
            onClick={() => {
              setLoading(true);
              setOffset((value) => value + PAGE_SIZE);
            }}
          >
            Next
            <ChevronRight size={15} aria-hidden="true" />
          </button>
        </div>
      </div>

      <dialog
        ref={dialogRef}
        className="users-dialog"
        aria-labelledby="create-user-title"
        onCancel={(event) => {
          if (creating) {
            event.preventDefault();
          }
        }}
        onClose={() => {
          setCreatedUser(null);
          setFormError("");
        }}
      >
        <div className="users-dialog-heading">
          <h2 id="create-user-title">
            {createdUser ? "User created" : "Create user"}
          </h2>

          <button
            className="users-close-button"
            onClick={closeCreateDialog}
            disabled={creating}
            aria-label="Close"
            type="button"
          >
            <X size={19} aria-hidden="true" />
          </button>
        </div>

        {createdUser ? (
          <div className="users-created" role="status">
            <p>
              <strong>{createdUser.username}</strong> is ready.
              Assign application access before their first sign-in.
            </p>

            <div className="users-password">
              <span>Temporary password</span>
              <code>{createdUser.temporary_password}</code>
            </div>

            <p className="users-password-note">
              Copy this password before closing. It will only be shown here.
              Share it securely with the user.
            </p>

            <div className="users-dialog-actions">
              <button
                type="button"
                className="users-secondary-button"
                onClick={closeCreateDialog}
                disabled={creating}
              >
                Done
              </button>

              <button
                type="button"
                className="users-primary-button"
                onClick={manageCreatedUser}
                disabled={creating}
              >
                Assign access
                <ArrowUpRight size={15} aria-hidden="true" />
              </button>
            </div>
          </div>
        ) : (
          <form onSubmit={createUser}>
            <p className="users-form-description">
              Create an account in AMH and the identity service.
            </p>

            <fieldset disabled={creating} className="users-fields">
              <label>
                Username
                <input
                  name="username"
                  required
                  minLength={3}
                  maxLength={100}
                  pattern={"[A-Za-z0-9._\\-]+"}
                  autoComplete="off"
                />
                <small>
                  Letters, numbers, dots, underscores and hyphens.
                </small>
              </label>

              <div className="users-name-fields">
                <label>
                  First name
                  <input
                    name="name"
                    required
                    maxLength={100}
                    autoComplete="given-name"
                  />
                </label>

                <label>
                  Last name
                  <input
                    name="surname"
                    required
                    maxLength={150}
                    autoComplete="family-name"
                  />
                </label>
              </div>

              <label>
                Primary email
                <input
                  name="email"
                  type="email"
                  required
                  maxLength={320}
                  autoComplete="email"
                />
              </label>
            </fieldset>

            {formError && (
              <p className="users-form-error" role="alert">
                {formError}
              </p>
            )}

            <div className="users-dialog-actions">
              <button
                className="users-secondary-button"
                type="button"
                onClick={closeCreateDialog}
                disabled={creating}
              >
                Cancel
              </button>

              <button
                className="users-primary-button"
                type="submit"
                disabled={creating}
              >
                {creating ? "Creating…" : "Create user"}
              </button>
            </div>
          </form>
        )}
      </dialog>
    </section>
  );
}
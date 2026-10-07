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

type User = {
  id: string;
  name: string;
  surname: string | null;
  is_blocked: boolean;
  primary_email: string | null;
  primary_email_verified: boolean;
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
    typeof user.primary_email_verified === "boolean"
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
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState("");

  const [creating, setCreating] = useState(false);
  const [formError, setFormError] = useState("");
  const [createdUser, setCreatedUser] = useState<CreatedUser | null>(null);

  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    let disposed = false;

    const timeout = window.setTimeout(() => controller.abort(), 10000);

    async function loadUsers() {
      setLoading(true);
      setListError("");

      try {
        const response = await fetch(
          `/api/v1/admin/users?limit=${PAGE_SIZE}&offset=${offset}`,
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

    void loadUsers();

    return () => {
      disposed = true;
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [offset, revision, onSessionExpired]);

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
        <span className="users-summary">
          {loading
            ? "Loading users…"
            : `${users.length} users on this page`}
        </span>

        <button
          className="users-primary-button"
          onClick={openCreateDialog}
          type="button"
        >
          <Plus size={16} aria-hidden="true" />
          Create user
        </button>
      </div>

      {loading ? (
        <div className="users-message" role="status">
          Loading users…
        </div>
      ) : listError ? (
        <div className="users-message" role="alert">
          <p>{listError}</p>

          <button
            type="button"
            className="users-secondary-button"
            onClick={() => setRevision((value) => value + 1)}
          >
            Try again
          </button>
        </div>
      ) : (
        <>
          <div className="table-container users-table">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Primary email</th>
                  <th>Status</th>
                  <th>
                    <span className="users-visually-hidden">
                      Actions
                    </span>
                  </th>
                </tr>
              </thead>

              <tbody>
                {users.map((user) => (
                  <tr key={user.id}>
                    <td>
                      <span className="users-name">
                        {user.name} {user.surname}
                      </span>
                    </td>

                    <td>{user.primary_email ?? "—"}</td>

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

                {users.length === 0 && (
                  <tr>
                    <td colSpan={4} className="users-empty">
                      No users on this page.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="users-pagination">
            <span>Page {Math.floor(offset / PAGE_SIZE) + 1}</span>

            <div>
              <button
                type="button"
                className="users-secondary-button"
                disabled={offset === 0}
                onClick={() =>
                  setOffset((value) => Math.max(0, value - PAGE_SIZE))
                }
              >
                <ChevronLeft size={15} aria-hidden="true" />
                Previous
              </button>

              <button
                type="button"
                className="users-secondary-button"
                disabled={users.length < PAGE_SIZE}
                onClick={() => setOffset((value) => value + PAGE_SIZE)}
              >
                Next
                <ChevronRight size={15} aria-hidden="true" />
              </button>
            </div>
          </div>
        </>
      )}

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
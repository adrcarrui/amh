import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import {
  ArrowLeft,
  CreditCard,
  KeyRound,
  Link2,
  ShieldCheck,
  UserRound,
} from "lucide-react";

import { UserContactPanel } from "./UserContactPanel";
import { UserStatusControl } from "./UserStatusControl";

import "./UserDetailPage.css";

type Grant = {
  display_name: string;
  application_code: string;
  role: "viewer" | "editor" | "admin";
  status: "active" | "blocked" | "revoked";
};

type Application = {
  code: string;
  display_name: string;
};

type ATurnosLink = {
  id_aturno: string;
  id_user: string;
};

type UserDetail = {
  id: string;
  name: string;
  surname: string;
  primary_email: string | null;
  is_blocked: boolean;
  grants: Grant[];
  applications: Application[];
  aturnos_links: ATurnosLink[];
};

type Props = {
  userId: string;
  onBack: () => void;
  onSessionExpired: () => void;
};

function isATurnosLink(value: unknown): value is ATurnosLink {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const link = value as Record<string, unknown>;

  return (
    typeof link.id_aturno === "string" &&
    link.id_aturno.length > 0 &&
    typeof link.id_user === "string" &&
    link.id_user.length > 0
  );
}

export function UserDetailPage({
  userId,
  onBack,
  onSessionExpired,
}: Props) {
  const [detail, setDetail] = useState<UserDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);

  const [mysimTokenConfigured, setMysimTokenConfigured] = useState<
    boolean | null | undefined
  >(undefined);

  const [savingAccess, setSavingAccess] = useState(false);
  const [accessMessage, setAccessMessage] = useState("");
  const [accessError, setAccessError] = useState("");

  const [savingCard, setSavingCard] = useState(false);
  const [cardMessage, setCardMessage] = useState("");
  const [cardError, setCardError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    let disposed = false;

    const timeout = window.setTimeout(() => {
      controller.abort();
    }, 10000);

    async function loadDetail() {
      setLoading(true);
      setError("");
      setMysimTokenConfigured(undefined);

      try {
        const response = await fetch(
          `/api/v1/admin/users/${encodeURIComponent(userId)}`,
          {
            credentials: "include",
            cache: "no-store",
            signal: controller.signal,
          },
        );

        if (disposed) {
          return;
        }

        if (response.status === 401) {
          onSessionExpired();
          return;
        }

        if (!response.ok) {
          throw new Error(
            response.status === 404
              ? "User not found."
              : "We couldn't load this user.",
          );
        }

        const data = await response.json();

        if (
          !data ||
          data.id !== userId ||
          typeof data.name !== "string" ||
          typeof data.surname !== "string" ||
          typeof data.is_blocked !== "boolean" ||
          !(
            typeof data.primary_email === "string" ||
            data.primary_email === null
          ) ||
          !Array.isArray(data.grants) ||
          !Array.isArray(data.applications) ||
          !Array.isArray(data.aturnos_links) ||
          !data.aturnos_links.every(isATurnosLink)
        ) {
          throw new Error("Invalid user response.");
        }

        if (!disposed) {
          setDetail(data);
        }
      } catch (cause) {
        if (!disposed) {
          setError(
            controller.signal.aborted
              ? "AMH took too long to respond. Please try again."
              : cause instanceof Error
                ? cause.message
                : "We couldn't load this user.",
          );
        }
      } finally {
        window.clearTimeout(timeout);

        if (!disposed) {
          setLoading(false);
        }
      }
    }

    void loadDetail();

    return () => {
      disposed = true;
      controller.abort();
      window.clearTimeout(timeout);
    };
  }, [userId, revision, onSessionExpired]);

  async function postChange(path: string, body: object) {
    const response = await fetch(path, {
      method: "POST",
      credentials: "include",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });

    if (response.status === 401) {
      onSessionExpired();
      return false;
    }

    if (!response.ok) {
      const data = await response.json().catch(() => null);

      throw new Error(
        typeof data?.detail === "string"
          ? data.detail
          : `The change could not be saved: HTTP ${response.status}`,
      );
    }

    return true;
  }

  async function saveAccess(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (savingAccess) {
      return;
    }

    const fields = new FormData(event.currentTarget);

    setSavingAccess(true);
    setAccessMessage("");
    setAccessError("");

    try {
      const saved = await postChange(
        `/api/v1/admin/users/${encodeURIComponent(userId)}/application-access`,
        {
          application_code: fields.get("application_code"),
          role: fields.get("role"),
          status: fields.get("status"),
          reason: String(fields.get("reason") ?? "").trim() || null,
        },
      );

      if (saved) {
        setAccessMessage("Application access updated.");
        setRevision((value) => value + 1);
      }
    } catch (cause) {
      setAccessError(
        cause instanceof Error
          ? cause.message
          : "Unable to save access.",
      );
    } finally {
      setSavingAccess(false);
    }
  }

  async function assignCard(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (savingCard) {
      return;
    }

    const form = event.currentTarget;
    const fields = new FormData(form);

    setSavingCard(true);
    setCardMessage("");
    setCardError("");

    try {
      const saved = await postChange(
        `/api/v1/admin/users/${encodeURIComponent(userId)}/cards`,
        {
          raw_uid: String(fields.get("raw_uid") ?? "").trim(),
        },
      );

      if (saved) {
        setCardMessage("Card assigned successfully.");
        form.reset();
      }
    } catch (cause) {
      setCardError(
        cause instanceof Error
          ? cause.message
          : "Unable to assign the card.",
      );
    } finally {
      setSavingCard(false);
    }
  }

  const isATurnosLinked = (detail?.aturnos_links.length ?? 0) > 0;

  const mysimStatusText =
    mysimTokenConfigured === undefined
      ? "Checking token..."
      : mysimTokenConfigured === null
        ? "Token status unavailable"
        : mysimTokenConfigured
          ? "Token configured"
          : "Token not configured";

  return (
    <section className="user-detail-page">
      <button
        type="button"
        className="users-secondary-button detail-back"
        onClick={onBack}
      >
        <ArrowLeft size={16} />
        Back to users
      </button>

      {loading && <p role="status">Loading user...</p>}

      {!loading && error && (
        <div className="detail-panel" role="alert">
          <p>{error}</p>

          <button
            type="button"
            className="users-secondary-button"
            onClick={() => setRevision((value) => value + 1)}
          >
            Try again
          </button>
        </div>
      )}

      {!loading && !error && detail && (
        <div className="detail-layout">
          <div className="detail-column">
            <section className="detail-panel detail-profile">
              <div className="detail-profile-main">
                <div className="detail-avatar">
                  <UserRound size={28} />
                </div>

                <div className="detail-identity">
                  <h2>
                    {detail.name} {detail.surname}
                  </h2>
                </div>

                <UserStatusControl
                  key={userId}
                  userId={userId}
                  isBlocked={detail.is_blocked}
                  onSessionExpired={onSessionExpired}
                  onStatusChanged={(isBlocked) => {
                    setDetail((current) =>
                      current
                        ? {
                          ...current,
                          is_blocked: isBlocked,
                        }
                        : current,
                    );
                  }}
                />
              </div>

              <div className="detail-integrations">
                <span
                  className={`detail-integration ${isATurnosLinked ? "is-linked" : "is-neutral"
                    }`}
                >
                  <Link2 size={16} />
                  <span>aTurnos</span>
                  <span className="detail-integration-value">
                    {isATurnosLinked ? "Linked" : "Not linked"}
                  </span>
                </span>

                <span
                  className={`detail-integration ${mysimTokenConfigured === true
                      ? "is-linked"
                      : "is-neutral"
                    }`}
                  title="Token management will be available with the mySim integration."
                >
                  <KeyRound size={16} />
                  <span>mySim</span>
                  <span className="detail-integration-value">
                    {mysimStatusText}
                  </span>
                </span>
              </div>
            </section>

            <section className="detail-panel detail-access-panel">
              <div className="detail-section-heading">
                <ShieldCheck size={20} />
                <h2>Application access</h2>
              </div>

              {detail.grants.length > 0 ? (
                <div className="table-container">
                  <table className="detail-access-table">
                    <thead>
                      <tr>
                        <th>Application</th>
                        <th>Role</th>
                        <th>Status</th>
                      </tr>
                    </thead>

                    <tbody>
                      {detail.grants.map((grant) => (
                        <tr key={grant.application_code}>
                          <td>{grant.display_name}</td>
                          <td className="detail-capitalize">
                            {grant.role}
                          </td>
                          <td className="detail-capitalize">
                            {grant.status}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="detail-muted">
                  No application access assigned.
                </p>
              )}

              {detail.applications.length > 0 && (
                <form className="detail-form" onSubmit={saveAccess}>
                  <h3>Assign or change access</h3>

                  <fieldset disabled={savingAccess}>
                    <div className="detail-form-grid">
                      <label>
                        Application
                        <select name="application_code" required>
                          {detail.applications.map((application) => (
                            <option
                              key={application.code}
                              value={application.code}
                            >
                              {application.display_name}
                            </option>
                          ))}
                        </select>
                      </label>

                      <label>
                        Role
                        <select name="role" defaultValue="viewer">
                          <option value="viewer">Viewer</option>
                          <option value="editor">Editor</option>
                          <option value="admin">Admin</option>
                        </select>
                      </label>

                      <label>
                        Status
                        <select name="status" defaultValue="active">
                          <option value="active">Active</option>
                          <option value="blocked">Blocked</option>
                          <option value="revoked">Revoked</option>
                        </select>
                      </label>
                    </div>

                    <label>
                      Reason (optional)
                      <input name="reason" maxLength={500} />
                    </label>

                    <p className="detail-muted">
                      Select Active for a first assignment. Blocking or
                      revoking requires an existing assignment.
                    </p>

                    <button
                      className="users-primary-button"
                      type="submit"
                    >
                      {savingAccess ? "Saving..." : "Save"}
                    </button>
                  </fieldset>

                  {accessError && (
                    <p className="detail-error" role="alert">
                      {accessError}
                    </p>
                  )}

                  {accessMessage && (
                    <p className="detail-success" role="status">
                      {accessMessage}
                    </p>
                  )}
                </form>
              )}
            </section>
          </div>

          <div className="detail-column">
            <UserContactPanel
              key={userId}
              userId={userId}
              onSessionExpired={onSessionExpired}
              onTokenStatusChange={setMysimTokenConfigured}
            />

            <section className="detail-panel detail-nfc-panel">
              <div className="detail-section-heading">
                <CreditCard size={20} />
                <h2>NFC card</h2>
              </div>

              <p className="detail-muted">
                Assign a card using the UID obtained from the reader.
              </p>

              <form className="detail-form" onSubmit={assignCard}>
                <fieldset disabled={savingCard}>
                  <label>
                    Card UID
                    <input
                      name="raw_uid"
                      required
                      minLength={8}
                      maxLength={64}
                      autoComplete="off"
                      placeholder="Enter the card UID"
                    />
                  </label>

                  <button
                    className="users-primary-button"
                    type="submit"
                  >
                    {savingCard ? "Assigning..." : "Save"}
                  </button>
                </fieldset>

                {cardError && (
                  <p className="detail-error" role="alert">
                    {cardError}
                  </p>
                )}

                {cardMessage && (
                  <p className="detail-success" role="status">
                    {cardMessage}
                  </p>
                )}
              </form>
            </section>
          </div>
        </div>
      )}
    </section>
  );
}
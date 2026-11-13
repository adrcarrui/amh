import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Mail } from "lucide-react";

type Contact = {
  user_id: string;
  primary_email: string | null;
  secondary_email: string | null;
  mysim_token_configured: boolean;
};

type Props = {
  userId: string;
  onSessionExpired: () => void;
  onTokenStatusChange?: (configured: boolean | null) => void;
};

function isContact(value: unknown): value is Contact {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const data = value as Record<string, unknown>;

  return (
    typeof data.user_id === "string" &&
    (
      typeof data.primary_email === "string" ||
      data.primary_email === null
    ) &&
    (
      typeof data.secondary_email === "string" ||
      data.secondary_email === null
    ) &&
    typeof data.mysim_token_configured === "boolean"
  );
}

export function UserContactPanel({
  userId,
  onSessionExpired,
  onTokenStatusChange,
}: Props) {
  const [contact, setContact] = useState<Contact | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<
    "primary" | "secondary" | null
  >(null);

  const [loadError, setLoadError] = useState("");
  const [primaryError, setPrimaryError] = useState("");
  const [primaryMessage, setPrimaryMessage] = useState("");
  const [secondaryError, setSecondaryError] = useState("");
  const [secondaryMessage, setSecondaryMessage] = useState("");
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let disposed = false;

    const timeout = window.setTimeout(() => {
      controller.abort();
    }, 10000);

    async function loadContact() {
      setLoading(true);
      setLoadError("");

      try {
        const response = await fetch(
          `/api/v1/admin/users/${encodeURIComponent(userId)}/contact`,
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
            `Unable to load contact information: HTTP ${response.status}`,
          );
        }

        const data: unknown = await response.json();

        if (!isContact(data) || data.user_id !== userId) {
          throw new Error("Invalid contact information response.");
        }

        if (!disposed) {
          setContact(data);
          onTokenStatusChange?.(data.mysim_token_configured);
        }
      } catch (cause) {
        if (!disposed) {
          onTokenStatusChange?.(null);

          setLoadError(
            controller.signal.aborted
              ? "The request took too long."
              : cause instanceof Error
                ? cause.message
                : "Unable to load contact information.",
          );
        }
      } finally {
        window.clearTimeout(timeout);

        if (!disposed) {
          setLoading(false);
        }
      }
    }

    void loadContact();

    return () => {
      disposed = true;
      controller.abort();
      window.clearTimeout(timeout);
    };
  }, [
    userId,
    revision,
    onSessionExpired,
    onTokenStatusChange,
  ]);

  async function saveEmail(
    event: FormEvent<HTMLFormElement>,
    kind: "primary" | "secondary",
  ) {
    event.preventDefault();

    if (saving !== null || loading || !contact) {
      return;
    }

    const fields = new FormData(event.currentTarget);
    const fieldName =
      kind === "primary" ? "primary_email" : "secondary_email";

    const email = String(fields.get(fieldName) ?? "").trim();

    if (kind === "primary" && !email) {
      setPrimaryError("The primary email cannot be empty.");
      return;
    }

    setSaving(kind);

    if (kind === "primary") {
      setPrimaryError("");
      setPrimaryMessage("");
    } else {
      setSecondaryError("");
      setSecondaryMessage("");
    }

    const endpoint =
      `/api/v1/admin/users/${encodeURIComponent(userId)}/contact` +
      (kind === "primary" ? "/primary" : "");

    const body =
      kind === "primary"
        ? {
            primary_email: email,
            expected_primary_email: contact.primary_email,
          }
        : {
            secondary_email: email || null,
          };

    try {
      const response = await fetch(endpoint, {
        method: "PATCH",
        credentials: "include",
        cache: "no-store",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(body),
      });

      if (response.status === 401) {
        onSessionExpired();
        return;
      }

      const data = await response.json().catch(() => null);

      if (!response.ok) {
        throw new Error(
          typeof data?.detail === "string"
            ? data.detail
            : response.status === 422
              ? "Enter a valid email address."
              : `Unable to save: HTTP ${response.status}`,
        );
      }

      if (kind === "primary") {
        setContact((current) =>
          current
            ? {
                ...current,
                primary_email: email,
              }
            : current,
        );

        setPrimaryMessage(
          "Primary email saved in AMH and Keycloak.",
        );
      } else {
        setContact((current) =>
          current
            ? {
                ...current,
                secondary_email: email || null,
              }
            : current,
        );

        setSecondaryMessage(
          email
            ? "Alternative email saved."
            : "Alternative email removed.",
        );
      }
    } catch (cause) {
      const message =
        cause instanceof Error
          ? cause.message
          : "Unable to save the email.";

      if (kind === "primary") {
        setPrimaryError(message);
      } else {
        setSecondaryError(message);
      }
    } finally {
      setSaving(null);
    }
  }

  const disabled = saving !== null || loading;

  return (
    <section className="detail-panel detail-contact-panel">
      <div className="detail-section-heading">
        <Mail size={20} />
        <h2>Email addresses</h2>
      </div>

      {loading && (
        <p className="detail-muted" role="status">
          Loading contact information...
        </p>
      )}

      {loadError && (
        <div role="alert">
          <p className="detail-error">{loadError}</p>

          {!loading && (
            <button
              type="button"
              className="users-secondary-button"
              onClick={() => setRevision((value) => value + 1)}
            >
              Try again
            </button>
          )}
        </div>
      )}

      {!loading && !loadError && contact && (
        <>
          <form
            key={`primary:${userId}:${revision}`}
            className="detail-form detail-contact-form"
            onSubmit={(event) => {
              void saveEmail(event, "primary");
            }}
          >
            <fieldset disabled={disabled}>
              <label>
                Primary email
                <input
                  type="email"
                  name="primary_email"
                  defaultValue={contact.primary_email ?? ""}
                  maxLength={320}
                  required
                  autoComplete="off"
                  placeholder="Primary email"
                />
              </label>

              <p className="detail-muted">
                Changes are saved in AMH and Keycloak.
                The new email is marked as unverified.
              </p>

              <button
                type="submit"
                className="users-primary-button"
              >
                {saving === "primary"
                  ? "Saving..."
                  : "Save"}
              </button>
            </fieldset>

            {primaryError && (
              <p className="detail-error" role="alert">
                {primaryError}
              </p>
            )}

            {primaryMessage && (
              <p className="detail-success" role="status">
                {primaryMessage}
              </p>
            )}
          </form>

          <form
            key={`secondary:${userId}:${revision}`}
            className="detail-form detail-secondary-email-form"
            onSubmit={(event) => {
              void saveEmail(event, "secondary");
            }}
          >
            <fieldset disabled={disabled}>
              <label>
                Alternative email
                <input
                  type="email"
                  name="secondary_email"
                  defaultValue={contact.secondary_email ?? ""}
                  maxLength={320}
                  autoComplete="off"
                  placeholder="Optional alternative email"
                />
              </label>

              <p className="detail-muted">
                Saved in AMH. Leave empty to remove it.
              </p>

              <button
                type="submit"
                className="users-primary-button"
              >
                {saving === "secondary"
                  ? "Saving..."
                  : "Save"}
              </button>
            </fieldset>

            {secondaryError && (
              <p className="detail-error" role="alert">
                {secondaryError}
              </p>
            )}

            {secondaryMessage && (
              <p className="detail-success" role="status">
                {secondaryMessage}
              </p>
            )}
          </form>
        </>
      )}
    </section>
  );
}
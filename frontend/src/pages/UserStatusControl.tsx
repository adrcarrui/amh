import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { LockKeyhole, UnlockKeyhole } from "lucide-react";

type Props = {
  userId: string;
  isBlocked: boolean;
  onStatusChanged: (isBlocked: boolean) => void;
  onSessionExpired: () => void;
};

export function UserStatusControl({
  userId,
  isBlocked,
  onStatusChanged,
  onSessionExpired,
}: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null);

  const [requestedBlocked, setRequestedBlocked] = useState<
    boolean | null
  >(null);

  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const open = requestedBlocked !== null;

  useEffect(() => {
    const dialog = dialogRef.current;

    if (!dialog) {
      return;
    }

    if (open && !dialog.open) {
      dialog.showModal();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  function openDialog() {
    setReason("");
    setError("");
    setMessage("");
    setRequestedBlocked(!isBlocked);
  }

  function closeDialog() {
    if (!saving) {
      setRequestedBlocked(null);
    }
  }

  async function saveStatus(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (saving || requestedBlocked === null) {
      return;
    }

    const cleanReason = reason.trim();

    if (!cleanReason) {
      setError("A reason is required.");
      return;
    }

    const desiredStatus = requestedBlocked;

    setSaving(true);
    setError("");

    try {
      const response = await fetch(
        `/api/v1/admin/users/${encodeURIComponent(userId)}/status`,
        {
          method: "PATCH",
          credentials: "include",
          cache: "no-store",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            is_blocked: desiredStatus,
            expected_is_blocked: !desiredStatus,
            reason: cleanReason,
          }),
        },
      );

      if (response.status === 401) {
        setRequestedBlocked(null);
        onSessionExpired();
        return;
      }

      const data = await response.json().catch(() => null);

      if (!response.ok) {
        throw new Error(
          typeof data?.detail === "string"
            ? data.detail
            : `Unable to save: HTTP ${response.status}`,
        );
      }

      if (
        data?.saved !== true ||
        data.user_id !== userId ||
        data.is_blocked !== desiredStatus
      ) {
        throw new Error(
          "The result could not be confirmed. Reload the user page.",
        );
      }

      onStatusChanged(data.is_blocked);
      setRequestedBlocked(null);

      setMessage(
        desiredStatus
          ? "User blocked. Sessions issued by AMH have been revoked."
          : "User unblocked. A new login is required.",
      );
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "The result could not be confirmed. Reload the user page.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="detail-user-status-controls">
      <div className="detail-user-status-actions">
        <span
          className={`detail-account-status ${
            isBlocked ? "is-blocked" : "is-active"
          }`}
        >
          {isBlocked ? "Blocked" : "Active"}
        </span>

        <button
          type="button"
          className={`detail-status-button ${
            isBlocked ? "is-unblock" : "is-block"
          }`}
          onClick={openDialog}
        >
          {isBlocked ? (
            <UnlockKeyhole size={15} />
          ) : (
            <LockKeyhole size={15} />
          )}

          {isBlocked ? "Unblock user" : "Block user"}
        </button>
      </div>

      {message && (
        <p className="detail-status-message" role="status">
          {message}
        </p>
      )}

      <dialog
        ref={dialogRef}
        className="detail-status-dialog"
        aria-labelledby="user-status-dialog-title"
        onCancel={(event) => {
          if (saving) {
            event.preventDefault();
          } else {
            setRequestedBlocked(null);
          }
        }}
      >
        <form onSubmit={saveStatus}>
          <h2 id="user-status-dialog-title">
            {requestedBlocked ? "Block user" : "Unblock user"}
          </h2>

          <p className="detail-muted">
            {requestedBlocked
              ? "This prevents access through AMH and revokes sessions issued by AMH. Assigned application permissions are preserved."
              : "This allows access through AMH again, subject to the user's assigned permissions. Previous sessions remain revoked."}
          </p>

          <fieldset disabled={saving}>
            <label>
              Reason
              <textarea
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                required
                maxLength={500}
                rows={3}
                placeholder="Explain the reason for this change"
              />
            </label>

            {error && (
              <p className="detail-error" role="alert">
                {error}
              </p>
            )}

            <div className="detail-status-dialog-actions">
              <button
                type="button"
                className="users-secondary-button"
                onClick={closeDialog}
              >
                Cancel
              </button>

              <button
                type="submit"
                className={`detail-status-confirm ${
                  requestedBlocked ? "is-block" : "is-unblock"
                }`}
              >
                {saving
                  ? "Saving..."
                  : requestedBlocked
                    ? "Block user"
                    : "Unblock user"}
              </button>
            </div>
          </fieldset>
        </form>
      </dialog>
    </div>
  );
}
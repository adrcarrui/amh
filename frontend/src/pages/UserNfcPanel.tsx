import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { CreditCard, ScanLine } from "lucide-react";

type Props = {
  userId: string;
  onSessionExpired: () => void;
};

const AGENT_READ_URL =
  "http://127.0.0.1:8766/enrollment/read";

function normalizeUid(value: string): string {
  return value.replace(/[\s:-]/g, "").toUpperCase();
}

function isValidUid(value: string): boolean {
  return (
    /^[0-9A-F]{8,64}$/.test(value) &&
    value.length % 2 === 0
  );
}

export function UserNfcPanel({
  userId,
  onSessionExpired,
}: Props) {
  const [uid, setUid] = useState("");
  const [reading, setReading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [readMessage, setReadMessage] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const mounted = useRef(false);
  const readController = useRef<AbortController | null>(null);

  useEffect(() => {
    mounted.current = true;

    return () => {
      mounted.current = false;
      readController.current?.abort("unmounted");
    };
  }, []);

  async function readCard() {
    if (saving || readController.current) {
      return;
    }

    const controller = new AbortController();
    readController.current = controller;

    const timeout = window.setTimeout(() => {
      controller.abort("timeout");
    }, 20000);

    setReading(true);
    setUid("");
    setError("");
    setMessage("");
    setReadMessage("Place the card on the reader.");

    try {
      while (!controller.signal.aborted) {
        const response = await fetch(AGENT_READ_URL, {
          method: "POST",
          credentials: "include",
          cache: "no-store",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({}),
          signal: controller.signal,
        });

        if (!mounted.current || controller.signal.aborted) {
          return;
        }

        if (response.status === 401) {
          onSessionExpired();
          return;
        }

        if (response.status === 204) {
          setReadMessage("Place the card on the reader.");
        } else {
          const data = await response.json().catch(() => null);

          if (!mounted.current || controller.signal.aborted) {
            return;
          }

          if (!response.ok) {
            throw new Error(
              typeof data?.detail === "string"
                ? data.detail
                : `Unable to read the card: HTTP ${response.status}`,
            );
          }

          if (data?.status === "remove_card") {
            setReadMessage(
              "Remove the card, wait a moment, then place it on the reader again.",
            );
          } else if (typeof data?.uid === "string") {
            const capturedUid = normalizeUid(data.uid);

            if (!isValidUid(capturedUid)) {
              throw new Error(
                "The reader returned an invalid card UID.",
              );
            }

            setUid(capturedUid);
            setReadMessage("");
            setMessage(
              "Card read successfully. Press Save to assign it to this user.",
            );

            return;
          } else {
            throw new Error(
              "The NFC agent returned an invalid response.",
            );
          }
        }

        await new Promise<void>((resolve) => {
          window.setTimeout(resolve, 400);
        });
      }
    } catch (cause) {
      if (!mounted.current) {
        return;
      }

      if (!controller.signal.aborted) {
        setError(
          cause instanceof TypeError
            ? "Cannot reach the NFC agent. Check that it is running on this computer."
            : cause instanceof Error
              ? cause.message
              : "Unable to read the card.",
        );
      }
    } finally {
      window.clearTimeout(timeout);

      if (readController.current === controller) {
        readController.current = null;
      }

      if (mounted.current) {
        setReading(false);
        setReadMessage("");

        if (
          controller.signal.aborted &&
          controller.signal.reason === "timeout"
        ) {
          setError(
            "No card was captured within 20 seconds. Try again.",
          );
        }

        if (
          controller.signal.aborted &&
          controller.signal.reason === "cancelled"
        ) {
          setMessage("Card reading cancelled.");
        }
      }
    }
  }

  async function assignCard(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (saving || reading) {
      return;
    }

    const normalizedUid = normalizeUid(uid);

    if (!isValidUid(normalizedUid)) {
      setError("Enter or read a valid hexadecimal card UID.");
      return;
    }

    setSaving(true);
    setError("");
    setMessage("");

    try {
      const response = await fetch(
        `/api/v1/admin/users/${encodeURIComponent(userId)}/cards`,
        {
          method: "POST",
          credentials: "include",
          cache: "no-store",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            raw_uid: normalizedUid,
          }),
        },
      );

      if (!mounted.current) {
        return;
      }

      if (response.status === 401) {
        onSessionExpired();
        return;
      }

      if (!response.ok) {
        const data = await response.json().catch(() => null);

        throw new Error(
          typeof data?.detail === "string"
            ? data.detail
            : `Unable to assign the card: HTTP ${response.status}`,
        );
      }

      if (mounted.current) {
        setUid("");
        setMessage("Card assigned successfully.");
      }
    } catch (cause) {
      if (mounted.current) {
        setError(
          cause instanceof TypeError
            ? "The assignment result could not be confirmed. Check the user's cards before retrying."
            : cause instanceof Error
              ? cause.message
              : "Unable to assign the card.",
        );
      }
    } finally {
      if (mounted.current) {
        setSaving(false);
      }
    }
  }

  return (
    <section className="detail-panel detail-nfc-panel">
      <div className="detail-nfc-heading">
        <div className="detail-section-heading">
          <CreditCard size={20} />
          <h2>NFC card</h2>
        </div>

        <button
          type="button"
          className="users-secondary-button detail-nfc-read"
          disabled={saving}
          onClick={() => {
            if (reading) {
              readController.current?.abort("cancelled");
            } else {
              void readCard();
            }
          }}
        >
          <ScanLine size={16} />
          {reading ? "Cancel reading" : "Read card"}
        </button>
      </div>

      <p className="detail-muted">
        Read a card or enter its UID, then save to assign it.
      </p>

      {reading && (
        <p className="detail-nfc-reading" role="status">
          {readMessage}
        </p>
      )}

      <form className="detail-form" onSubmit={assignCard}>
        <fieldset disabled={saving || reading}>
          <label>
            Card UID
            <input
              name="raw_uid"
              value={uid}
              onChange={(event) => {
                setUid(event.target.value);
                setMessage("");
                setError("");
              }}
              required
              minLength={8}
              maxLength={64}
              autoComplete="off"
              spellCheck={false}
              placeholder="Read a card or enter its UID"
            />
          </label>

          <button
            className="users-primary-button"
            type="submit"
            disabled={!uid.trim()}
          >
            {saving ? "Saving..." : "Save"}
          </button>
        </fieldset>

        {error && (
          <p className="detail-error" role="alert">
            {error}
          </p>
        )}

        {message && (
          <p className="detail-success" role="status">
            {message}
          </p>
        )}
      </form>
    </section>
  );
}
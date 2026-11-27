(() => {
  const AGENT = "http://127.0.0.1:8766";
  const airbusLogo = new URL("../img/airbus-white.svg", document.currentScript.src);

  const CLIENTS = {
    amh_admin_dev: {
      backend: "http://127.0.0.1:8001",
      destination: "http://127.0.0.1:5174/",
      portal: true,
    },
    mysim_dashboard_dev: {
      backend: "http://127.0.0.1:8000",
      destination: "http://127.0.0.1:5173/",
      portal: false,
    },
  };

  const NFC_COPY = {
    english: {
      label: "Contactless card sign-in",
      title: "Sign in with your card",
      prepare: "Getting the card reader ready…",
      retry: "Try again",
      startError: "Card sign-in is unavailable. Try again.",
      invalidChallenge: "Could not start a card sign-in attempt.",
      scanPrompt: "Hold your card near the reader.",
      removeCard: "Move your card away, then hold it near the reader again.",
      recognized: "Card recognized. Signing you in…",
      finishError: "Could not sign you in. Try again.",
      sessionError: "Could not confirm your AMH session.",
      unexpectedScan: "The card reader returned an unexpected response.",
      readError: "Could not read your card. Try again.",
      connectionError: "Could not connect to AMH or the card reader. Check that both are running.",
      genericError: "Could not sign in with your card.",
    },
    spanish: {
      label: "Acceso con tarjeta NFC",
      title: "O entra con tu tarjeta",
      prepare: "Preparando inicio con tarjeta...",
      retry: "Reintentar lectura",
      startError: "No se pudo iniciar NFC",
      invalidChallenge: "Desafio NFC no valido",
      scanPrompt: "Acerca tu tarjeta al lector ACR122U",
      removeCard: "Retira la tarjeta y vuelve a acercarla",
      recognized: "Tarjeta reconocida. Iniciando sesion...",
      finishError: "No se pudo crear la sesion",
      unexpectedScan: "Respuesta del agente NFC no valida",
      readError: "No se pudo leer la tarjeta",
      connectionError: "No se pudo conectar con AMH o el agente NFC. Comprueba que esten iniciados.",
      genericError: "No se pudo iniciar sesion con la tarjeta",
    },
  };

  const ENGLISH_ERROR_DETAILS = new Map([
    ["Lector no disponible", "Card reader unavailable."],
    ["AMH no disponible", "AMH is unavailable."],
    ["El intento NFC no pertenece a este navegador. Reintenta.", "This card sign-in attempt belongs to another browser session. Try again."],
    ["Tarjeta no autorizada, usuario bloqueado o intento NFC caducado.", "The card is unauthorized, the account is blocked, or the sign-in attempt expired."],
  ]);

  async function responseError(response, fallback, useEnglish) {
    const data = await response.json().catch(() => null);

    if (useEnglish) {
      return ENGLISH_ERROR_DETAILS.get(data?.detail) ?? fallback;
    }

    return typeof data?.detail === "string"
      ? data.detail
      : fallback + " (HTTP " + response.status + ")";
  }

  function applyPortalBranding() {
    document.body.classList.add("amh-portal-login");

    const heading = document.getElementById("kc-header-wrapper");
    if (heading) {
      heading.replaceChildren();
      for (const [index, word] of ["Access", "Management", "Hub"].entries()) {
        if (index > 0) heading.append(" ");
        const initial = document.createElement("span");
        initial.className = "amh-brand-initial";
        initial.textContent = word[0];
        heading.append(initial, word.slice(1));
      }
    }

    const footer = document.createElement("footer");
    footer.className = "amh-brand-footer";
    const logo = document.createElement("img");
    logo.src = airbusLogo.href;
    logo.alt = "Airbus";
    logo.width = 402;
    logo.height = 77;
    footer.append(logo);
    document.body.append(footer);
  }

  function main() {
    const pageClientId = new URL(location.href).searchParams.get("client_id");
    if (document.getElementById("kc-logout-confirm")) {
      if (CLIENTS[pageClientId]?.portal === true) applyPortalBranding();
      return;
    }

    const form = document.querySelector("#kc-form-login");

    if (!form || form.dataset.amhNfcReady === "1") {
      return;
    }

    const actionClientId = new URL(
      form.action,
      location.href,
    ).searchParams.get("client_id");

    const clientId = actionClientId ?? pageClientId;

    if (
      !Object.prototype.hasOwnProperty.call(
        CLIENTS,
        clientId,
      )
    ) {
      return;
    }

    const config = CLIENTS[clientId];
    const copy = config.portal ? NFC_COPY.english : NFC_COPY.spanish;
    form.dataset.amhNfcReady = "1";

    if (config.portal) {
      applyPortalBranding();
      document.body.classList.add("amh-portal-sign-in");
    }

    const box = document.createElement("section");
    box.classList.add("amh-nfc-login");
    box.setAttribute(
      "aria-label",
      copy.label,
    );
    if (!config.portal) {
      box.style.cssText =
        "margin-top:1.5rem;padding-top:1.25rem;" +
        "border-top:1px solid #d2d2d2;text-align:center";
    }

    const title = document.createElement("strong");
    title.textContent = copy.title;

    const message = document.createElement("p");
    message.setAttribute("aria-live", "polite");
    message.style.marginTop = "0.75rem";
    message.textContent = copy.prepare;

    const retry = document.createElement("button");
    retry.type = "button";
    retry.textContent = copy.retry;
    retry.hidden = true;

    box.append(title, message, retry);
    form.insertAdjacentElement("afterend", box);

    let stopped = false;
    let running = false;
    let activeController = null;

    function stop() {
      stopped = true;
      activeController?.abort();
    }

    form.addEventListener("submit", stop);

    window.addEventListener(
      "pagehide",
      stop,
      { once: true },
    );

    const pause = (ms) =>
      new Promise((resolve) => {
        window.setTimeout(resolve, ms);
      });

    async function scanLoop() {
      if (running || stopped) {
        return;
      }

      running = true;
      retry.hidden = true;

      const controller = new AbortController();
      activeController = controller;

      try {
        while (!stopped) {
          message.textContent =
            copy.prepare;

          const start = await fetch(
            config.backend + "/auth/nfc/start",
            {
              method: "POST",
              credentials: "include",
              cache: "no-store",
              signal: controller.signal,
            },
          );

          if (!start.ok) {
            throw new Error(
              await responseError(
                start,
                copy.startError,
                config.portal,
              ),
            );
          }

          const data = await start.json();
          const challenge = data.challenge;

          if (
            typeof challenge !== "string" ||
            !/^[A-Za-z0-9_-]{43}$/.test(challenge)
          ) {
            throw new Error(
              copy.invalidChallenge,
            );
          }

          const seconds =
            typeof data.expires_in_seconds === "number" &&
            Number.isFinite(data.expires_in_seconds)
              ? Math.min(
                  Math.max(data.expires_in_seconds, 3),
                  90,
                )
              : 90;

          const deadline =
            Date.now() + (seconds - 2) * 1000;

          message.textContent =
            copy.scanPrompt;

          while (
            !stopped &&
            Date.now() < deadline
          ) {
            const scan = await fetch(
              AGENT + "/scan",
              {
                method: "POST",
                credentials: "omit",
                headers: {
                  "Content-Type": "application/json",
                },
                body: JSON.stringify({ challenge }),
                cache: "no-store",
                signal: controller.signal,
              },
            );

            if (scan.status === 204) {
              message.textContent =
                copy.scanPrompt;
            } else if (scan.ok) {
              const result = await scan.json();

              if (result.status === "remove_card") {
                message.textContent =
                  copy.removeCard;
              } else if (
                result.status === "verified"
              ) {
                message.textContent =
                  copy.recognized;

                const finish = await fetch(
                  config.backend + "/auth/nfc/finish",
                  {
                    method: "POST",
                    credentials: "include",
                    headers: {
                      "Content-Type": "application/json",
                    },
                    body: JSON.stringify({ challenge }),
                    cache: "no-store",
                    signal: controller.signal,
                  },
                );

                if (!finish.ok) {
                  throw new Error(
                    await responseError(
                      finish,
                      copy.finishError,
                      config.portal,
                    ),
                  );
                }

                if (config.portal) {
                  const session = await finish.json();

                  if (
                    session.authenticated !== true
                  ) {
                    throw new Error(
                      copy.sessionError,
                    );
                  }
                }

                stop();

                window.location.assign(
                  config.destination,
                );
                return;
              } else {
                throw new Error(
                  copy.unexpectedScan,
                );
              }
            } else {
              throw new Error(
                await responseError(
                  scan,
                  copy.readError,
                  config.portal,
                ),
              );
            }

            await pause(400);
          }
        }
      } catch (error) {
        if (!stopped) {
          message.textContent =
            error instanceof TypeError
              ? copy.connectionError
              : error instanceof Error && error.message && !(error instanceof SyntaxError)
                ? error.message
                : copy.genericError;

          retry.hidden = false;
        }
      } finally {
        running = false;

        if (activeController === controller) {
          activeController = null;
        }
      }
    }

    retry.addEventListener("click", () => {
      void scanLoop();
    });

    void scanLoop();
  }

  if (document.readyState === "loading") {
    document.addEventListener(
      "DOMContentLoaded",
      main,
      { once: true },
    );
  } else {
    main();
  }
})();
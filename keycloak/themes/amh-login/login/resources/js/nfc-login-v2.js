(() => {
  const AGENT = "http://127.0.0.1:8766";

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

  async function responseError(response, fallback) {
    const data = await response.json().catch(() => null);

    return typeof data?.detail === "string"
      ? data.detail
      : fallback + " (HTTP " + response.status + ")";
  }

  function main() {
    const form = document.querySelector("#kc-form-login");

    if (!form || form.dataset.amhNfcReady === "1") {
      return;
    }

    const actionClientId = new URL(
      form.action,
      location.href,
    ).searchParams.get("client_id");

    const pageClientId = new URL(
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
    form.dataset.amhNfcReady = "1";

    const box = document.createElement("section");
    box.setAttribute(
      "aria-label",
      "Acceso con tarjeta NFC",
    );
    box.style.cssText =
      "margin-top:1.5rem;padding-top:1.25rem;" +
      "border-top:1px solid #d2d2d2;text-align:center";

    const title = document.createElement("strong");
    title.textContent = "O entra con tu tarjeta";

    const message = document.createElement("p");
    message.setAttribute("aria-live", "polite");
    message.style.marginTop = "0.75rem";
    message.textContent = "Preparando lector NFC...";

    const retry = document.createElement("button");
    retry.type = "button";
    retry.textContent = "Reintentar lectura";
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
            "Preparando inicio con tarjeta...";

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
                "No se pudo iniciar NFC",
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
              "Desafio NFC no valido",
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
            "Acerca tu tarjeta al lector ACR122U";

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
                "Acerca tu tarjeta al lector ACR122U";
            } else if (scan.ok) {
              const result = await scan.json();

              if (result.status === "remove_card") {
                message.textContent =
                  "Retira la tarjeta y vuelve a acercarla";
              } else if (
                result.status === "verified"
              ) {
                message.textContent =
                  "Tarjeta reconocida. Iniciando sesion...";

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
                      "No se pudo crear la sesion",
                    ),
                  );
                }

                if (config.portal) {
                  const session = await finish.json();

                  if (
                    session.authenticated !== true
                  ) {
                    throw new Error(
                      "No se pudo confirmar la sesion AMH",
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
                  "Respuesta del agente NFC no valida",
                );
              }
            } else {
              throw new Error(
                await responseError(
                  scan,
                  "No se pudo leer la tarjeta",
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
              ? "No se pudo conectar con AMH o el agente NFC. Comprueba que esten iniciados."
              : error instanceof Error
                ? error.message
                : "No se pudo iniciar sesion con la tarjeta";

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
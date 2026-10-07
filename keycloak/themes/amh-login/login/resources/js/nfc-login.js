(() => {
  const BACKEND = "http://127.0.0.1:8000";
  const AGENT = "http://127.0.0.1:8766";
  const DASHBOARD = "http://127.0.0.1:5173/";

  async function main() {
    const form = document.querySelector("#kc-form-login");
    if (!form) return;

    // El tema se aplica a todo amh-dev. Solo activamos NFC
    // cuando Keycloak está mostrando el login de mySim.
    const actionClientId = new URL(form.action).searchParams.get("client_id");
    const pageClientId = new URL(location.href).searchParams.get("client_id");
    if ((actionClientId ?? pageClientId) !== "mysim_dashboard_dev") return;

    const box = document.createElement("section");
    box.setAttribute("aria-label", "Inicio de sesión con tarjeta NFC");
    box.style.cssText =
      "margin-top:1.5rem;padding-top:1.25rem;" +
      "border-top:1px solid #d2d2d2;text-align:center";

    const title = document.createElement("strong");
    title.textContent = "O entra con tu tarjeta";

    const message = document.createElement("p");
    message.setAttribute("aria-live", "polite");
    message.textContent = "Preparando lector NFC…";
    message.style.marginTop = "0.75rem";

    const retry = document.createElement("button");
    retry.type = "button";
    retry.textContent = "Reintentar lectura";
    retry.hidden = true;

    box.append(title, message, retry);
    form.insertAdjacentElement("afterend", box);

    let stopped = false;
    let controller = new AbortController();

    function stop() {
      stopped = true;
      controller.abort();
    }

    // Si se usa usuario y contraseña, dejamos de leer la tarjeta.
    form.addEventListener("submit", stop);
    window.addEventListener("pagehide", stop, { once: true });

    const pause = (ms) =>
      new Promise((resolve) => window.setTimeout(resolve, ms));

    async function scanLoop() {
      retry.hidden = true;

      try {
        while (!stopped) {
          message.textContent = "Preparando inicio con tarjeta…";

          const start = await fetch(`${BACKEND}/auth/nfc/start`, {
            method: "POST",
            credentials: "include",
            cache: "no-store",
            signal: controller.signal,
          });

          if (!start.ok) {
            throw new Error(`No se pudo iniciar NFC: HTTP ${start.status}`);
          }

          const data = await start.json();
          const challenge = data.challenge;

          if (typeof challenge !== "string" || !challenge) {
            throw new Error("Desafío NFC no válido");
          }

          const seconds =
            typeof data.expires_in_seconds === "number"
              ? data.expires_in_seconds
              : 90;

          const deadline =
            Date.now() + Math.max(seconds - 2, 1) * 1000;

          message.textContent = "Acerca tu tarjeta al lector ACR122U";

          while (!stopped && Date.now() < deadline) {
            const scan = await fetch(`${AGENT}/scan`, {
              method: "POST",
              credentials: "omit",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ challenge }),
              cache: "no-store",
              signal: controller.signal,
            });

            if (scan.status === 200) {
              const result = await scan.json();

              if (result.status === "remove_card") {
                message.textContent =
                  "Retira la tarjeta y vuelve a acercarla";
              }

              if (result.status === "verified") {
                message.textContent =
                  "Tarjeta reconocida. Iniciando sesión…";

                const finish = await fetch(
                  `${BACKEND}/auth/nfc/finish`,
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
                    `No se pudo crear la sesión: HTTP ${finish.status}`,
                  );
                }

                stop();
                window.location.assign(DASHBOARD);
                return;
              }
            } else if (scan.status === 204) {
              message.textContent =
                "Acerca tu tarjeta al lector ACR122U";
            } else {
              throw new Error(
                `El lector devolvió HTTP ${scan.status}`,
              );
            }

            await pause(300);
          }

          // Caducó el intento: solicita otro y sigue esperando.
        }
      } catch (error) {
        if (stopped) return;
        message.textContent =
          error instanceof Error
            ? error.message
            : "No se pudo leer la tarjeta";
        retry.hidden = false;
      }
    }

    retry.addEventListener("click", () => {
      controller.abort();
      controller = new AbortController();
      void scanLoop();
    });

    void scanLoop();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", main, { once: true });
  } else {
    void main();
  }
})();
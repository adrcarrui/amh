from html import escape
from urllib.parse import urlencode, urlsplit
from uuid import UUID

from authlib.integrations.base_client.errors import OAuthError
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from app.user_contact_routes import router as user_contact_router
from app.portal_nfc_routes import portal_nfc_app
from app.user_primary_email_routes import router as user_primary_email_router
from app.user_status_routes import router as user_status_router
from app.models.user_aturnos_link import UserATurnosLink
from app.aturnos_routes import router as aturnos_router
from app.admin_routes import router as admin_router
from app.application_access_routes import router as application_access_router
from app.application_session_routes import router as application_session_router
from app.authorization import has_application_access
from app.config import settings
from app.db import SessionLocal
from app.models import Application, User, UserApplicationAccess, UserEmail
from app.nfc_routes import router as nfc_router
from app.oidc import oauth
from app.maintenance_directory_routes import (
    router as maintenance_directory_router,
)
from app.briefing_directory_routes import (
    router as briefing_directory_router,
)
from app.session_service import (
    create_portal_session,
    get_admin_session_user_id,
    get_portal_session_user_id,
    revoke_admin_session,
)


SESSION_COOKIE = "amh_session"
SESSION_MAX_AGE = 8 * 60 * 60
FRONTEND_URL = "http://127.0.0.1:5174"


# Estilos de las páginas administrativas que todavía viven en el backend.
UI_STYLE = """
<style>
  :root {
    font-family: system-ui, sans-serif;
    color: #172638;
    background: #f3f6fa;
  }

  body { margin: 0; }

  main {
    box-sizing: border-box;
    max-width: 1050px;
    min-height: 100vh;
    margin: 0 auto;
    padding: 40px 28px 80px;
    background: white;
  }

  h1 { margin: 18px 0 28px; font-size: 2rem; }
  h2 { margin-top: 38px; font-size: 1.3rem; }
  a { color: #145a96; }
  a:hover { color: #0b3c68; }

  form, section {
    max-width: 680px;
    margin: 24px 0;
    padding: 24px;
    border: 1px solid #dce4ec;
    border-radius: 12px;
  }

  label { font-weight: 600; }

  input, select {
    box-sizing: border-box;
    width: 100%;
    max-width: 440px;
    margin-top: 7px;
    padding: 10px 12px;
    border: 1px solid #aebdca;
    border-radius: 7px;
    font: inherit;
  }

  button {
    padding: 10px 16px;
    border: 0;
    border-radius: 7px;
    background: #145a96;
    color: white;
    font: inherit;
    font-weight: 600;
    cursor: pointer;
  }

  button:hover { background: #0b3c68; }
  button:disabled { opacity: .6; cursor: wait; }
  :focus-visible { outline: 3px solid #e7a935; outline-offset: 3px; }

  table { width: 100%; border-collapse: collapse; }
  th, td { padding: 12px; border: 1px solid #dce4ec; text-align: left; }
  th { background: #eef3f8; }
  tr:nth-child(even) { background: #f8fafc; }
  code { overflow-wrap: anywhere; }

  @media (max-width: 650px) {
    main { padding: 24px 16px; }
    table { display: block; overflow-x: auto; }
  }
</style>
"""


app = FastAPI(title="AMH - Access Management Hub")
app.mount("/auth/nfc", portal_nfc_app)

app.include_router(admin_router)
app.include_router(nfc_router)
app.include_router(application_access_router)
app.include_router(application_session_router)
app.include_router(aturnos_router)
app.include_router(user_contact_router)
app.include_router(user_primary_email_router)
app.include_router(user_status_router)
app.include_router(maintenance_directory_router)
app.include_router(briefing_directory_router)
# Cookie temporal usada por Authlib durante el flujo OIDC.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.amh_oidc_state_secret.get_secret_value(),
    session_cookie="amh_oidc_flow",
    max_age=300,
    same_site="lax",
    https_only=False,
)


def _create_session_for_subject(subject: str) -> str | None:
    with SessionLocal.begin() as db:
        user = db.scalar(
            select(User).where(User.keycloak_subject == subject)
        )
        if user is None or user.is_blocked:
            return None

        return create_portal_session(db, user_id=user.id)


def _current_portal_id(token: str | None):
    if not token:
        return None

    with SessionLocal.begin() as db:
        return get_portal_session_user_id(db, token=token)


def _portal_applications(user_id):
    with SessionLocal.begin() as db:
        rows = db.execute(
            select(
                Application.code,
                Application.display_name,
                Application.launch_url,
            )
            .join(
                UserApplicationAccess,
                UserApplicationAccess.application_id == Application.id,
            )
            .where(
                UserApplicationAccess.user_id == user_id,
                UserApplicationAccess.status == "active",
                Application.is_enabled.is_(True),
                Application.code != "amh",
                Application.launch_url.is_not(None),
            )
            .order_by(Application.display_name)
        ).all()

        return [
            {
                "code": code,
                "display_name": display_name,
                "launch_url": launch_url,
            }
            for code, display_name, launch_url in rows
        ]


def _is_portal_admin(user_id) -> bool:
    with SessionLocal.begin() as db:
        return has_application_access(
            db,
            user_id=user_id,
            application_code="amh",
            minimum_role="admin",
        )


def _revoke_session(token: str | None) -> None:
    if token:
        with SessionLocal.begin() as db:
            revoke_admin_session(db, token=token)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
async def portal_entry():
    return RedirectResponse(
        url=f"{FRONTEND_URL}/",
        status_code=303,
        headers={"Cache-Control": "no-store"},
    )


@app.get("/auth/login")
async def auth_login(request: Request):
    request.session.clear()

    return await oauth.keycloak.authorize_redirect(
        request,
        settings.amh_oidc_redirect_uri,
    )


@app.get("/auth/callback")
async def auth_callback(request: Request):
    try:
        token = await oauth.keycloak.authorize_access_token(request)
        subject = token["userinfo"]["sub"]
    except (OAuthError, KeyError, TypeError):
        request.session.clear()
        raise HTTPException(
            status_code=401,
            detail="No se pudo validar el login con Keycloak.",
        ) from None

    request.session.clear()

    session_token = await run_in_threadpool(
        _create_session_for_subject,
        subject,
    )
    if session_token is None:
        raise HTTPException(
            status_code=403,
            detail="Usuario AMH no registrado o bloqueado.",
        )

    response = RedirectResponse(
        url=f"{FRONTEND_URL}/",
        status_code=303,
        headers={"Cache-Control": "no-store"},
    )
    response.set_cookie(
        key=SESSION_COOKIE,
        value=session_token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=False,
        samesite="lax",
        path="/",
    )
    return response


@app.get("/auth/me")
async def auth_me(request: Request):
    user_id = await run_in_threadpool(
        _current_portal_id,
        request.cookies.get(SESSION_COOKIE),
    )
    if user_id is None:
        response = JSONResponse(
            {"detail": "Sesión ausente, caducada o revocada."},
            status_code=401,
            headers={"Cache-Control": "no-store"},
        )
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    return RedirectResponse(
        url=f"{FRONTEND_URL}/",
        status_code=303,
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/v1/portal/me")
async def portal_me(request: Request):
    user_id = await run_in_threadpool(
        _current_portal_id,
        request.cookies.get(SESSION_COOKIE),
    )
    if user_id is None:
        return JSONResponse(
            {"detail": "Sesión ausente, caducada o revocada."},
            status_code=401,
            headers={"Cache-Control": "no-store"},
        )

    applications = await run_in_threadpool(
        _portal_applications,
        user_id,
    )
    is_admin = await run_in_threadpool(
        _is_portal_admin,
        user_id,
    )

    return JSONResponse(
        {
            "user_id": str(user_id),
            "applications": applications,
            "is_admin": is_admin,
        },
        headers={"Cache-Control": "no-store"},
    )


@app.post("/auth/logout")
async def auth_logout(request: Request):
    callback = urlsplit(settings.amh_oidc_redirect_uri)
    backend_origin = f"{callback.scheme}://{callback.netloc}"

    if request.headers.get("origin") not in {
        backend_origin,
        FRONTEND_URL,
    }:
        raise HTTPException(
            status_code=403,
            detail="Origin not allowed",
        )

    await run_in_threadpool(
        _revoke_session,
        request.cookies.get(SESSION_COOKIE),
    )
    request.session.clear()

    post_logout_uri = f"{backend_origin}/auth/logged-out"
    logout_url = (
        f"{settings.amh_oidc_issuer.rstrip('/')}"
        "/protocol/openid-connect/logout?"
        + urlencode(
            {
                "client_id": settings.amh_oidc_client_id,
                "post_logout_redirect_uri": post_logout_uri,
            }
        )
    )

    response = RedirectResponse(
        url=logout_url,
        status_code=303,
        headers={"Cache-Control": "no-store"},
    )
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@app.get("/auth/logged-out")
def logged_out():
    return RedirectResponse(
        url=f"{FRONTEND_URL}/",
        status_code=303,
        headers={"Cache-Control": "no-store"},
    )


def _admin_user_rows(session_token: str):
    with SessionLocal.begin() as db:
        admin_id = get_admin_session_user_id(db, token=session_token)
        if admin_id is None:
            return None

        return db.execute(
            select(
                User.id,
                User.name,
                User.surname,
                User.is_blocked,
                UserEmail.email,
            )
            .outerjoin(
                UserEmail,
                (UserEmail.user_id == User.id)
                & (UserEmail.kind == "primary"),
            )
            .order_by(User.name, User.surname, User.id)
        ).all()

@app.get("/api/v1/admin/users/{user_id}")
async def admin_user_detail_api(
    user_id: UUID,
    request: Request,
):
    session_token = request.cookies.get(SESSION_COOKIE)

    if not session_token:
        return JSONResponse(
            {"detail": "Sesión no iniciada"},
            status_code=401,
            headers={"Cache-Control": "no-store"},
        )

    try:
        detail = await run_in_threadpool(
            _admin_user_detail,
            session_token,
            user_id,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    if detail is None:
        return JSONResponse(
            {"detail": "Sesión no válida o permiso admin requerido"},
            status_code=401,
            headers={"Cache-Control": "no-store"},
        )

    return JSONResponse(
        {
            "id": str(user_id),
            "name": detail["name"],
            "surname": detail["surname"],
            "primary_email": (
                None if detail["email"] == "—" else detail["email"]
            ),
            "is_blocked": detail["is_blocked"],
            "aturnos_links": detail["aturnos_links"],
            "grants": [
                {
                    "display_name": display_name,
                    "application_code": code,
                    "role": role,
                    "status": status,
                }
                for display_name, code, role, status in detail["grants"]
            ],
            "applications": [
                {
                    "code": code,
                    "display_name": display_name,
                }
                for code, display_name in detail["applications"]
            ],
        },
        headers={"Cache-Control": "no-store"},
    )

@app.get("/admin/users")
async def admin_users_page(request: Request):
    session_token = request.cookies.get(SESSION_COOKIE)
    if not session_token:
        raise HTTPException(status_code=401, detail="Sesión no iniciada")

    rows = await run_in_threadpool(_admin_user_rows, session_token)
    if rows is None:
        raise HTTPException(
            status_code=403,
            detail="Se requiere el rol admin de AMH",
        )

    table_rows = "".join(
        "<tr>"
        f'<td><a href="/admin/users/{user_id}">'
        f"{escape(name)} {escape(surname or '')}</a></td>"
        f"<td>{escape(email or '—')}</td>"
        f"<td>{'Bloqueado' if is_blocked else 'Activo'}</td>"
        f"<td><code>{escape(str(user_id))}</code></td>"
        "</tr>"
        for user_id, name, surname, is_blocked, email in rows
    )

    script = """
    <script>
      const form = document.querySelector("#create-user-form");
      const result = document.querySelector("#create-user-result");

      form.addEventListener("submit", async (event) => {
        event.preventDefault();

        const button = form.querySelector('button[type="submit"]');
        const fields = new FormData(form);

        result.replaceChildren();
        button.disabled = true;

        try {
          const response = await fetch("/api/v1/admin/users", {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              username: fields.get("username"),
              name: fields.get("name"),
              surname: fields.get("surname"),
              email: fields.get("email"),
            }),
          });

          const data = await response.json();

          if (!response.ok) {
            result.textContent =
              typeof data.detail === "string"
                ? data.detail
                : `No se pudo crear el usuario: HTTP ${response.status}`;
            return;
          }

          const notice = document.createElement("p");
          notice.textContent =
            "Usuario creado. Entrega esta contraseña temporal " +
            "por un canal seguro; se mostrará solo ahora.";

          const password = document.createElement("code");
          password.textContent = data.temporary_password;

          const link = document.createElement("a");
          link.href = `/admin/users/${encodeURIComponent(data.user_id)}`;
          link.textContent = "Abrir ficha y asignar aplicaciones";

          result.append(
            notice,
            password,
            document.createElement("br"),
            link,
          );
          form.reset();
        } catch {
          result.textContent = "No se pudo conectar con AMH.";
        } finally {
          button.disabled = false;
        }
      });
    </script>
    """

    return HTMLResponse(
        "<!doctype html>"
        '<html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"{UI_STYLE}"
        "<title>Usuarios · AMH</title></head><body>"
        "<main>"
        '<p><a href="/auth/me">← Mis aplicaciones</a></p>'
        "<h1>Gestión de usuarios</h1>"
        "<h2>Crear usuario</h2>"
        '<form id="create-user-form" autocomplete="off">'
        '<p><label>Username<br>'
        '<input name="username" required minlength="3" maxlength="100">'
        "</label></p>"
        '<p><label>Nombre<br>'
        '<input name="name" required maxlength="100"></label></p>'
        '<p><label>Apellidos<br>'
        '<input name="surname" required maxlength="150"></label></p>'
        '<p><label>Email principal<br>'
        '<input name="email" type="email" required maxlength="320">'
        "</label></p>"
        '<button type="submit">Crear usuario</button>'
        "</form>"
        '<div id="create-user-result" role="status"></div>'
        "<h2>Usuarios registrados</h2>"
        '<table border="1" cellpadding="8">'
        "<thead><tr><th>Nombre</th><th>Email principal</th>"
        "<th>Estado</th><th>ID</th></tr></thead>"
        f"<tbody>{table_rows}</tbody>"
        "</table>"
        f"{script}"
        "</main></body></html>",
        headers={"Cache-Control": "no-store"},
    )


def _admin_user_detail(session_token: str, user_id: UUID):
    with SessionLocal.begin() as db:
        admin_id = get_admin_session_user_id(db, token=session_token)
        if admin_id is None:
            return None

        user = db.get(User, user_id)
        if user is None:
            raise LookupError("Usuario no encontrado")

        email = db.scalar(
            select(UserEmail.email).where(
                UserEmail.user_id == user_id,
                UserEmail.kind == "primary",
            )
        )

        grants = db.execute(
            select(
                Application.display_name,
                Application.code,
                UserApplicationAccess.role,
                UserApplicationAccess.status,
            )
            .join(
                UserApplicationAccess,
                UserApplicationAccess.application_id == Application.id,
            )
            .where(UserApplicationAccess.user_id == user_id)
            .order_by(Application.display_name)
        ).all()

        applications = db.execute(
            select(Application.code, Application.display_name)
            .where(
                Application.is_enabled.is_(True),
                Application.code != "amh",
            )
            .order_by(Application.display_name)
        ).all()

        aturnos_links = db.scalars(
            select(UserATurnosLink)
            .where(UserATurnosLink.user_id == user_id)
            .order_by(
                UserATurnosLink.id_aturno,
                UserATurnosLink.id_user,
            )
        ).all()

        return {
            "name": user.name,
            "surname": user.surname or "",
            "email": email or "—",
            "is_blocked": user.is_blocked,
            "grants": grants,
            "applications": applications,
            "aturnos_links": [
                {
                    "id_aturno": link.id_aturno,
                    "id_user": link.id_user,
                }
                for link in aturnos_links
            ],
        }


@app.get("/admin/users/{user_id}")
async def admin_user_detail_page(user_id: UUID, request: Request):
    session_token = request.cookies.get(SESSION_COOKIE)
    if not session_token:
        raise HTTPException(status_code=401, detail="Sesión no iniciada")

    try:
        detail = await run_in_threadpool(
            _admin_user_detail,
            session_token,
            user_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if detail is None:
        raise HTTPException(
            status_code=403,
            detail="Se requiere el rol admin de AMH",
        )

    grant_rows = "".join(
        "<tr>"
        f"<td>{escape(display_name)}</td>"
        f"<td>{escape(code)}</td>"
        f"<td>{escape(role)}</td>"
        f"<td>{escape(status)}</td>"
        "</tr>"
        for display_name, code, role, status in detail["grants"]
    )

    grant_table = (
        '<table border="1" cellpadding="8">'
        "<thead><tr><th>Aplicación</th><th>Código</th>"
        "<th>Rol</th><th>Estado</th></tr></thead>"
        f"<tbody>{grant_rows}</tbody></table>"
        if grant_rows
        else "<p>Este usuario no tiene aplicaciones asignadas.</p>"
    )

    application_options = "".join(
        f'<option value="{escape(code, quote=True)}">'
        f"{escape(display_name)}</option>"
        for code, display_name in detail["applications"]
    )

    if application_options:
        access_form = (
            "<h2>Asignar o cambiar acceso</h2>"
            '<form id="access-form">'
            '<p><label>Aplicación<br>'
            '<select name="application_code" required>'
            f"{application_options}"
            "</select></label></p>"
            '<p><label>Rol<br><select name="role">'
            '<option value="viewer">Viewer</option>'
            '<option value="editor">Editor</option>'
            '<option value="admin">Admin</option>'
            "</select></label></p>"
            '<p><label>Estado<br><select name="status">'
            '<option value="active">Activo</option>'
            '<option value="blocked">Bloqueado</option>'
            '<option value="revoked">Revocado</option>'
            "</select></label></p>"
            '<p><label>Motivo<br>'
            '<input name="reason" maxlength="500"></label></p>'
            '<button type="submit">Guardar acceso</button>'
            '<p id="access-result" role="status"></p>'
            "</form>"
            "<p>Para una primera asignación, selecciona «Activo». "
            "Para bloquear o revocar debe existir una asignación previa.</p>"
        )
    else:
        access_form = "<p>No hay aplicaciones habilitadas para asignar.</p>"

    full_name = escape(
        f"{detail['name']} {detail['surname']}".strip()
    )
    email = escape(detail["email"])
    state = "Bloqueado" if detail["is_blocked"] else "Activo"

    script = """
    <script>
      const form = document.querySelector("#access-form");

      if (form) {
        form.addEventListener("submit", async (event) => {
          event.preventDefault();

          const result = document.querySelector("#access-result");
          const button = form.querySelector('button[type="submit"]');
          const fields = new FormData(form);

          result.textContent = "Guardando…";
          button.disabled = true;

          try {
            const response = await fetch(
              `/api/v1/admin/users/${form.dataset.userId}/application-access`,
              {
                method: "POST",
                credentials: "same-origin",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  application_code: fields.get("application_code"),
                  role: fields.get("role"),
                  status: fields.get("status"),
                  reason: fields.get("reason") || null,
                }),
              },
            );

            if (!response.ok) {
              const error = await response.json();
              result.textContent =
                typeof error.detail === "string"
                  ? error.detail
                  : `No se pudo guardar: HTTP ${response.status}`;
              return;
            }

            window.location.reload();
          } catch {
            result.textContent = "No se pudo conectar con AMH.";
          } finally {
            button.disabled = false;
          }
        });
      }
    </script>
    """

    # El ID es un UUID validado por FastAPI.
    access_form = access_form.replace(
        '<form id="access-form">',
        f'<form id="access-form" data-user-id="{user_id}">',
    )

    access_form += (
        "<section>"
        "<h2>Tarjeta NFC</h2>"
        "<p>Selecciona este usuario y acerca su tarjeta al ACR122U.</p>"
        f'<button id="assign-card" type="button" data-user-id="{user_id}">'
        "Leer y asignar tarjeta"
        "</button>"
        '<p id="card-result" role="status"></p>'
        "</section>"
    )

    script += """
    <script>
      const cardButton = document.querySelector("#assign-card");
      const cardResult = document.querySelector("#card-result");

      cardButton.addEventListener("click", async () => {
        cardButton.disabled = true;
        cardResult.textContent = "Acerca la tarjeta al lector…";

        try {
          const deadline = Date.now() + 30000;

          while (Date.now() < deadline) {
            const reading = await fetch(
              "http://127.0.0.1:8766/enrollment/read",
              {
                method: "POST",
                credentials: "include",
                cache: "no-store",
              },
            );

            if (reading.status === 204) {
              await new Promise(resolve => setTimeout(resolve, 300));
              continue;
            }

            const data = await reading.json();

            if (!reading.ok) {
              throw new Error(
                typeof data.detail === "string"
                  ? data.detail
                  : `Error del lector: HTTP ${reading.status}`,
              );
            }

            if (data.status === "remove_card") {
              cardResult.textContent =
                "Retira la tarjeta anterior y vuelve a acercarla.";
              await new Promise(resolve => setTimeout(resolve, 300));
              continue;
            }

            if (typeof data.uid !== "string") {
              throw new Error("El lector no devolvió un UID válido.");
            }

            cardResult.textContent = "Asignando tarjeta…";

            const assignment = await fetch(
              `/api/v1/admin/users/${cardButton.dataset.userId}/cards`,
              {
                method: "POST",
                credentials: "same-origin",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ raw_uid: data.uid }),
              },
            );

            if (!assignment.ok) {
              const error = await assignment.json();
              throw new Error(
                typeof error.detail === "string"
                  ? error.detail
                  : `No se pudo asignar: HTTP ${assignment.status}`,
              );
            }

            cardResult.textContent = "Tarjeta asignada correctamente.";
            return;
          }

          cardResult.textContent =
            "No se detectó ninguna tarjeta en 30 segundos.";
        } catch (error) {
          cardResult.textContent =
            error instanceof Error
              ? error.message
              : "No se pudo leer o asignar la tarjeta.";
        } finally {
          cardButton.disabled = false;
        }
      });
    </script>
    """

    return HTMLResponse(
        "<!doctype html>"
        '<html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"{UI_STYLE}"
        "<title>Usuario · AMH</title></head><body><main>"
        '<p><a href="/admin/users">← Usuarios</a></p>'
        f"<h1>{full_name}</h1>"
        f"<p>Email principal: {email}</p>"
        f"<p>Estado: {state}</p>"
        "<h2>Acceso a aplicaciones</h2>"
        f"{grant_table}"
        f"{access_form}"
        f"{script}"
        "</main></body></html>",
        headers={"Cache-Control": "no-store"},
    )
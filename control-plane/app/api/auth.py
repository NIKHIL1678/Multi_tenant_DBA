"""Sign-up, sign-in, token refresh and sign-out.

The access token (JWT) is returned in the body; the dashboard keeps it in memory only.
The refresh token is set as an httpOnly cookie that JavaScript cannot read.
"""

from typing import Annotated

from fastapi import APIRouter, Cookie, Request, Response, status
from fastapi.responses import JSONResponse

from app.api.errors import conflict, error_response, unauthenticated
from app.auth import service
from app.auth.current_user import DbSession
from app.auth.security import create_access_token
from app.core.config import get_settings
from app.models import User
from app.schemas.auth import LoginIn, SignupIn, TokenOut

router = APIRouter(prefix="/v1/auth", tags=["auth"])

REFRESH_COOKIE = "zdba_refresh"
_COOKIE_PATH = "/v1/auth"


def _client(request: Request) -> service.ClientInfo:
    return service.ClientInfo(
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )


def _set_refresh_cookie(response: Response, raw: str) -> None:
    s = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        raw,
        max_age=s.refresh_token_days * 24 * 3600,
        path=_COOKIE_PATH,
        httponly=True,
        secure=s.cookie_secure,
        samesite="lax",
    )


def _clear_refresh_cookie(response: Response) -> None:
    s = get_settings()
    response.delete_cookie(
        REFRESH_COOKIE, path=_COOKIE_PATH, httponly=True, secure=s.cookie_secure, samesite="lax"
    )


async def _issue(session: DbSession, user: User, request: Request, response: Response) -> TokenOut:
    raw = await service.start_session(session, user, _client(request))
    await session.commit()
    _set_refresh_cookie(response, raw)
    token, expires_in = create_access_token(user.id)
    return TokenOut(access_token=token, expires_in=expires_in)


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(
    body: SignupIn, session: DbSession, request: Request, response: Response
) -> TokenOut:
    try:
        user = await service.sign_up(
            session, email=str(body.email), password=body.password, full_name=body.full_name
        )
    except service.EmailTakenError:
        raise conflict("An account with this email already exists.") from None
    return await _issue(session, user, request, response)


@router.post("/login")
async def login(
    body: LoginIn, session: DbSession, request: Request, response: Response
) -> TokenOut:
    try:
        user = await service.authenticate(session, email=body.email.strip(), password=body.password)
    except service.InvalidCredentialsError:
        raise unauthenticated("Wrong email or password.") from None
    return await _issue(session, user, request, response)


@router.post("/refresh", response_model=TokenOut)
async def refresh(
    session: DbSession,
    request: Request,
    response: Response,
    zdba_refresh: Annotated[str | None, Cookie()] = None,
) -> TokenOut | JSONResponse:
    if zdba_refresh:
        try:
            user, new_raw = await service.rotate_session(session, zdba_refresh, _client(request))
        except service.InvalidRefreshError:
            await session.commit()  # keep any reuse-detection revocations
        else:
            await session.commit()
            _set_refresh_cookie(response, new_raw)
            token, expires_in = create_access_token(user.id)
            return TokenOut(access_token=token, expires_in=expires_in)
    failed = error_response(401, "unauthenticated", "Session expired. Sign in again.")
    _clear_refresh_cookie(failed)
    return failed


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    session: DbSession,
    response: Response,
    zdba_refresh: Annotated[str | None, Cookie()] = None,
) -> None:
    if zdba_refresh:
        await service.end_session(session, zdba_refresh)
        await session.commit()
    _clear_refresh_cookie(response)

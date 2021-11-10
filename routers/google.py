from fastapi import FastAPI, exceptions, APIRouter, status, Depends
from fastapi.responses import JSONResponse
from fastapi_jwt_auth import AuthJWT
from google.auth.transport import requests
from google.oauth2.id_token import verify_oauth2_token
from ..utils import request
from ..settings import Settings
from ..models.user import User
from urllib.parse import urlparse, parse_qs
from pydantic import BaseModel
from typing import Optional
import datetime

settings = Settings()
router = APIRouter()


class DevLoginRequest(BaseModel):
    id_token: Optional[str]
    access_token: Optional[str]


class LoginRequest(BaseModel):
    id_token: str
    access_token: str


url = settings.GOOGLE_URL
url = url.replace("google#", "google?")


@router.post('/login')
async def google_login(req: LoginRequest if settings.APP_ENV != 'dev' else DevLoginRequest,
                       Authorize: AuthJWT = Depends()):
    """
    Login API
    """
    if settings.APP_ENV == 'dev':
        data = parse_qs(urlparse(url).query)
        google_id_token = data['id_token'][0]
        google_access_token = data['access_token'][0]
    else:
        google_id_token = req.id_token
        google_access_token = req.access_token

    try:
        auth_info = verify_oauth2_token(google_id_token, requests.Request())
    except Exception as ve:
        return JSONResponse(status_code=status.HTTP_408_REQUEST_TIMEOUT, content={'error': 'timeout'})

    user = await User.filter(email=auth_info['email']).first()
    if not user:
        profile = await request(f'https://www.googleapis.com/oauth2/v1/userinfo?access_token={google_access_token}')
        if not profile.get('verified_email'):
            raise exceptions.RequestValidationError({'message': 'email not verified'})
        user = User(
            provider='google',
            nickname=profile['family_name'] + profile['given_name'],
            email=profile['email'],
            verified=True,
            avatar=profile['picture']
        )
        await user.save()

    sign_data = {
        'id': user.id,
        'email': user.email,
        'onboarded': user.onboarded,
        'avatar': user.avatar,
        'username': user.username
    }

    # Create Tokens
    access_token = Authorize.create_access_token(subject=user.email)
    refresh_token = Authorize.create_refresh_token(subject=user.email)

    # Set Cookies
    Authorize.set_access_cookies(access_token)
    Authorize.set_refresh_cookies(refresh_token)

    return {
        'access_token': access_token,
        'refresh_token': refresh_token
    }


@router.post('/refresh')
async def refresh(Authorize: AuthJWT = Depends()):
    Authorize.jwt_refresh_token_required()

    signed_user = Authorize.get_jwt_subject()
    new_access_token = Authorize.create_access_token(subject=signed_user)
    Authorize.set_access_cookies(new_access_token)

    await User.filter(email=signed_user).update(last_logged_in=datetime.datetime.now())
    return {'access_token': new_access_token}


@router.delete('/logout')
def logout(Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    Authorize.unset_jwt_cookies()
    return {"msg": "success"}


@router.post('/user')
async def get_user(Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    signed_user = Authorize.get_jwt_subject()
    current_user = await User.filter(email=signed_user).first()
    return {
        "user": current_user
    }

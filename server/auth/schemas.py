from pydantic import BaseModel


class AuthRequest(BaseModel):
    username: str = ""
    password: str = ""
    clientToken: str = ""
    requestUser: bool = False


class RegisterRequest(BaseModel):
    username: str = ""
    password: str = ""
    email: str = ""


class TokenRequest(BaseModel):
    accessToken: str = ""
    clientToken: str = ""


class RefreshRequest(BaseModel):
    accessToken: str = ""
    clientToken: str = ""
    requestUser: bool = False


class JoinRequest(BaseModel):
    accessToken: str = ""
    selectedProfile: str = ""
    serverId: str = ""


class SignoutRequest(BaseModel):
    username: str = ""
    password: str = ""


class ProfileResponse(BaseModel):
    id: str
    name: str


class AuthenticateResponse(BaseModel):
    accessToken: str
    clientToken: str
    availableProfiles: list[ProfileResponse] = []
    selectedProfile: ProfileResponse | None = None
    user: dict | None = None


class ErrorResponse(BaseModel):
    error: str
    errorMessage: str

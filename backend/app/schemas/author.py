from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr


class AuthorCreate(BaseModel):
    email: EmailStr
    password: str
    name: str


class AuthorLogin(BaseModel):
    email: EmailStr
    password: str


class AuthorResponse(BaseModel):
    id: UUID
    email: str
    name: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AuthorLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    author: AuthorResponse

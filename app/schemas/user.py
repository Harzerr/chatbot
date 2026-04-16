from typing import Optional

from pydantic import BaseModel


class UserBase(BaseModel):
    username: str
    tenant_id: str
    full_name: str
    email: str
    phone: str
    target_role: str
    years_of_experience: int
    bio: Optional[str] = None


class UserCreate(UserBase):
    password: str


class UserUpdate(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    target_role: Optional[str] = None
    years_of_experience: Optional[int] = None
    bio: Optional[str] = None


class ResumeUploadResponse(BaseModel):
    message: str
    file_name: str
    resume_uploaded_at: str
    extracted_preview: str


class UserInDBBase(UserBase):
    id: int
    resume_file_name: Optional[str] = None
    resume_content_type: Optional[str] = None
    resume_uploaded_at: Optional[str] = None
    has_resume: bool = False
    resume_excerpt: Optional[str] = None

    class Config:
        from_attributes = True


class User(UserInDBBase):
    pass


class UserInDB(UserInDBBase):
    password: str # Hashed

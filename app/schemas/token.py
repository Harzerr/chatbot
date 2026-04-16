from typing import Optional

from pydantic import BaseModel, Field


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenPayload(BaseModel):
    sub: Optional[str] = None
    exp: Optional[int] = None

class LivekitToken(BaseModel):
    token: str
    room_name: str
    livekit_url: str


class VoiceInterviewTokenRequest(BaseModel):
    chat_id: Optional[str] = Field(default=None, description="Interview chat ID to continue")
    interview_role: Optional[str] = Field(default=None, description="Interview role")
    interview_level: Optional[str] = Field(default=None, description="Interview level")
    interview_type: Optional[str] = Field(default=None, description="Interview round type")
    target_company: Optional[str] = Field(default=None, description="Target company")
    jd_content: Optional[str] = Field(default=None, description="Job description content")

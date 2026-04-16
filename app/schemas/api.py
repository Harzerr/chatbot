from typing import Optional

from pydantic import BaseModel, Field

class LLMRequest(BaseModel):
    user_message: str = Field(description="Chat message")
    chat_id: str = Field(description="Chat ID")
    skill_name: Optional[str] = Field(default=None, description="Registered skill name to run")
    interview_role: Optional[str] = Field(default=None, description="Interview role")
    interview_level: Optional[str] = Field(default=None, description="Interview level")
    interview_type: Optional[str] = Field(default=None, description="Interview type")
    target_company: Optional[str] = Field(default=None, description="Target company")
    jd_content: Optional[str] = Field(default=None, description="Job description content")
    resume_content: Optional[str] = Field(default=None, description="Resume content or summary")


class CodeRunRequest(BaseModel):
    language: str = Field(description="Programming language key, e.g. python/cpp/java")
    source_code: str = Field(description="Source code to run")
    stdin: str = Field(default="", description="Custom standard input")
    expected_output: Optional[str] = Field(default=None, description="Expected output for simple pass/fail matching")


class CodeRunResponse(BaseModel):
    status: str = Field(description="Judge status description")
    stdout: str = Field(default="", description="Program stdout")
    stderr: str = Field(default="", description="Program stderr")
    compile_output: str = Field(default="", description="Compiler output")
    message: str = Field(default="", description="Judge message")
    time: Optional[str] = Field(default=None, description="Execution time returned by Judge0")
    memory: Optional[int] = Field(default=None, description="Memory usage returned by Judge0")
    token: Optional[str] = Field(default=None, description="Judge0 submission token")
    passed: Optional[bool] = Field(default=None, description="Whether stdout matches expected_output")

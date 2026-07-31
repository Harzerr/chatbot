from datetime import datetime
import json
from pathlib import Path
import shutil
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.api.deps import get_current_user, get_user_service
from app.models.user import User as DBUser
from app.schemas.user import User, UserUpdate, ResumeUploadResponse
from app.services.resume_parser import ResumeParserService, SUPPORTED_RESUME_TYPES
from app.services.user import UserService

router = APIRouter()
resume_parser = ResumeParserService()
RESUME_UPLOAD_DIR = Path(__file__).resolve().parents[3] / "uploads" / "resumes"
AVATAR_UPLOAD_DIR = Path(__file__).resolve().parents[3] / "uploads" / "avatars"
AVATAR_CONTENT_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}
MAX_AVATAR_BYTES = 5 * 1024 * 1024


def _avatar_url(user: DBUser) -> str | None:
    if not user.avatar_file_name:
        return None
    version = user.avatar_updated_at or "1"
    return f"/media/avatars/{user.avatar_file_name}?v={version}"


def _education_records(user: DBUser) -> list[dict]:
    try:
        records = json.loads(user.education_json or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return records if isinstance(records, list) else []


def _remove_avatar_path(path: str | None) -> None:
    if not path:
        return
    candidate = Path(path).resolve()
    avatar_root = AVATAR_UPLOAD_DIR.resolve()
    if candidate.parent == avatar_root:
        candidate.unlink(missing_ok=True)


def _remove_avatar_file(user: DBUser) -> None:
    _remove_avatar_path(user.avatar_file_path)


def build_user_response(user: DBUser) -> User:
    resume_text = (user.resume_text or "").strip()
    return User(
        id=user.id,
        username=user.username,
        tenant_id=user.tenant_id,
        full_name=user.full_name,
        email=user.email,
        phone=user.phone,
        target_role=user.target_role,
        years_of_experience=user.years_of_experience,
        bio=user.bio,
        resume_file_name=user.resume_file_name,
        resume_content_type=user.resume_content_type,
        resume_uploaded_at=user.resume_uploaded_at,
        has_resume=bool(resume_text),
        resume_excerpt=resume_text[:800] if resume_text else None,
        avatar_url=_avatar_url(user),
        avatar_updated_at=user.avatar_updated_at,
        education=_education_records(user),
    )


@router.get("/me", response_model=User)
async def read_users_me(
    current_user: Annotated[DBUser, Depends(get_current_user)],
) -> User:
    return build_user_response(current_user)


@router.put("/me", response_model=User)
async def update_user_me(
    *,
    user_in: UserUpdate,
    current_user: Annotated[DBUser, Depends(get_current_user)],
    user_service: UserService = Depends(get_user_service)
) -> User:
    if user_in.username and user_in.username != current_user.username:
        if await user_service.username_exists_for_other_user(user_in.username, current_user.id):
            raise HTTPException(status_code=400, detail="Username already registered")

    update_data = user_in.model_dump(exclude_unset=True)
    education = update_data.pop("education", None)
    if education is not None:
        update_data["education_json"] = json.dumps(education, ensure_ascii=False)
    user = await user_service.update(db_obj=current_user, obj_in=update_data)
    return build_user_response(user)


@router.post("/me/avatar", response_model=User)
async def upload_my_avatar(
    current_user: Annotated[DBUser, Depends(get_current_user)],
    file: UploadFile = File(...),
    user_service: UserService = Depends(get_user_service),
) -> User:
    content_type = (file.content_type or "").lower()
    extension = AVATAR_CONTENT_TYPES.get(content_type)
    if not extension:
        raise HTTPException(status_code=400, detail="Avatar must be a PNG, JPG, JPEG, or WEBP image")

    content = await file.read(MAX_AVATAR_BYTES + 1)
    if not content or len(content) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=400, detail="Avatar must be smaller than 5 MB")

    AVATAR_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stored_name = f"user_{current_user.id}_{uuid.uuid4().hex}{extension}"
    stored_path = AVATAR_UPLOAD_DIR / stored_name
    try:
        stored_path.write_bytes(content)
        old_avatar = current_user.avatar_file_path
        updated_at = datetime.utcnow().isoformat()
        user = await user_service.update(
            db_obj=current_user,
            obj_in={
                "avatar_file_name": stored_name,
                "avatar_file_path": str(stored_path),
                "avatar_content_type": content_type,
                "avatar_updated_at": updated_at,
            },
        )
        if old_avatar and old_avatar != str(stored_path):
            _remove_avatar_path(old_avatar)
        return build_user_response(user)
    except HTTPException:
        raise
    except Exception as exc:
        stored_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Failed to save avatar") from exc


@router.delete("/me/avatar", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_avatar(
    current_user: Annotated[DBUser, Depends(get_current_user)],
    user_service: UserService = Depends(get_user_service),
) -> None:
    _remove_avatar_file(current_user)
    await user_service.update(
        db_obj=current_user,
        obj_in={
            "avatar_file_name": None,
            "avatar_file_path": None,
            "avatar_content_type": None,
            "avatar_updated_at": None,
        },
    )


@router.post("/me/resume", response_model=ResumeUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_my_resume(
    current_user: Annotated[DBUser, Depends(get_current_user)],
    file: UploadFile = File(...),
    user_service: UserService = Depends(get_user_service),
) -> ResumeUploadResponse:
    content_type = (file.content_type or "").lower()
    if content_type not in SUPPORTED_RESUME_TYPES:
        raise HTTPException(status_code=400, detail="Resume must be a PDF, PNG, JPG, JPEG, or WEBP file")

    RESUME_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    extension = Path(file.filename or "resume").suffix or ".bin"
    stored_name = f"user_{current_user.id}_{uuid.uuid4().hex}{extension}"
    stored_path = RESUME_UPLOAD_DIR / stored_name

    try:
        with stored_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        extracted_text = await resume_parser.extract_text(str(stored_path), content_type)
        uploaded_at = datetime.utcnow().isoformat()
        await user_service.update(
            db_obj=current_user,
            obj_in={
                "resume_file_name": file.filename or stored_name,
                "resume_file_path": str(stored_path),
                "resume_content_type": content_type,
                "resume_uploaded_at": uploaded_at,
                "resume_text": extracted_text,
            },
        )
        return ResumeUploadResponse(
            message="Resume uploaded successfully",
            file_name=file.filename or stored_name,
            resume_uploaded_at=uploaded_at,
            extracted_preview=extracted_text[:1200],
        )
    except HTTPException:
        raise
    except Exception as exc:
        if stored_path.exists():
            stored_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Failed to process resume: {str(exc)}") from exc


@router.get("/{user_id}", response_model=User)
async def read_user_by_id(
    user_id: int,
    current_user: Annotated[DBUser, Depends(get_current_user)],
    user_service: UserService = Depends(get_user_service)
) -> User:
    user = await user_service.get(user_id=user_id)

    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == current_user.id:
        return build_user_response(user)

    raise HTTPException(status_code=403, detail="Not enough permissions")

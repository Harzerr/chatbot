from sqlalchemy import Column, Integer, String, Text

from app.db.base_class import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password = Column(String, nullable=False)
    tenant_id = Column(String, nullable=False)
    full_name = Column(String, nullable=False, default="")
    email = Column(String, nullable=False, default="")
    phone = Column(String, nullable=False, default="")
    target_role = Column(String, nullable=False, default="")
    years_of_experience = Column(Integer, nullable=False, default=0)
    bio = Column(Text, nullable=True)
    resume_file_name = Column(String, nullable=True)
    resume_file_path = Column(String, nullable=True)
    resume_content_type = Column(String, nullable=True)
    resume_uploaded_at = Column(String, nullable=True)
    resume_text = Column(Text, nullable=True)

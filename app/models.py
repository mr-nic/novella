# models_2026-05-10_11-00-00.py
from sqlalchemy import Column, Integer, String, Text, Float, DateTime
from sqlalchemy.sql import func
from .database import Base

class Book(Base):
    __tablename__ = "books"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    author = Column(String, nullable=False)
    isbn = Column(String)
    condition = Column(String)
    condition_notes = Column(Text)
    seller_note = Column(Text)
    seller_email = Column(String, default="")
    buyer_email = Column(String, default="")
    price = Column(Float, nullable=False)
    seller_net = Column(Float, default=0.0)
    cover_image = Column(String)
    estimated_postage = Column(Float, default=0.0)
    is_bundle = Column(String, default="false")
    bundle_titles = Column(Text, default="")
    status = Column(String, default="available")  # available / sold / posted
    tracking_reference = Column(String, default="")
    posted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

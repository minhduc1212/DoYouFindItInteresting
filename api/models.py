"""
SQLAlchemy ORM Models for the TIL application.
- Article: A piece of knowledge (from a video or article).
- Term: A technical word within an article, mapped to its definition.
"""

from sqlalchemy import Column, Integer, String, Text, ForeignKey, Enum
from sqlalchemy.orm import relationship
from .database import Base
import enum


class SourceType(str, enum.Enum):
    VIDEO = "Video"
    ARTICLE = "Article"


class Article(Base):
    __tablename__ = "articles"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    source_url = Column(String(500), nullable=True)
    source_type = Column(String(10), nullable=False, default=SourceType.ARTICLE)
    content = Column(Text, nullable=False)

    # One article → many terms
    terms = relationship("Term", back_populates="article", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Article id={self.id} title='{self.title}'>"


class Term(Base):
    __tablename__ = "terms"

    id = Column(Integer, primary_key=True, index=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False)
    term = Column(String(100), nullable=False)         # The word as it appears in content
    definition = Column(Text, nullable=False)          # Tooltip explanation

    # Many terms → one article
    article = relationship("Article", back_populates="terms")

    def __repr__(self):
        return f"<Term term='{self.term}' article_id={self.article_id}>"
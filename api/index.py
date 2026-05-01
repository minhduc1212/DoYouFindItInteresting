"""
Today I Learned (TIL) - FastAPI Backend
Serves random knowledge snippets with highlighted technical terms.
"""

from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
import random
import re
import os

from .database import SessionLocal, engine, Base
from .models import Article, Term
from .schemas import KnowledgeResponse, ContentSegment
from .seed import seed_database

# ── App Setup ──────────────────────────────────────────────────────────────────
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Do You Find It Interesting API", version="1.0.0")

# ── Dependency ─────────────────────────────────────────────────────────────────
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ── Startup: seed DB if empty ──────────────────────────────────────────────────
@app.on_event("startup")
def startup_event():
    db = SessionLocal()
    try:
        if db.query(Article).count() == 0:
            seed_database(db)
            print("✅ Database seeded with mock data.")
    finally:
        db.close()

# ── Helper: parse content into segments ───────────────────────────────────────
def parse_content_into_segments(content: str, terms: list[Term]) -> list[ContentSegment]:
    """
    Splits article content into plain text and term segments.
    Terms are matched case-insensitively using regex word boundaries.
    Returns an ordered list of segments for the frontend to render.
    """
    if not terms:
        return [ContentSegment(type="text", text=content)]

    # Build a regex pattern that matches any term (longest first to avoid partial matches)
    sorted_terms = sorted(terms, key=lambda t: len(t.term), reverse=True)
    term_map = {t.term.lower(): t for t in sorted_terms}
    pattern = r'\b(' + '|'.join(re.escape(t.term) for t in sorted_terms) + r')\b'

    segments: list[ContentSegment] = []
    last_end = 0

    for match in re.finditer(pattern, content, flags=re.IGNORECASE):
        start, end = match.start(), match.end()
        matched_word = match.group(0)
        term_obj = term_map.get(matched_word.lower())

        # Add preceding plain text
        if start > last_end:
            segments.append(ContentSegment(type="text", text=content[last_end:start]))

        # Add the term segment
        if term_obj:
            segments.append(ContentSegment(
                type="term",
                text=matched_word,
                term_id=term_obj.id,
                definition=term_obj.definition
            ))

        last_end = end

    # Remaining text after the last match
    if last_end < len(content):
        segments.append(ContentSegment(type="text", text=content[last_end:]))

    return segments

# ── API Endpoints ──────────────────────────────────────────────────────────────
@app.get("/api/random-knowledge", response_model=KnowledgeResponse)
def get_random_knowledge(db: Session = Depends(get_db)):
    """
    Returns a random article with its content pre-parsed into segments.
    Each segment is either plain text or a highlighted technical term with its definition.
    """
    articles = db.query(Article).all()
    if not articles:
        raise HTTPException(status_code=404, detail="No articles found in the database.")

    article = random.choice(articles)
    terms = db.query(Term).filter(Term.article_id == article.id).all()
    segments = parse_content_into_segments(article.content, terms)

    return KnowledgeResponse(
        id=article.id,
        title=article.title,
        source_url=article.source_url,
        source_type=article.source_type,
        segments=segments,
        term_count=len(terms),
    )

@app.get("/api/articles/count")
def get_article_count(db: Session = Depends(get_db)):
    """Returns the total number of articles in the database."""
    return {"count": db.query(Article).count()}

# ── Static Frontend Serving ────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
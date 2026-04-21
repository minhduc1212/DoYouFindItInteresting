# Do You Find It Interesting? — Full-Stack App

A minimalist editorial knowledge feed. Click **Randomize** to surface a random article summary. Technical terms are highlighted — hover or click them to reveal Glassmorphism tooltips with definitions.

---

## Project Structure

```
til-app/
├── backend/
│   ├── main.py          # FastAPI app, API endpoints, static file serving
│   ├── database.py      # SQLAlchemy engine + session
│   ├── models.py        # ORM models (Article, Term)
│   ├── schemas.py       # Pydantic response schemas
│   └── seed.py          # Mock data seeder (5 articles, 30+ terms)
├── frontend/
│   ├── index.html       # Single-page HTML
│   ├── style.css        # Editorial design + glassmorphism CSS
│   └── app.js           # Fetch logic + tooltip system (vanilla JS)
├── til_database.db      # SQLite file (auto-created on first run)
├── requirements.txt
└── README.md
```

---

## Quick Start

### 1. Install dependencies

```bash
cd til-app
pip install -r requirements.txt
```

### 2. Start the server

```bash
cd backend
uvicorn index:app --reload --port 8000
```

The first startup auto-seeds the database with 5 articles and 30+ technical terms.

### 3. Open the app

Visit → **http://localhost:8000**

---

## API Endpoints

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/` | Serves the frontend |
| GET | `/api/random-knowledge` | Returns a random article with segmented content |
| GET | `/api/articles/count` | Returns total article count |
| GET | `/docs` | Auto-generated Swagger UI |

### Example response — `/api/random-knowledge`

```json
{
  "id": 2,
  "title": "Understanding Docker: Containers vs. Virtual Machines",
  "source_url": "https://www.docker.com/resources/what-container/",
  "source_type": "Article",
  "term_count": 7,
  "segments": [
    { "type": "text", "text": "A " },
    {
      "type": "term",
      "text": "container",
      "term_id": 8,
      "definition": "A standard unit of software that packages code and all its dependencies..."
    },
    { "type": "text", "text": " is a lightweight, portable unit..." }
  ]
}
```

---

## Adding New Articles

Edit `backend/seed.py` and add an entry to the `MOCK_DATA` list. Delete `til_database.db` to re-seed, then restart the server.

---

## Tech Stack

- **Backend:** Python 3.11+, FastAPI, SQLAlchemy, SQLite
- **Frontend:** HTML5, CSS3 (Custom Properties, backdrop-filter), Vanilla JS
- **Fonts:** Playfair Display, Lora, DM Sans (Google Fonts)
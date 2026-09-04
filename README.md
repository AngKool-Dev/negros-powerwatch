# Negros PowerWatch

Real-time electricity outage detection and alerting platform for Negros Oriental, Philippines.

## Architecture

- **Backend**: FastAPI + SQLAlchemy + APScheduler (deployed on Railway or Render)
- **Frontend**: Static HTML/CSS/JS PWA (deployed on Cloudflare Pages)
- **Database**: SQLite (Railway/Render persistent volume) or PostgreSQL (Render managed database)
- **Live Updates**: Server-Sent Events (SSE)

## Local Development

1. Create virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   # or
   venv\Scripts\activate  # Windows
   ```

2. Install dependencies:
   ```bash
   pip install -e ".[dev]"
   ```

3. Configure environment:
   ```bash
   cp .env.example .env
   # Edit .env and add your FACEBOOK_ACCESS_TOKEN
   ```

4. Run server:
   ```bash
   uvicorn app.main:app --reload
   ```

5. Open http://localhost:8000

## Deployment

### Backend (Railway)

1. Push this repo to GitHub
2. Go to [Railway.app](https://railway.app) → New Project → Deploy from GitHub
3. Select your repo
4. Railway auto-detects `railway.toml` and deploys
5. Set environment variables in Railway dashboard:
   - `FACEBOOK_ACCESS_TOKEN` - your Facebook page access token
   - `FACEBOOK_SOURCES` - JSON array of sources to monitor
   - `FACEBOOK_ENABLED` - `true` or `false`

### Backend (Render)

1. Push this repo to GitHub
2. Go to [Render.com](https://render.com) → New → Web Service
3. Connect your repo
4. Render auto-detects `render.yaml` and deploys
5. Set environment variables in Render dashboard

### Frontend (Cloudflare Pages)

1. Push this repo to GitHub
2. Go to [Cloudflare Pages](https://pages.cloudflare.com) → Create a project
3. Connect your GitHub repo
4. Configure build settings:
   - **Build command**: `bash build_frontend.sh`
   - **Build output directory**: `public`
   - **Environment variables**: None required for static frontend
5. Deploy

### Connecting Frontend to Backend

After deploying both:

1. Update `public/config.js` on Cloudflare Pages (or set as Pages environment variable):
   ```javascript
   window.POWERWATCH_CONFIG.API_BASE = 'https://your-backend-url.com/api/v1';
   ```

2. Or set a Pages environment variable `API_BASE_URL` and modify the build script to inject it.

## API Endpoints

- `GET /api/v1/status` - System status and active outages
- `GET /api/v1/outages` - List active outages
- `POST /api/v1/reports` - Submit community report
- `GET /api/v1/events` - SSE live updates
- `POST /api/v1/scan` - Trigger Facebook scan manually

## Facebook Configuration

The system monitors these pages by default:
- NORECO II (`NORECO2Official`)
- NGCP (`NGCPph`)

Get a Page Access Token from [Meta for Developers](https://developers.facebook.com/) with permissions:
- `pages_read_engagement`
- `pages_read_user_content`

## Testing

```bash
pytest tests/ -v
```

## Tech Stack

- FastAPI, SQLAlchemy 2.0, Pydantic Settings
- APScheduler (1-minute Facebook polling)
- Leaflet.js (map), vanilla JS PWA
- SSE for real-time updates

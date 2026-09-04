from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi import Request
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler

from app.api import router as api_router
from app.db import Base, engine, SessionLocal
from app.models import GeographicArea, Source, SourceType, SourceStatus
from app.services import ReportService

Base.metadata.create_all(bind=engine)

scheduler = BackgroundScheduler()


def run_scan_job():
    db = SessionLocal()
    try:
        service = ReportService(db)
        import asyncio
        asyncio.get_event_loop().run_until_complete(service.scan_sources())
    except Exception:
        pass
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = SessionLocal()
    try:
        if db.query(GeographicArea).count() == 0:
            areas = [
                ("Negros Oriental", "province", None, 9.8, 123.5),
                ("Siaton", "municipality", "Negros Oriental", 9.65, 123.15),
                ("Zamboanguita", "municipality", "Negros Oriental", 9.1, 123.2),
                ("Bayawan", "city", "Negros Oriental", 9.35, 122.8),
                ("Dumaguete", "city", "Negros Oriental", 9.3, 123.3),
                ("Bacong", "municipality", "Negros Oriental", 9.25, 123.3),
                ("Valencia", "municipality", "Negros Oriental", 9.25, 123.55),
                ("Dauin", "municipality", "Negros Oriental", 9.2, 123.35),
                ("Santa Catalina", "municipality", "Negros Oriental", 9.25, 123.1),
                ("Ayungon", "municipality", "Negros Oriental", 9.4, 123.2),
                ("Mabinay", "municipality", "Negros Oriental", 9.7, 123.1),
                ("Bindoy", "municipality", "Negros Oriental", 9.75, 123.1),
                ("Manjuyod", "municipality", "Negros Oriental", 9.65, 123.15),
                ("Pamplona", "municipality", "Negros Oriental", 9.55, 123.1),
                ("Tanjay", "city", "Negros Oriental", 9.5, 123.15),
            ]
            for name, area_type, parent_name, lat, lon in areas:
                parent = None
                if parent_name:
                    parent = db.query(GeographicArea).filter(GeographicArea.name == parent_name).first()
                area = GeographicArea(
                    name=name,
                    area_type=area_type,
                    parent_id=parent.id if parent else None,
                    latitude=lat,
                    longitude=lon,
                )
                db.add(area)
        if db.query(Source).count() == 0:
            sources = [
                ("community", SourceType.COMMUNITY, 0.7, SourceStatus.UNKNOWN),
                ("noreco_ii", SourceType.NORECO_II, 0.9, SourceStatus.UNKNOWN),
                ("ngcp", SourceType.NGCP, 0.9, SourceStatus.UNKNOWN),
            ]
            for name, source_type, reliability, status in sources:
                source = Source(name=name, source_type=source_type, reliability=reliability, status=status)
                db.add(source)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    scheduler.add_job(run_scan_job, "interval", minutes=1, id="facebook_scan", replace_existing=True)
    scheduler.start()
    yield

    scheduler.shutdown(wait=False)


app = FastAPI(
    title="Negros PowerWatch",
    description="Real-time electricity outage detection and alerting for Negros Oriental",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(api_router, prefix="/api/v1")
app.mount("/static", StaticFiles(directory="static"), name="static")


def read_template(name: str) -> str:
    import os
    path = os.path.join("templates", name)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


@app.get("/", response_class=HTMLResponse)
async def homepage(request: Request):
    return read_template("index.html")


@app.get("/map", response_class=HTMLResponse)
async def map_page(request: Request):
    return read_template("map.html")


@app.get("/outages", response_class=HTMLResponse)
async def outages_page(request: Request):
    return read_template("outages.html")


@app.get("/about", response_class=HTMLResponse)
async def about_page(request: Request):
    return read_template("about.html")


@app.get("/report", response_class=HTMLResponse)
async def report_page(request: Request):
    return read_template("report.html")


@app.get("/outages/{outage_id}", response_class=HTMLResponse)
async def outage_detail_page(request: Request, outage_id: str):
    return read_template("outage_detail.html")


@app.get("/sw.js")
async def service_worker():
    return FileResponse("static/sw.js", media_type="application/javascript")

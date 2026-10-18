from __future__ import annotations

import asyncio
import hmac
import ipaddress
import logging
import subprocess
import threading
import urllib.error
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .db import Database
from .decoder import decode_mode_s
from .dialogue import fixed_pilot_answer, ollama_pilot_answer, recognize_question
from .enrichment import EnrichmentService
from .live_store import LiveStore
from .models import HardwareControlEvent, HardwareSelection, IngestBatch, PilotQuestion
from .radio import (
    begin_radio_session,
    cancel_radio_session,
    finish_radio_session,
    has_confirmed_route,
    is_radio_playing,
    play_radio_text,
    radio_intro_text,
    radio_route_text,
)
from .realtime import LiveHub


settings = Settings.from_env()
logger = logging.getLogger(__name__)
database = Database(
    settings.database_path,
    retention_hours=settings.retention_hours,
    active_seconds=settings.active_seconds,
    store_raw_messages=settings.store_raw_messages,
    store_positions=settings.store_positions,
    store_ingest_batches=settings.store_raw_messages,
)
live_store = LiveStore(active_seconds=settings.active_seconds)
enricher = EnrichmentService(
    database,
    enabled=settings.enrichment_enabled or settings.enrichment_on_demand,
    base_url=settings.enrichment_base_url,
    success_hours=settings.enrichment_success_hours,
    retry_hours=settings.enrichment_retry_hours,
    timeout_seconds=settings.enrichment_timeout_seconds,
)
static_dir = Path(__file__).parent / "static"


def live_snapshot() -> dict:
    live_data = live_store.snapshot() if settings.realtime_first else database.live_aircraft()
    if settings.enrichment_enabled:
        enricher.schedule_contacts(
            (aircraft["icao"], aircraft.get("callsign"))
            for aircraft in live_data["aircraft"]
        )
    return live_data


def realtime_snapshot() -> dict:
    live_data = live_snapshot()
    return {
        "type": "snapshot",
        "live": live_data,
        "stats": live_store.stats() if settings.realtime_first else database.stats(),
    }


live_hub = LiveHub(realtime_snapshot, heartbeat_seconds=5.0)
hardware_selected_icao: str | None = None


def hardware_dialogue_status() -> tuple[str | None, str, str]:
    active_aircraft = live_snapshot().get("aircraft", [])
    if not active_aircraft:
        return None, "No aircraft are currently available. Wait for an aircraft signal.", "no_aircraft"
    selected = hardware_selected_icao
    if not selected:
        return None, "Select an aircraft before speaking to the pilot.", "selection_required"
    if not any(str(item.get("icao", "")).upper() == selected for item in active_aircraft):
        return None, "The selected aircraft is no longer available. Select another aircraft.", "selection_required"
    return selected, "", "ready"


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.initialize()
    live_store.hydrate(database.latest_state())
    if settings.enrichment_enabled or settings.enrichment_on_demand:
        enricher.start(database.enrichment_candidates() if settings.enrichment_enabled else ())
    await live_hub.start()
    try:
        yield
    finally:
        await live_hub.stop()
        enricher.stop()


app = FastAPI(
    title="SkyTrace ADS-B",
    version="1.5.0",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)
app.mount("/assets", StaticFiles(directory=static_dir), name="assets")


@app.middleware("http")
async def api_headers(request: Request, call_next):
    if request.method == "POST":
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                too_large = int(content_length) > 8 * 1024 * 1024
            except ValueError:
                return JSONResponse({"detail": "invalid content length"}, status_code=400)
            if too_large:
                return JSONResponse({"detail": "request body too large"}, status_code=413)
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    return response


def require_ingest_key(authorization: str | None = Header(default=None)) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing API key")
    supplied = authorization.removeprefix("Bearer ")
    if not hmac.compare_digest(supplied, settings.ingest_api_key):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid API key")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.get("/healthz")
def health() -> dict:
    return {**database.health(), "version": app.version}


def close_kiosk_process() -> None:
    subprocess.run(["pkill", "-f", "^angelfish"], check=False)


def normalize_icao(icao: str) -> str:
    normalized = icao.upper()
    if len(normalized) != 6 or any(c not in "0123456789ABCDEF" for c in normalized):
        raise HTTPException(status_code=422, detail="invalid ICAO address")
    return normalized


def is_local_or_docker_request(request: Request) -> bool:
    if request.client is None:
        return False
    try:
        address = ipaddress.ip_address(request.client.host)
    except ValueError:
        return False
    return address.is_loopback or (
        isinstance(address, ipaddress.IPv4Address)
        and address in ipaddress.ip_network("172.16.0.0/12")
    )


@app.post("/api/v1/kiosk/close", include_in_schema=False)
def close_kiosk(request: Request, background_tasks: BackgroundTasks) -> dict:
    if not is_local_or_docker_request(request):
        raise HTTPException(status_code=403, detail="local kiosk only")
    background_tasks.add_task(close_kiosk_process)
    return {"closing": True}


@app.post("/api/v1/hardware/event", include_in_schema=False)
async def hardware_event(request: Request, event: HardwareControlEvent) -> dict:
    if not is_local_or_docker_request(request):
        raise HTTPException(status_code=403, detail="local hardware only")
    await live_hub.broadcast({"type": "hardware_control", **event.model_dump()})
    return {"accepted": True}


@app.post("/api/v1/hardware/selection", include_in_schema=False)
def hardware_selection(request: Request, selection: HardwareSelection) -> dict:
    if not is_local_or_docker_request(request):
        raise HTTPException(status_code=403, detail="local hardware only")
    global hardware_selected_icao
    hardware_selected_icao = selection.icao.upper()
    return {"selected": hardware_selected_icao}


@app.post("/api/v1/hardware/radio/stop", include_in_schema=False)
def hardware_stop_radio(request: Request) -> dict:
    if not is_local_or_docker_request(request):
        raise HTTPException(status_code=403, detail="local hardware only")
    stopped_icao = cancel_radio_session()
    if stopped_icao:
        global hardware_selected_icao
        hardware_selected_icao = stopped_icao
    selected_icao, message, reason = hardware_dialogue_status()
    return {
        "stopped": bool(stopped_icao),
        "icao": stopped_icao,
        "ready": bool(selected_icao),
        "selected": selected_icao,
        "message": message,
        "reason": reason,
    }


@app.get("/api/v1/hardware/dialogue/status", include_in_schema=False)
def hardware_dialogue_availability(request: Request) -> dict:
    if not is_local_or_docker_request(request):
        raise HTTPException(status_code=403, detail="local hardware only")
    selected_icao, message, reason = hardware_dialogue_status()
    return {
        "ready": bool(selected_icao),
        "selected": selected_icao,
        "message": message,
        "reason": reason,
    }


def play_pilot_dialogue(icao: str, aircraft: dict, answer: str) -> None:
    session, _ = begin_radio_session(icao)
    try:
        _play_radio_segment(aircraft, session, "dialogue", answer, True)
    finally:
        finish_radio_session(session)


async def broadcast_pilot_subtitles(question: str, answer: str, mode: str) -> None:
    await live_hub.broadcast(
        {
            "type": "hardware_control",
            "action": "dialogue_answer",
            "question": question,
            "answer": answer,
            "mode": mode,
        }
    )


@app.post("/api/v1/hardware/dialogue", include_in_schema=False)
def hardware_dialogue(
    request: Request,
    question: PilotQuestion,
    background_tasks: BackgroundTasks,
) -> dict:
    if not is_local_or_docker_request(request):
        raise HTTPException(status_code=403, detail="local hardware only")
    icao, unavailable_message, _ = hardware_dialogue_status()
    if not icao:
        raise HTTPException(status_code=409, detail=unavailable_message)
    aircraft = _radio_aircraft_payload(icao)
    if aircraft is None:
        raise HTTPException(status_code=404, detail="selected aircraft is no longer available")
    try:
        transcript = recognize_question(settings.dialogue_asr_url, question.audio_base64)
    except (OSError, urllib.error.URLError, ValueError) as exc:
        logger.warning("pilot ASR failed: %s", exc)
        transcript = ""
    if not transcript:
        answer = "I did not copy that. Please ask again."
        mode = "fixed"
    elif settings.dialogue_llm_enabled:
        try:
            answer = ollama_pilot_answer(
                settings.dialogue_ollama_url,
                settings.dialogue_ollama_model,
                transcript,
                aircraft,
            )
            mode = "llm"
        except (OSError, urllib.error.URLError, ValueError) as exc:
            logger.warning("pilot LLM failed, using fixed answer: %s", exc)
            answer = fixed_pilot_answer(transcript, aircraft)
            mode = "fixed-fallback"
    else:
        answer = fixed_pilot_answer(transcript, aircraft)
        mode = "fixed"
    background_tasks.add_task(broadcast_pilot_subtitles, transcript, answer, mode)
    background_tasks.add_task(play_pilot_dialogue, icao, aircraft, answer)
    return {
        "icao": icao,
        "question": transcript,
        "answer": answer,
        "mode": mode,
        "played": False,
        "queued": True,
    }


@app.get("/api/v1/hardware/status", include_in_schema=False)
def hardware_status(request: Request) -> dict:
    if not is_local_or_docker_request(request):
        raise HTTPException(status_code=403, detail="local hardware only")
    live_data = live_store.snapshot() if settings.realtime_first else database.live_aircraft()
    return {
        "signal_active": bool(live_data.get("aircraft")),
        "radio_playing": is_radio_playing(),
    }


@app.post("/api/v1/ingest", dependencies=[Depends(require_ingest_key)])
async def ingest(batch: IngestBatch) -> dict:
    live_result = live_store.ingest(batch) if settings.realtime_first else None
    result = await asyncio.to_thread(database.ingest, batch)
    if not result.get("duplicate"):
        if settings.enrichment_enabled:
            contacts = [(aircraft.icao, aircraft.callsign) for aircraft in batch.aircraft]
            contacts.extend(
                (message.icao, None) for message in batch.messages if message.icao
            )
            enricher.schedule_contacts(contacts)
        live_hub.notify()
    return live_result or result


@app.websocket("/ws/v1/live")
async def live_websocket(websocket: WebSocket) -> None:
    try:
        await live_hub.connect(websocket)
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await live_hub.disconnect(websocket)


@app.get("/api/v1/stats")
def stats() -> dict:
    return live_store.stats() if settings.realtime_first else database.stats()


@app.get("/api/v1/live")
def live() -> dict:
    return live_snapshot()


@app.get("/api/v1/aircraft")
def aircraft_list(
    search: str = Query(default="", max_length=64),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> dict:
    result = database.list_aircraft(search, page, page_size)
    enricher.schedule_contacts(
        (aircraft["icao"], aircraft.get("callsign"))
        for aircraft in result["items"]
    )
    return result


@app.get("/api/v1/aircraft/{icao}")
def aircraft_detail(
    icao: str,
    hours: int = Query(default=24, ge=1, le=24 * 365),
) -> dict:
    normalized = normalize_icao(icao)
    result = (
        live_store.aircraft_detail(normalized, hours)
        if settings.realtime_first
        else database.aircraft_detail(normalized, hours)
    )
    if result is None:
        raise HTTPException(status_code=404, detail="aircraft not found")
    return result


@app.get("/api/v1/aircraft/{icao}/enrichment")
def aircraft_enrichment(
    icao: str,
    callsign: str | None = Query(default=None, max_length=16),
) -> dict:
    normalized = normalize_icao(icao)
    cleaned_callsign = (callsign or "").strip().upper() or None
    if cleaned_callsign is None:
        detail = (
            live_store.aircraft_detail(normalized, 1)
            if settings.realtime_first
            else database.aircraft_detail(normalized, 1)
        )
        if detail:
            cleaned_callsign = detail["aircraft"].get("callsign")
    enrichment = database.aircraft_enrichment(normalized, cleaned_callsign)
    payload = {"icao": normalized, "callsign": cleaned_callsign}
    payload.update({key: value for key, value in enrichment.items() if value is not None})
    if settings.enrichment_enabled or settings.enrichment_on_demand:
        enricher.schedule_contacts(
            [(normalized, cleaned_callsign)]
        )
    return {"aircraft": payload}


def _radio_aircraft_payload(icao: str) -> dict | None:
    result = (
        live_store.aircraft_detail(icao, 1)
        if settings.realtime_first
        else database.aircraft_detail(icao, 1)
    )
    if result is None and settings.realtime_first:
        result = database.aircraft_detail(icao, 1)
    if result is None:
        return None
    aircraft = dict(result["aircraft"])
    if settings.enrichment_enabled or settings.enrichment_on_demand:
        enricher.schedule_contacts([(icao, aircraft.get("callsign"))])
    enrichment = database.aircraft_enrichment(icao, aircraft.get("callsign"))
    aircraft.update({key: value for key, value in enrichment.items() if value is not None})
    return aircraft


def _play_radio_segment(aircraft: dict, session, segment: str, text: str, chirp: bool) -> dict:
    result = play_radio_text(
        aircraft,
        text,
        session=session,
        segment=segment,
        tts_command=settings.radio_tts_command,
        voice_model=settings.radio_voice_model,
        voice_config=settings.radio_voice_config,
        audio_device=settings.radio_audio_device,
        tmp_dir=settings.radio_tmp_dir,
        chirp=chirp,
        tts_http_url=settings.radio_tts_http_url,
        tts_length_scale=settings.radio_tts_length_scale,
    )
    if result.get("played"):
        print(
            f"aircraft radio played icao={aircraft.get('icao')} segment={segment} voice={result.get('voice')}",
            flush=True,
        )
        logger.info(
            "aircraft radio played icao=%s segment=%s voice=%s",
            aircraft.get("icao"),
            segment,
            result.get("voice"),
        )
    else:
        print(
            f"aircraft radio skipped icao={aircraft.get('icao')} segment={segment} reason={result.get('reason')}",
            flush=True,
        )
        logger.warning(
            "aircraft radio skipped icao=%s segment=%s reason=%s",
            aircraft.get("icao"),
            segment,
            result.get("reason"),
        )
    return result


def _radio_sleep(session, seconds: float) -> bool:
    return not session.cancelled.wait(seconds)


def _play_radio_background(icao: str, aircraft: dict, session) -> None:
    try:
        intro_result = _play_radio_segment(
            aircraft,
            session,
            "intro",
            radio_intro_text(aircraft),
            True,
        )
        if session.cancelled.is_set() or not intro_result.get("played"):
            return

        route_aircraft = aircraft
        if not has_confirmed_route(route_aircraft):
            for delay in (0.3, 0.7, 1.2, 1.8, 2.5, 3.5):
                if not _radio_sleep(session, delay):
                    return
                refreshed = _radio_aircraft_payload(icao)
                if refreshed:
                    route_aircraft = refreshed
                if has_confirmed_route(route_aircraft):
                    break

        if not _radio_sleep(session, 0.18):
            return
        _play_radio_segment(
            route_aircraft,
            session,
            "route",
            radio_route_text(route_aircraft),
            False,
        )
    finally:
        finish_radio_session(session)


@app.post("/api/v1/aircraft/{icao}/radio")
def aircraft_radio(icao: str) -> dict:
    if not settings.radio_enabled:
        raise HTTPException(status_code=503, detail="radio playback disabled")
    normalized = normalize_icao(icao)
    global hardware_selected_icao
    hardware_selected_icao = normalized
    aircraft = _radio_aircraft_payload(normalized)
    if aircraft is None:
        raise HTTPException(status_code=404, detail="aircraft not found")
    session, created = begin_radio_session(normalized)
    if not created:
        return {
            "queued": False,
            "icao": normalized,
            "callsign": aircraft.get("callsign"),
            "reason": "already playing",
        }
    thread = threading.Thread(
        target=_play_radio_background,
        args=(normalized, aircraft, session),
        name=f"skytrace-radio-{normalized}",
        daemon=True,
    )
    thread.start()
    return {
        "queued": True,
        "icao": normalized,
        "callsign": aircraft.get("callsign"),
    }


@app.get("/api/v1/aircraft/{icao}/messages")
def aircraft_messages(
    icao: str,
    cursor: int | None = Query(default=None, ge=1),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    if settings.realtime_first and not settings.store_raw_messages:
        return {"items": [], "next_cursor": None}
    normalized = normalize_icao(icao)
    result = database.aircraft_messages(normalized, cursor, limit)
    for message in result["items"]:
        try:
            message["decoded"] = decode_mode_s(message["raw"])
        except ValueError:
            message["decoded"] = {
                "summary": "Message format could not be decoded",
                "fields": [],
                "notes": ["The stored raw value is not a valid 56-bit or 112-bit Mode S message."],
            }
    return result


@app.get("/api/v1/receivers")
def receivers() -> list[dict]:
    return database.receivers()

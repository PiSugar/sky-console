from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


Icao = Annotated[str, StringConstraints(pattern=r"^[0-9A-Fa-f]{6}$")]
ReceiverId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]{1,64}$")]


class ReceiverPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: ReceiverId
    name: str = Field(min_length=1, max_length=120)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    version: str | None = Field(default=None, max_length=64)


class AircraftState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    icao: Icao
    observed_at_ms: int = Field(ge=0)
    position_at_ms: int | None = Field(default=None, ge=0)
    callsign: str | None = Field(default=None, max_length=16)
    registration: str | None = Field(default=None, max_length=32)
    aircraft_type: str | None = Field(default=None, max_length=64)
    category: str | None = Field(default=None, max_length=16)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    altitude_baro: int | str | None = None
    altitude_geom: int | None = Field(default=None, ge=-2000, le=100000)
    ground_speed: float | None = Field(default=None, ge=0, le=2000)
    track: float | None = Field(default=None, ge=0, le=360)
    vertical_rate: int | None = Field(default=None, ge=-20000, le=20000)
    squawk: str | None = Field(default=None, pattern=r"^[0-7]{4}$")
    emergency: str | None = Field(default=None, max_length=32)
    signal: float | None = Field(default=None, ge=-200, le=100)
    messages: int | None = Field(default=None, ge=0)

    @field_validator("icao")
    @classmethod
    def uppercase_icao(cls, value: str) -> str:
        return value.upper()

    @field_validator("callsign")
    @classmethod
    def clean_callsign(cls, value: str | None) -> str | None:
        value = value.strip().upper() if value else None
        return value or None

    @field_validator("altitude_baro")
    @classmethod
    def normalize_altitude(cls, value: int | str | None) -> int | None:
        if value in (None, "ground"):
            return 0 if value == "ground" else None
        parsed = int(value)
        if not -2000 <= parsed <= 100000:
            raise ValueError("altitude_baro is outside the supported range")
        return parsed


class RawMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ts_ms: int = Field(ge=0)
    raw: str = Field(pattern=r"^[0-9A-Fa-f]{14}([0-9A-Fa-f]{14})?$")
    icao: Icao | None = None
    df: int = Field(ge=0, le=31)
    type_code: int | None = Field(default=None, ge=0, le=31)
    signal: float | None = Field(default=None, ge=-200, le=100)

    @field_validator("raw", "icao")
    @classmethod
    def uppercase_hex(cls, value: str | None) -> str | None:
        return value.upper() if value else value


class IngestBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: str = Field(min_length=12, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")
    emitted_at_ms: int = Field(ge=0)
    receiver: ReceiverPayload
    aircraft: list[AircraftState] = Field(default_factory=list, max_length=1000)
    messages: list[RawMessage] = Field(default_factory=list, max_length=5000)


class HardwareControlEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal[
        "pan",
        "zoom",
        "select_nearest",
        "toggle_follow",
        "dialogue_listening",
        "dialogue_idle",
        "dialogue_transcribing",
        "dialogue_answer",
        "dialogue_error",
        "dialogue_unavailable",
        "dialogue_interrupted",
        "photo_viewer_close",
    ]
    x: float = Field(default=0.0, ge=-1.0, le=1.0)
    y: float = Field(default=0.0, ge=-1.0, le=1.0)
    delta: int = Field(default=0, ge=-8, le=8)
    question: str = Field(default="", max_length=1000)
    answer: str = Field(default="", max_length=4000)
    message: str = Field(default="", max_length=500)
    mode: str = Field(default="", max_length=40)


class HardwareSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    icao: Icao


class PhotoViewerState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: bool


class PilotQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audio_base64: str = Field(min_length=16, max_length=16 * 1024 * 1024)

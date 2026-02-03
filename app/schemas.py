from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from app.db import JobStatus, LectureStatus


class SpokenMath(BaseModel):
    latex: str
    spoken: str
    intuition: Optional[str] = None


class FigureNarration(BaseModel):
    figure_id: Optional[str] = None
    description: str
    chart_type: Optional[str] = None
    axes: Optional[str] = None
    trend: Optional[str] = None
    significance: Optional[str] = None


class Chapter(BaseModel):
    name: str
    narration: str
    spoken_math: List[SpokenMath] = Field(default_factory=list)
    figure_narration: List[FigureNarration] = Field(default_factory=list)


class LectureScript(BaseModel):
    title: str
    source_type: str
    duration_estimate_sec: int
    chapters: List[Chapter]
    final_recap: str


class LectureChunk(BaseModel):
    chunk_id: int
    approx_seconds: int
    text: str
    spoken_math: Optional[List[str]] = None
    section_name: Optional[str] = None
    source_refs: Optional[List[str]] = None


class LectureSummary(BaseModel):
    lecture_id: str
    title: str
    created_at: str
    status: LectureStatus
    duration_estimate: Optional[int] = None


class LectureDetail(BaseModel):
    lecture_id: str
    title: str
    created_at: str
    status: LectureStatus
    source_filename: Optional[str] = None
    duration_estimate: Optional[int] = None
    num_chunks: int
    chunks_ready: bool
    script_ready: bool


class LectureChunkResponse(BaseModel):
    lecture_id: str
    chunk: LectureChunk


class LectureContextResponse(BaseModel):
    lecture_id: str
    index: int
    window: int
    approx_seconds: int
    context_text: str


class ClientSecret(BaseModel):
    value: str
    expires_at: int


class RealtimeTokenResponse(BaseModel):
    client_secret: ClientSecret
    realtime_model: str
    voice: str
    lecture_id: str
    server_time: str


class RealtimeInstructionResponse(BaseModel):
    lecture_id: str
    instructions: str


class JobResponse(BaseModel):
    job_id: str
    status: JobStatus
    created_at: str
    updated_at: str
    source_filename: Optional[str] = None
    audio_ready: bool = False
    script_ready: bool = False
    user_error: Optional[str] = None


class UploadResponse(BaseModel):
    job_id: str


class HealthResponse(BaseModel):
    status: str

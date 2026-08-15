from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

class TeamAnalysisPayload(BaseModel):
    team_a_id: str = Field(default="", description="Team A ID")
    team_b_id: str = Field(default="", description="Team B ID")
    event_ids: Optional[List[str]] = Field(default=None, description="Event ID filters")

class BanPickPayload(BaseModel):
    maps_a: Dict[str, Any] = Field(default_factory=dict)
    maps_b: Dict[str, Any] = Field(default_factory=dict)
    map_pool: List[str] = Field(default_factory=list)

class MatchItem(BaseModel):
    id: str
    url: str
    team_a: str
    team_b: str
    event: str = ""
    tournament: str = ""
    stage: str = ""
    round_name: str = ""
    region: str = ""
    tier: str
    status: str
    time: str
    date: str

class MatchDetails(BaseModel):
    match_id: str
    team_a_id: str
    team_a_name: str
    team_b_id: str
    team_b_name: str
    event_id: str

class LiveScoreMap(BaseModel):
    map: str
    score_a: str
    score_b: str

class LiveScoreResponse(BaseModel):
    series_score_a: str
    series_score_b: str
    status: str
    maps: List[LiveScoreMap] = Field(default_factory=list)

class MatchDetailsResponse(BaseModel):
    details: MatchDetails
    team_a_events: List[Dict[str, str]] = Field(default_factory=list)
    team_b_events: List[Dict[str, str]] = Field(default_factory=list)
    map_pool: List[str] = Field(default_factory=list)
    live_score: LiveScoreResponse

class TeamFormResponse(BaseModel):
    form_a: List[str] = Field(default_factory=list)
    form_b: List[str] = Field(default_factory=list)

class MapStatItem(BaseModel):
    played: int = 0
    w: int = 0
    l: int = 0
    atk_won: int = 0
    atk_total: int = 0
    def_won: int = 0
    def_total: int = 0

class TeamMapsResponse(BaseModel):
    maps_a: Dict[str, MapStatItem] = Field(default_factory=dict)
    maps_b: Dict[str, MapStatItem] = Field(default_factory=dict)

class AcePlayer(BaseModel):
    nickname: str = "N/A"
    acs: float = 0.0
    kd_margin: int = 0
    agents: List[str] = Field(default_factory=lambda: ["N/A"])

class AceAnalysisResponse(BaseModel):
    ace_a: AcePlayer
    ace_b: AcePlayer

class AdvancedMetrics(BaseModel):
    map_win_rate: Optional[float] = 50.0
    pistol_win_rate: Optional[float] = 50.0
    fk_fd_margin: Optional[float] = 0.0
    fk_fd_diff: int = 0
    fk_fd_per_round: float = 0.0
    total_played: int = 0
    total_wins: int = 0
    total_fk: int = 0
    total_fd: int = 0
    top_compositions: List[str] = Field(default_factory=list)

class AdvancedMetricsResponse(BaseModel):
    adv_a: AdvancedMetrics
    adv_b: AdvancedMetrics

class BanPickBanItem(BaseModel):
    map: str
    team: str
    reason: str

class BanPickPickItem(BaseModel):
    map: str
    team: str
    win_pct: float

class BanPickResponse(BaseModel):
    bans: List[BanPickBanItem] = Field(default_factory=list)
    picks: List[BanPickPickItem] = Field(default_factory=list)

class HealthResponse(BaseModel):
    status: str = "ok"

class UpstreamHealthResponse(BaseModel):
    status: str = "ok"
    vlr: str = "reachable"

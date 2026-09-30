from typing import Optional, List, Dict, Annotated
from pydantic import BaseModel, Field, ConfigDict, StringConstraints, model_validator

NumericId = Annotated[str, StringConstraints(pattern=r"^\d{0,12}$")]
MapName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]

class TeamAnalysisPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    team_a_id: NumericId = Field(default="", description="Team A ID")
    team_b_id: NumericId = Field(default="", description="Team B ID")
    event_ids: Optional[List[NumericId]] = Field(default=None, max_length=24, description="Event ID filters (12 per team)")

class BanPickMapStat(BaseModel):
    model_config = ConfigDict(extra='forbid')
    played: int = Field(default=0, ge=0, strict=True)
    w: int = Field(default=0, ge=0, strict=True)
    l: Optional[int] = Field(default=None, ge=0, strict=True)
    atk_won: int = Field(default=0, ge=0, strict=True)
    atk_total: int = Field(default=0, ge=0, strict=True)
    def_won: int = Field(default=0, ge=0, strict=True)
    def_total: int = Field(default=0, ge=0, strict=True)

    @model_validator(mode='after')
    def coherent(self):
        if self.w > self.played or (self.l is not None and self.w + self.l != self.played):
            raise ValueError('Wins and losses must agree with played')
        if self.atk_won > self.atk_total or self.def_won > self.def_total:
            raise ValueError('Won rounds exceed total rounds')
        return self


class BanPickPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    maps_a: Dict[MapName, BanPickMapStat] = Field(default_factory=dict, max_length=15)
    maps_b: Dict[MapName, BanPickMapStat] = Field(default_factory=dict, max_length=15)
    map_pool: List[MapName] = Field(default_factory=list, max_length=15)


class FullAnalysisPayload(TeamAnalysisPayload):
    map_pool: List[MapName] = Field(default_factory=list, max_length=15)


class HealthResponse(BaseModel):
    status: str = "ok"

class UpstreamHealthResponse(BaseModel):
    status: str = "ok"
    vlr: str = "reachable"

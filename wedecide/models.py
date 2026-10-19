from datetime import date
from typing import Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

class Provider(Model):
    id: str = Field(default="custom", pattern=r"^[a-zA-Z0-9_-]{1,48}$")
    name: str = Field(default="自定义接口", min_length=1, max_length=80)
    protocol: Literal["openai", "anthropic", "custom"] = "openai"
    endpoint: str = Field(default="", max_length=2000)
    model: str = Field(default="", max_length=200)
    models_endpoint: str = Field(default="", max_length=2000)
    models_path: str = Field(default="data", max_length=200)
    model_id_field: str = Field(default="id", min_length=1, max_length=100)
    api_key: str = Field(default="", max_length=4096)
    clear_key: bool = False
    auth_header: str = Field(default="Authorization", pattern=r"^[A-Za-z0-9-]{1,80}$")
    auth_prefix: str = Field(default="Bearer ", max_length=80)
    headers: dict[str, str] = Field(default_factory=dict)
    extra_body: dict = Field(default_factory=dict)
    request_template: dict = Field(default_factory=dict)
    response_path: str = Field(default="choices.0.message.content", max_length=200)
    timeout: int = Field(default=60, ge=5, le=180)
    max_tokens: int = Field(default=2048, ge=128, le=8192)
    temperature: float = Field(default=0.5, ge=0, le=2)
    enabled: bool = True

    @field_validator("endpoint", "models_endpoint")
    @classmethod
    def valid_endpoint(cls, value):
        if value:
            u = urlsplit(value)
            if u.scheme not in {"http", "https"} or not u.hostname or u.username or u.password or u.fragment or u.query:
                raise ValueError("端点须为完整 http(s) URL；密钥请填鉴权配置，不能放在链接中")
        return value

    @model_validator(mode="after")
    def header_limits(self):
        if len(self.headers) > 20 or len(str(self.extra_body)) > 12000 or len(str(self.request_template)) > 12000:
            raise ValueError("接口配置过大")
        for k, v in {**self.headers, self.auth_header: self.auth_prefix + self.api_key}.items():
            if any(c in k + v for c in "\r\n"):
                raise ValueError("鉴权与请求头不能含换行")
        return self

class ModelDiscovery(Model):
    provider: Provider | None = None
    saved_provider_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,48}$")
    provider_id: str | None = Field(default=None, max_length=48)


class Preference(Model):
    budget_max: float | None = Field(default=None, ge=0, le=1000000)
    available_start: int = Field(default=0, ge=0, le=1439)
    available_end: int = Field(default=1440, ge=1, le=1440)
    excluded_categories: list[str] = Field(default_factory=list, max_length=30)
    allowed_locations: list[str] = Field(default_factory=list, max_length=30)
    max_duration: int | None = Field(default=None, ge=15, le=1440)
    budget_target: float | None = Field(default=None, ge=0, le=1000000)
    budget_weight: int = Field(default=3, ge=1, le=5)
    preferred_start: int | None = Field(default=None, ge=0, le=1439)
    preferred_end: int | None = Field(default=None, ge=1, le=1440)
    time_weight: int = Field(default=3, ge=1, le=5)
    categories: dict[str, Literal[0, 50, 100]] = Field(default_factory=dict)
    activity_weight: int = Field(default=3, ge=1, le=5)
    other: str = Field(default="", max_length=2000)
    unresolved: list[str] = Field(default_factory=list, max_length=20)
    notes: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def coherent(self):
        if self.available_end <= self.available_start:
            raise ValueError("可参加的结束时间须晚于开始时间")
        if self.preferred_start is not None and self.preferred_end is not None and self.preferred_end <= self.preferred_start:
            raise ValueError("偏好的结束时间须晚于开始时间")
        if any(len(v) > 500 for v in self.notes):
            raise ValueError("每条补充说明不超过 500 字")
        if len(self.categories) > 30 or any(len(v) > 80 for v in [*self.categories, *self.excluded_categories, *self.allowed_locations, *self.unresolved]):
            raise ValueError("条件条目过长或过多")
        return self

class Resource(Model):
    id: str = Field(default="", max_length=64)
    name: str = Field(min_length=1, max_length=100)
    category: str = Field(default="休闲", min_length=1, max_length=60)
    location: str = Field(default="", max_length=160)
    cost: float | None = Field(default=None, ge=0, le=1000000)
    cost_upper: float | None = Field(default=None, ge=0, le=1000000)
    fixed_cost: float = Field(default=0, ge=0, le=1000000)
    start: int = Field(default=540, ge=0, le=1439)
    end: int = Field(default=1260, ge=1, le=1440)
    duration: int = Field(default=90, ge=15, le=1440)
    source: str = Field(default="用户提供", max_length=500)
    source_url: str = Field(default="", max_length=2000)
    confirmed: bool = False
    verified: bool = False

    @model_validator(mode="after")
    def coherent(self):
        if self.end - self.start < self.duration:
            raise ValueError("活动时长超过开放窗口")
        if self.cost is not None and self.cost_upper is not None and self.cost_upper < self.cost:
            raise ValueError("费用上界不能小于估算值")
        if self.source_url and urlsplit(self.source_url).scheme not in {"http", "https"}:
            raise ValueError("来源链接须使用 http(s)")
        if self.verified and not self.source_url:
            raise ValueError("标记已核验时须提供依据链接")
        return self

class Rules(Model):
    threshold: float = Field(default=0.8, ge=0.5, le=1)
    fairness: float = Field(default=0.3, ge=0, le=1)
    max_rounds: int = Field(default=3, ge=1, le=5)
    vote_seconds: int = Field(default=86400, ge=30, le=604800)
    max_members: int = Field(default=8, ge=1, le=64)
    max_activities: int = Field(default=2, ge=1, le=2)
    transfer_minutes: int = Field(default=30, ge=0, le=180)
    transfer_cost: float = Field(default=0, ge=0, le=10000)

class Scenario(Model):
    title: str = Field(min_length=1, max_length=100)
    city: str = Field(default="", max_length=80)
    date: str = Field(default="", max_length=10)
    description: str = Field(default="", max_length=2000)
    reference_budget: float | None = Field(default=None, ge=0, le=1000000)

    @field_validator("date")
    @classmethod
    def valid_date(cls, value):
        if value:
            date.fromisoformat(value)
        return value

class CreateRoom(Model):
    username: str = Field(min_length=1, max_length=30)
    scenario: Scenario
    rules: Rules = Field(default_factory=Rules)
    demo: bool = False

class JoinRoom(Model):
    username: str = Field(min_length=1, max_length=30)

class Mutation(Model):
    revision: int = Field(ge=1)
    action: str = Field(max_length=60)
    payload: dict = Field(default_factory=dict)

class AIInput(Model):
    text: str = Field(min_length=1, max_length=6000)
    kind: Literal["chat", "preferences", "scenario", "negotiate"] = "chat"

class Login(Model):
    password: str = Field(min_length=1, max_length=256)

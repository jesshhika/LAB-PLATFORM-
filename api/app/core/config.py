from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "postgresql+psycopg://labforge:local-dev-password@localhost:5432/labforge"
    redis_url: str = "redis://localhost:6379/0"
    dev_user_id: str | None = None
    labs_dir: str | None = None
    key_vault_url: str | None = None
    guac_crypt_key: str | None = None
    guac_ws_url: str = "ws://localhost:8080/"
    azure_subscription_id: str | None = None
    azure_resource_group: str = "rg-labforge-labvms"
    azure_lab_subnet_id: str | None = None
    azure_gallery_image_id: str | None = None
    azure_lab_vm_size: str = "Standard_B2s"
    azure_lab_vm_admin_username: str = "labadmin"
    azure_lab_vm_learner_username: str = "learner"
    max_concurrent_vms: int = Field(default=2, gt=0)
    session_max_minutes: int = Field(default=120, gt=0)
    max_extensions: int = Field(default=1, ge=0)
    idle_timeout_minutes: int = Field(default=20, gt=0)
    daily_vm_hours_cap: int = Field(default=8, gt=0)
    allowed_vm_sizes: str = "Standard_B2s"
    warm_pool_size: int = Field(default=0, ge=0)
    vm_autoshutdown_time: str = "2100"
    vm_autoshutdown_tz: str = "India Standard Time"
    session_extension_minutes: int = Field(default=15, gt=0)
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_uri: str | None = None
    azure_labs_tenant_id: str | None = None
    azure_labs_tenant_domain: str | None = None
    azure_sandbox_subscription_id: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("allowed_vm_sizes")
    @classmethod
    def validate_allowed_vm_sizes(cls, value: str) -> str:
        sizes = [size.strip() for size in value.split(",")]
        if not sizes or any(not size for size in sizes):
            raise ValueError("ALLOWED_VM_SIZES must contain non-empty comma-separated VM sizes.")
        if len(set(sizes)) != len(sizes):
            raise ValueError("ALLOWED_VM_SIZES must not contain duplicate VM sizes.")
        return ",".join(sizes)

    @field_validator("vm_autoshutdown_time")
    @classmethod
    def validate_vm_autoshutdown_time(cls, value: str) -> str:
        if len(value) != 4 or not value.isdigit():
            raise ValueError("VM_AUTOSHUTDOWN_TIME must use the HHMM format.")
        hour, minute = int(value[:2]), int(value[2:])
        if hour > 23 or minute > 59:
            raise ValueError("VM_AUTOSHUTDOWN_TIME must be a valid 24-hour time.")
        return value

    @field_validator("vm_autoshutdown_tz")
    @classmethod
    def validate_vm_autoshutdown_timezone(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("VM_AUTOSHUTDOWN_TZ must not be empty.")
        return value.strip()

    @property
    def allowed_vm_size_set(self) -> frozenset[str]:
        return frozenset(self.allowed_vm_sizes.split(","))


@lru_cache
def get_settings() -> Settings:
    return Settings()

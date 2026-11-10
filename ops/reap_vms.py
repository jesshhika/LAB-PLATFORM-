#!/usr/bin/env python3
import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Sequence

from azure.core.exceptions import AzureError, ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.resource import ResourceManagementClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

TARGET_RESOURCE_GROUP = "rg-labforge-labvms"
SCHEDULE_API_VERSION = "2018-09-15"
MISSING_SESSION_GRACE = timedelta(minutes=15)
logger = logging.getLogger("labforge.reaper")


@dataclass(frozen=True)
class ResourceRef:
    resource_type: str
    name: str
    resource_id: str


def _value(resource: Any, name: str, default: Any = None) -> Any:
    if isinstance(resource, dict):
        return resource.get(name, default)
    return getattr(resource, name, default)


def _in_target_group(resource_id: str | None) -> bool:
    if not resource_id:
        return False
    marker = f"/resourcegroups/{TARGET_RESOURCE_GROUP}/"
    return marker in resource_id.casefold()


def _tagged_for_labforge(resource: Any) -> bool:
    tags = _value(resource, "tags") or {}
    return str(tags.get("labforge", "")).casefold() == "true"


def _session_id(resource: Any) -> str | None:
    tags = _value(resource, "tags") or {}
    value = tags.get("session_id")
    return str(value) if value else None


def _created_at(resource: Any) -> datetime | None:
    tags = _value(resource, "tags") or {}
    raw_value = tags.get("created_at")
    if not isinstance(raw_value, str):
        return None
    try:
        value = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _old_enough(resource: Any, now: datetime, threshold: timedelta) -> bool:
    created_at = _created_at(resource)
    return created_at is not None and now - created_at > threshold


def _resource_eligible(
    resource: Any,
    session_statuses: dict[str, str],
    now: datetime,
    session_max_minutes: int,
    db_available: bool,
) -> bool:
    if _old_enough(resource, now, timedelta(minutes=session_max_minutes * 2)):
        return True
    if not db_available:
        return False
    session_id = _session_id(resource)
    if not session_id:
        return False
    status = session_statuses.get(session_id)
    if status is not None:
        return status in {"ended", "failed"}
    return _old_enough(resource, now, MISSING_SESSION_GRACE)


def select_vms_to_delete(
    vms: Sequence[Any],
    session_statuses: dict[str, str],
    now: datetime,
    session_max_minutes: int,
    *,
    db_available: bool = True,
) -> list[Any]:
    return [
        vm
        for vm in vms
        if _in_target_group(_value(vm, "id"))
        and _tagged_for_labforge(vm)
        and _resource_eligible(vm, session_statuses, now, session_max_minutes, db_available)
    ]


def select_resources_to_delete(
    vms: Sequence[Any],
    nics: Sequence[Any],
    disks: Sequence[Any],
    generic_resources: Sequence[Any],
    session_statuses: dict[str, str],
    now: datetime,
    session_max_minutes: int,
    *,
    db_available: bool = True,
) -> list[ResourceRef]:
    selected_vms = select_vms_to_delete(
        vms,
        session_statuses,
        now,
        session_max_minutes,
        db_available=db_available,
    )
    selected_vm_ids = {
        str(_value(vm, "id")).casefold()
        for vm in selected_vms
        if _value(vm, "id")
    }
    selected_session_ids = {
        session_id for vm in selected_vms if (session_id := _session_id(vm))
    }
    result: list[ResourceRef] = []

    for resource in generic_resources:
        resource_type = str(_value(resource, "type", "")).casefold()
        resource_id = _value(resource, "id")
        if (
            resource_type == "microsoft.devtestlab/schedules"
            and _in_target_group(resource_id)
            and _tagged_for_labforge(resource)
            and (
                _session_id(resource) in selected_session_ids
                or _resource_eligible(
                    resource,
                    session_statuses,
                    now,
                    session_max_minutes,
                    db_available,
                )
            )
        ):
            result.append(
                ResourceRef(
                    resource_type="schedule",
                    name=str(_value(resource, "name")),
                    resource_id=resource_id,
                )
            )

    for vm in selected_vms:
        result.append(
            ResourceRef(
                resource_type="vm",
                name=str(_value(vm, "name")),
                resource_id=str(_value(vm, "id")),
            )
        )

    for nic in nics:
        resource_id = _value(nic, "id")
        if (
            not _in_target_group(resource_id)
            or not _tagged_for_labforge(nic)
        ):
            continue
        vm_ref = _value(nic, "virtual_machine")
        attached_vm_id = _value(vm_ref, "id") if vm_ref else None
        selected_with_session = _session_id(nic) in selected_session_ids
        attached_to_selected = bool(
            attached_vm_id and attached_vm_id.casefold() in selected_vm_ids
        )
        if attached_vm_id and not attached_to_selected:
            continue
        if not (attached_to_selected or selected_with_session) and not _resource_eligible(
            nic,
            session_statuses,
            now,
            session_max_minutes,
            db_available,
        ):
            continue
        result.append(
            ResourceRef(
                resource_type="nic",
                name=str(_value(nic, "name")),
                resource_id=str(resource_id),
            )
        )

    for disk in disks:
        resource_id = _value(disk, "id")
        if (
            not _in_target_group(resource_id)
            or not _tagged_for_labforge(disk)
            or _value(disk, "managed_by")
            or not _resource_eligible(
                disk,
                session_statuses,
                now,
                session_max_minutes,
                db_available,
            )
        ):
            continue
        result.append(
            ResourceRef(
                resource_type="disk",
                name=str(_value(disk, "name")),
                resource_id=str(resource_id),
            )
        )

    deletion_order = {"schedule": 0, "vm": 1, "nic": 2, "disk": 3}
    return sorted(result, key=lambda item: (deletion_order[item.resource_type], item.name))


def _database_url(credential: DefaultAzureCredential) -> str:
    direct_url = os.getenv("DATABASE_URL")
    if direct_url:
        return direct_url
    vault_url = os.getenv("KEY_VAULT_URL")
    secret_name = os.getenv("REAPER_DB_SECRET_NAME")
    if not vault_url or not secret_name:
        raise RuntimeError("Set DATABASE_URL or both KEY_VAULT_URL and REAPER_DB_SECRET_NAME.")
    secret = SecretClient(vault_url=vault_url, credential=credential).get_secret(secret_name)
    if not secret.value:
        raise RuntimeError(f"Key Vault secret {secret_name!r} is empty.")
    return secret.value


def load_session_statuses(database_url: str) -> dict[str, str]:
    engine = create_engine(database_url, pool_pre_ping=True, connect_args={"connect_timeout": 10})
    try:
        with engine.connect() as connection:
            rows = connection.execute(text("SELECT id, status FROM lab_sessions"))
            return {str(row.id): str(row.status) for row in rows}
    finally:
        engine.dispose()


def _resource_refs(
    credential: DefaultAzureCredential,
    subscription_id: str,
) -> tuple[list[Any], list[Any], list[Any], list[Any]]:
    compute = ComputeManagementClient(credential, subscription_id)
    network = NetworkManagementClient(credential, subscription_id)
    resources = ResourceManagementClient(credential, subscription_id)
    return (
        list(compute.virtual_machines.list(TARGET_RESOURCE_GROUP)),
        list(network.network_interfaces.list(TARGET_RESOURCE_GROUP)),
        list(compute.disks.list_by_resource_group(TARGET_RESOURCE_GROUP)),
        list(resources.resources.list_by_resource_group(TARGET_RESOURCE_GROUP)),
    )


def delete_resources(
    resources: Sequence[ResourceRef],
    compute: ComputeManagementClient,
    network: NetworkManagementClient,
    resource_client: ResourceManagementClient,
    *,
    dry_run: bool,
    max_delete: int,
    force: bool,
) -> dict[str, int]:
    summary = {"deleted": 0, "would_delete": 0, "skipped": 0, "errors": 0}
    if len(resources) > max_delete and not force:
        logger.error(
            json.dumps(
                {
                    "event": "delete_limit_exceeded",
                    "selected": len(resources),
                    "max_delete": max_delete,
                    "force_required": True,
                },
                sort_keys=True,
            )
        )
        summary["errors"] = 1
        summary["skipped"] = len(resources)
        return summary

    for resource in resources:
        if dry_run:
            logger.info(
                json.dumps(
                    {"event": "would_delete", "type": resource.resource_type, "name": resource.name},
                    sort_keys=True,
                )
            )
            summary["would_delete"] += 1
            continue
        try:
            if resource.resource_type == "schedule":
                resource_client.resources.begin_delete_by_id(
                    resource.resource_id,
                    SCHEDULE_API_VERSION,
                ).result(timeout=600)
            elif resource.resource_type == "vm":
                compute.virtual_machines.begin_delete(
                    TARGET_RESOURCE_GROUP, resource.name
                ).result(timeout=900)
            elif resource.resource_type == "nic":
                network.network_interfaces.begin_delete(
                    TARGET_RESOURCE_GROUP, resource.name
                ).result(timeout=600)
            elif resource.resource_type == "disk":
                compute.disks.begin_delete(
                    TARGET_RESOURCE_GROUP, resource.name
                ).result(timeout=600)
            summary["deleted"] += 1
        except ResourceNotFoundError:
            summary["skipped"] += 1
        except Exception as exc:
            logger.exception(
                "Resource deletion failed: %s %s",
                resource.resource_type,
                resource.name,
            )
            summary["errors"] += 1
    return summary


def _positive_int(value: str, label: str, *, allow_zero: bool = False) -> int:
    try:
        result = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{label} must be an integer.") from exc
    if result < 0 or (result == 0 and not allow_zero):
        qualifier = "non-negative" if allow_zero else "positive"
        raise argparse.ArgumentTypeError(f"{label} must be {qualifier}.")
    return result


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Safely reap tagged LabForge staging resources.")
    parser.add_argument("--dry-run", action="store_true", help="Report selected resources without deleting.")
    parser.add_argument("--max-delete", type=lambda value: _positive_int(value, "--max-delete", allow_zero=True), default=5)
    parser.add_argument("--force", action="store_true", help="Allow selection above --max-delete.")
    args = parser.parse_args(argv)
    configured_group = os.getenv("AZURE_RESOURCE_GROUP", TARGET_RESOURCE_GROUP)
    if configured_group != TARGET_RESOURCE_GROUP:
        parser.error(f"Refusing resource group {configured_group!r}; only {TARGET_RESOURCE_GROUP!r} is allowed.")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = _arguments(argv)
    subscription_id = os.getenv("AZURE_SUBSCRIPTION_ID")
    if not subscription_id:
        logger.error("AZURE_SUBSCRIPTION_ID is required.")
        return 2
    session_max_minutes = _positive_int(
        os.getenv("SESSION_MAX_MINUTES", "120"),
        "SESSION_MAX_MINUTES",
    )

    credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
    db_available = True
    session_statuses: dict[str, str] = {}
    try:
        try:
            session_statuses = load_session_statuses(_database_url(credential))
        except (AzureError, SQLAlchemyError, RuntimeError, OSError) as exc:
            db_available = False
            logger.error(
                json.dumps(
                    {"event": "database_unavailable", "error": str(exc), "action": "age_rule_only"},
                    sort_keys=True,
                )
            )

        vms, nics, disks, generic_resources = _resource_refs(credential, subscription_id)
        selected = select_resources_to_delete(
            vms,
            nics,
            disks,
            generic_resources,
            session_statuses,
            datetime.now(UTC),
            session_max_minutes,
            db_available=db_available,
        )
        compute = ComputeManagementClient(credential, subscription_id)
        network = NetworkManagementClient(credential, subscription_id)
        resource_client = ResourceManagementClient(credential, subscription_id)
        summary = delete_resources(
            selected,
            compute,
            network,
            resource_client,
            dry_run=args.dry_run,
            max_delete=args.max_delete,
            force=args.force,
        )
        summary.update(
            {
                "selected": len(selected),
                "db_available": int(db_available),
                "dry_run": int(args.dry_run),
            }
        )
        logger.info(json.dumps({"event": "reaper_summary", **summary}, sort_keys=True))
        return 1 if not db_available or summary["errors"] else 0
    except AzureError as exc:
        logger.exception("Azure reaper operation failed: %s", exc)
        return 1
    finally:
        credential.close()


if __name__ == "__main__":
    sys.exit(main())

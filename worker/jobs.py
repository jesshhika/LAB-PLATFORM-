import logging
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from azure.core.exceptions import ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from azure.mgmt.authorization import AuthorizationManagementClient
from azure.mgmt.authorization.models import RoleAssignmentCreateParameters
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.compute.models import (
    HardwareProfile,
    ImageReference,
    NetworkInterfaceReference,
    NetworkProfile,
    OSDisk,
    OSProfile,
    RunCommandInput,
    RunCommandInputParameter,
    StorageProfile,
    VirtualMachine,
)
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.network.models import (
    NetworkInterface,
    NetworkInterfaceIPConfiguration,
    Subnet,
)
from azure.mgmt.resource import ResourceManagementClient
from sqlalchemy import select

from api.app.catalog import get_course, get_lab, load_courses
from api.app.core.config import get_settings
from api.app.core.db import SessionLocal
from api.app.cost_controls import initial_session_minutes
from api.app.models import LabSession

logger = logging.getLogger(__name__)


def _random_secret() -> str:
    return secrets.token_urlsafe(32)


def _secret_name(prefix: str, vm_name: str) -> str:
    return f"{prefix}-{vm_name}".lower()[:127]


def _clients() -> tuple[DefaultAzureCredential, str, ComputeManagementClient, NetworkManagementClient]:
    settings = get_settings()
    if not settings.azure_subscription_id:
        raise RuntimeError("AZURE_SUBSCRIPTION_ID is required for VM provisioning.")
    credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
    return (
        credential,
        settings.azure_subscription_id,
        ComputeManagementClient(credential, settings.azure_subscription_id),
        NetworkManagementClient(credential, settings.azure_subscription_id),
    )


def _gallery_image_id(session: LabSession) -> str:
    settings = get_settings()
    if settings.azure_gallery_image_id:
        return settings.azure_gallery_image_id
    lab = get_lab(session.lab_id)
    course = get_course(lab["course_id"])
    image = course.get("image", {})
    if not image.get("definition") or not image.get("version"):
        raise RuntimeError(f"No gallery image is configured for course {lab['course_id']}.")
    return (
        f"/subscriptions/{settings.azure_subscription_id}/resourceGroups/rg-labforge-core/"
        f"providers/Microsoft.Compute/galleries/galLabForge/images/{image['definition']}/"
        f"versions/{image['version']}"
    )


def _image_reference(session: LabSession) -> ImageReference:
    settings = get_settings()
    if settings.azure_gallery_image_id:
        return ImageReference(id=settings.azure_gallery_image_id)
    lab = get_lab(session.lab_id)
    course = get_course(lab["course_id"])
    image = course.get("image", {})
    if image.get("definition") and image.get("version"):
        return _gallery_image_reference(session)
    if image.get("publisher") and image.get("offer") and image.get("sku"):
        return ImageReference(
            publisher=image["publisher"],
            offer=image["offer"],
            sku=image["sku"],
            version=image.get("version", "latest"),
        )
    raise RuntimeError(f"No usable image is configured for course {lab['course_id']}.")


def _gallery_image_reference(session: LabSession) -> ImageReference:
    settings = get_settings()
    lab = get_lab(session.lab_id)
    course = get_course(lab["course_id"])
    image = course.get("image", {})
    if not image.get("definition") or image.get("publisher"):
        raise RuntimeError(f"No usable image is configured for course {lab['course_id']}.")
    return ImageReference(
        id=(
            f"/subscriptions/{settings.azure_subscription_id}/resourceGroups/rg-labforge-core/"
            f"providers/Microsoft.Compute/galleries/galLabForge/images/{image['definition']}/"
            f"versions/{image['version']}"
        )
    )


def create_lab_vm(session: LabSession) -> tuple[str, str]:
    settings = get_settings()
    if not settings.azure_lab_subnet_id:
        raise RuntimeError("AZURE_LAB_SUBNET_ID is required for VM provisioning.")
    if not settings.key_vault_url:
        raise RuntimeError("KEY_VAULT_URL is required to store VM credentials.")

    lab = get_lab(session.lab_id)
    course = get_course(lab["course_id"])
    vm_size = course.get("vm_size", settings.azure_lab_vm_size)
    if vm_size not in settings.allowed_vm_size_set:
        raise RuntimeError(f"VM size {vm_size!r} is not in ALLOWED_VM_SIZES.")

    credential, subscription_id, compute, network = _clients()
    resource_client = ResourceManagementClient(credential, subscription_id)
    resource_group = settings.azure_resource_group
    vm_name = f"vm-{session.id.replace('-', '')[:20]}"
    nic_name = f"{vm_name}-nic"
    admin_password = _random_secret()
    learner_password = _random_secret()
    admin_secret_name = _secret_name("vm-admin", vm_name)
    learner_secret_name = _secret_name("vm", vm_name)
    location = "centralindia"
    created_at = datetime.now(UTC)
    initial_minutes = initial_session_minutes(
        int(course.get("session_minutes", settings.session_max_minutes)),
        settings.session_max_minutes,
        settings.session_extension_minutes,
        settings.max_extensions,
    )
    initial_expiry = created_at + timedelta(minutes=initial_minutes)
    created_tags = {
        "labforge": "true",
        "session_id": session.id,
        "user_id": session.user_id,
        "course": lab["course_id"],
        "created_at": created_at.isoformat(),
        "expires_at": initial_expiry.isoformat(),
    }
    nic_created = False
    vm_created = False
    schedule_created = False

    try:
        nic_created = True
        nic = network.network_interfaces.begin_create_or_update(
            resource_group,
            nic_name,
            NetworkInterface(
                location=location,
                tags=created_tags,
                ip_configurations=[
                    NetworkInterfaceIPConfiguration(
                        name="ipconfig1",
                        subnet=Subnet(id=settings.azure_lab_subnet_id),
                        private_ip_allocation_method="Dynamic",
                        primary=True,
                    )
                ],
            ),
        ).result()

        started_at = datetime.now(UTC)
        expires_at = started_at + timedelta(minutes=initial_minutes)
        with SessionLocal() as db:
            stored_session = db.scalar(
                select(LabSession).where(LabSession.id == session.id)
            )
            if stored_session is None:
                raise RuntimeError(f"Lab session {session.id} disappeared before VM creation.")
            stored_session.started_at = started_at
            stored_session.expires_at = expires_at
            stored_session.max_expires_at = started_at + timedelta(
                minutes=settings.session_max_minutes
            )
            db.commit()

        vm = VirtualMachine(
            location=location,
            tags={
                **created_tags,
                "created_at": started_at.isoformat(),
                "expires_at": expires_at.isoformat(),
            },
            hardware_profile=HardwareProfile(
                vm_size=vm_size
            ),
            storage_profile=StorageProfile(
                image_reference=_image_reference(session),
                os_disk=OSDisk(
                    create_option="FromImage",
                    managed_disk={"storageAccountType": "StandardSSD_LRS"},
                    caching="ReadWrite",
                    delete_option="Delete",
                ),
            ),
            os_profile=OSProfile(
                computer_name=vm_name[:15],
                admin_username=settings.azure_lab_vm_admin_username,
                admin_password=admin_password,
                windows_configuration={
                    "provisionVMAgent": True,
                    "enableAutomaticUpdates": True,
                },
            ),
            network_profile=NetworkProfile(
                network_interfaces=[
                    NetworkInterfaceReference(
                        id=nic.id,
                        primary=True,
                        delete_option="Delete",
                    )
                ]
            ),
            diagnostics_profile={"bootDiagnostics": {"enabled": False}},
        )
        vm_created = True
        compute.virtual_machines.begin_create_or_update(resource_group, vm_name, vm).result()

        schedule_id = (
            f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
            f"/providers/Microsoft.DevTestLab/schedules/shutdown-computevm-{vm_name}"
        )
        schedule_created = True
        resource_client.resources.begin_create_or_update_by_id(
            schedule_id,
            "2018-09-15",
            {
                "location": location,
                "tags": {
                    **created_tags,
                    "created_at": started_at.isoformat(),
                    "expires_at": expires_at.isoformat(),
                },
                "properties": {
                    "status": "Enabled",
                    "taskType": "ComputeVmShutdownTask",
                    "dailyRecurrence": {"time": settings.vm_autoshutdown_time},
                    "timeZoneId": settings.vm_autoshutdown_tz,
                    "targetResourceId": (
                        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
                        f"/providers/Microsoft.Compute/virtualMachines/{vm_name}"
                    ),
                    "notificationSettings": {"status": "Disabled"},
                },
            },
        ).result()

        nic = network.network_interfaces.get(resource_group, nic_name)
        private_ip = (
            nic.ip_configurations[0].private_ip_address
            if nic.ip_configurations
            else None
        )
        if not private_ip:
            raise RuntimeError("The provisioned VM did not receive a private IP.")

        secret_client = SecretClient(vault_url=settings.key_vault_url, credential=credential)
        secret_client.set_secret(admin_secret_name, admin_password)
        secret_client.set_secret(learner_secret_name, learner_password)

        compute.virtual_machines.begin_run_command(
            resource_group,
            vm_name,
            RunCommandInput(
                command_id="PowerShell",
                script=[
                    "$securePassword = ConvertTo-SecureString $learnerPassword -AsPlainText -Force",
                    "$learner = Get-LocalUser -Name $learnerName -ErrorAction SilentlyContinue",
                    "if ($null -eq $learner) { New-LocalUser -Name $learnerName -Password $securePassword -PasswordNeverExpires }",
                    "else { Set-LocalUser -Name $learnerName -Password $securePassword -PasswordNeverExpires }",
                ],
                parameters=[
                    RunCommandInputParameter(name="learnerPassword", value=learner_password),
                    RunCommandInputParameter(
                        name="learnerName", value=settings.azure_lab_vm_learner_username
                    ),
                ],
            ),
        ).result()
    except Exception:
        if schedule_created:
            try:
                resource_client.resources.begin_delete_by_id(
                    schedule_id,
                    "2018-09-15",
                ).result(timeout=600)
            except ResourceNotFoundError:
                pass
            except Exception:
                logger.exception("Could not roll back VM auto-shutdown schedule %s.", vm_name)
        if vm_created:
            try:
                compute.virtual_machines.begin_delete(
                    resource_group, vm_name
                ).result(timeout=600)
            except ResourceNotFoundError:
                pass
            except Exception:
                logger.exception("Could not roll back VM %s.", vm_name)
        if nic_created:
            try:
                network.network_interfaces.begin_delete(
                    resource_group, nic_name
                ).result(timeout=600)
            except ResourceNotFoundError:
                pass
            except Exception:
                logger.exception("Could not roll back NIC %s.", nic_name)
        try:
            disk_client = ComputeManagementClient(credential, settings.azure_subscription_id)
            for disk in disk_client.disks.list_by_resource_group(resource_group):
                if disk.name and disk.name.startswith(vm_name):
                    try:
                        disk_client.disks.begin_delete(resource_group, disk.name).result(timeout=600)
                    except ResourceNotFoundError:
                        pass
                    except Exception:
                        logger.exception("Could not roll back disk %s.", disk.name)
        except Exception:
            logger.exception("Could not enumerate disks while rolling back VM %s.", vm_name)
        if settings.key_vault_url:
            try:
                secret_client = SecretClient(
                    vault_url=settings.key_vault_url,
                    credential=credential,
                )
                for secret_name in {admin_secret_name, learner_secret_name}:
                    try:
                        secret_client.begin_delete_secret(secret_name).result(timeout=600)
                    except ResourceNotFoundError:
                        pass
                    except Exception:
                        logger.exception("Could not roll back Key Vault secret %s.", secret_name)
            except Exception:
                logger.exception("Could not create Key Vault client during VM rollback.")
        raise
    finally:
        credential.close()

    return vm_name, private_ip


def create_sandbox(session: LabSession) -> None:
    settings = get_settings()
    lab = get_lab(session.lab_id)
    course = get_course(lab["course_id"])
    if not course.get("needs_azure_sandbox", False):
        return
    required = (
        settings.azure_labs_tenant_id,
        settings.azure_labs_tenant_domain,
        settings.azure_sandbox_subscription_id,
        settings.key_vault_url,
    )
    if not all(required):
        raise RuntimeError("Azure sandbox tenant, domain, subscription, and Key Vault are required.")

    short_id = session.id.replace("-", "")[:8]
    upn = f"lab-{short_id}@{settings.azure_labs_tenant_domain}"
    password = _random_secret()[:16]
    resource_group = f"rg-lab-{short_id}"
    username_secret = _secret_name("azure-user", short_id)
    password_secret = _secret_name("azure-password", short_id)

    credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
    graph_token = credential.get_token("https://graph.microsoft.com/.default").token
    headers = {"Authorization": f"Bearer {graph_token}", "Content-Type": "application/json"}
    graph_user_id: str | None = None
    resource_group_created = False
    created_secrets: set[str] = set()
    try:
        response = httpx.post(
            "https://graph.microsoft.com/v1.0/users",
            headers=headers,
            json={
                "accountEnabled": True,
                "displayName": f"LabForge learner {short_id}",
                "mailNickname": f"lab-{short_id}",
                "userPrincipalName": upn,
                "passwordProfile": {
                    "forceChangePasswordNextSignIn": False,
                    "password": password,
                },
                "usageLocation": "IN",
            },
            timeout=30.0,
        )
        if response.status_code >= 300:
            raise RuntimeError(f"Microsoft Graph user creation failed: {response.text}")
        graph_user = response.json()
        graph_user_id = graph_user["id"]

        resource_client = ResourceManagementClient(
            credential, settings.azure_sandbox_subscription_id
        )
        resource_group_created = True
        resource_client.resource_groups.create_or_update(
            resource_group,
            {
                "location": "centralindia",
                "tags": {
                    "labforge": "true",
                    "session_id": session.id,
                    "user_id": session.user_id,
                },
            },
        )

        authorization = AuthorizationManagementClient(
            credential, settings.azure_sandbox_subscription_id
        )
        assignment_scope = (
            f"/subscriptions/{settings.azure_sandbox_subscription_id}"
            f"/resourceGroups/{resource_group}"
        )
        contributor_role_id = (
            f"/subscriptions/{settings.azure_sandbox_subscription_id}"
            "/providers/Microsoft.Authorization/roleDefinitions/"
            "b24988ac-6180-42a0-ab88-20f7382dd24c"
        )
        for attempt in range(6):
            try:
                authorization.role_assignments.create(
                    assignment_scope,
                    str(uuid.uuid4()),
                    RoleAssignmentCreateParameters(
                        role_definition_id=contributor_role_id,
                        principal_id=graph_user["id"],
                        principal_type="User",
                    ),
                )
                break
            except Exception:
                if attempt == 5:
                    raise
                time.sleep(10)

        secret_client = SecretClient(vault_url=settings.key_vault_url, credential=credential)
        secret_client.set_secret(username_secret, upn)
        created_secrets.add(username_secret)
        secret_client.set_secret(password_secret, password)
        created_secrets.add(password_secret)

        with SessionLocal() as db:
            stored = db.scalar(select(LabSession).where(LabSession.id == session.id))
            if stored is not None:
                stored.azure_username_secret_name = username_secret
                stored.azure_password_secret_name = password_secret
                stored.azure_resource_group = resource_group
                stored.azure_subscription_id = settings.azure_sandbox_subscription_id
                db.commit()
    except Exception:
        if resource_group_created:
            try:
                ResourceManagementClient(
                    credential, settings.azure_sandbox_subscription_id
                ).resource_groups.begin_delete(resource_group).result(timeout=900)
            except Exception:
                logger.exception("Could not roll back sandbox resource group %s.", resource_group)
        if graph_user_id:
            try:
                delete_response = httpx.delete(
                    f"https://graph.microsoft.com/v1.0/users/{graph_user_id}",
                    headers={"Authorization": f"Bearer {graph_token}"},
                    timeout=30.0,
                )
                if delete_response.status_code >= 300 and delete_response.status_code != 404:
                    logger.error(
                        "Could not roll back Graph user %s: HTTP %s",
                        graph_user_id,
                        delete_response.status_code,
                    )
            except httpx.HTTPError:
                logger.exception("Could not roll back Graph user %s.", graph_user_id)
        if created_secrets:
            try:
                secret_client = SecretClient(
                    vault_url=settings.key_vault_url,
                    credential=credential,
                )
                for secret_name in created_secrets:
                    try:
                        secret_client.begin_delete_secret(secret_name).result(timeout=60)
                    except ResourceNotFoundError:
                        pass
                    except Exception:
                        logger.exception("Could not roll back sandbox secret %s.", secret_name)
            except Exception:
                logger.exception("Could not create Key Vault client during sandbox rollback.")
        raise
    finally:
        credential.close()


def delete_sandbox(session: LabSession) -> None:
    settings = get_settings()
    if not session.azure_resource_group and not session.azure_username_secret_name:
        return
    credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
    try:
        if session.azure_resource_group and settings.azure_sandbox_subscription_id:
            resources = ResourceManagementClient(
                credential, settings.azure_sandbox_subscription_id
            )
            resources.resource_groups.begin_delete(session.azure_resource_group).result(timeout=900)

        if session.azure_username_secret_name and settings.key_vault_url:
            secret_client = SecretClient(vault_url=settings.key_vault_url, credential=credential)
            upn = secret_client.get_secret(session.azure_username_secret_name).value
            if upn:
                token = credential.get_token("https://graph.microsoft.com/.default").token
                httpx.delete(
                    f"https://graph.microsoft.com/v1.0/users/{upn}",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=30.0,
                )
            for secret_name in {
                session.azure_username_secret_name,
                session.azure_password_secret_name,
            }:
                if secret_name:
                    try:
                        secret_client.begin_delete_secret(secret_name).result(timeout=60)
                    except Exception:
                        pass
    finally:
        credential.close()


def provision_lab_session(session_id: str) -> None:
    settings = get_settings()
    with SessionLocal() as db:
        session = db.scalar(select(LabSession).where(LabSession.id == session_id))
        if session is None:
            raise RuntimeError(f"Lab session {session_id} does not exist.")
        if session.status == "ready":
            return
        if session.status not in {"queued", "provisioning"}:
            return
        session.status = "provisioning"
        db.commit()

    vm_provisioned = False
    try:
        vm_name, private_ip = create_lab_vm(session)
        vm_provisioned = True
        with SessionLocal() as db:
            session = db.scalar(select(LabSession).where(LabSession.id == session_id))
            if session is None:
                raise RuntimeError(f"Lab session {session_id} disappeared during provisioning.")
            if session.started_at is None:
                raise RuntimeError(f"Lab session {session_id} has no VM start timestamp.")
            lab = get_lab(session.lab_id)
            course = get_course(lab["course_id"])
            started_at = session.started_at
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=UTC)
            else:
                started_at = started_at.astimezone(UTC)
            initial_minutes = initial_session_minutes(
                int(course.get("session_minutes", settings.session_max_minutes)),
                settings.session_max_minutes,
                settings.session_extension_minutes,
                settings.max_extensions,
            )
            session.vm_name = vm_name
            session.resource_group = settings.azure_resource_group
            session.vm_private_ip = private_ip
            session.vm_username = settings.azure_lab_vm_learner_username
            session.vm_password_secret_name = _secret_name("vm", vm_name)
            session.status = "ready"
            session.expires_at = started_at + timedelta(minutes=initial_minutes)
            session.max_expires_at = started_at + timedelta(
                minutes=settings.session_max_minutes
            )
            session.last_activity_at = started_at
            db.commit()
        create_sandbox(session)
    except Exception as exc:
        if vm_provisioned:
            try:
                cleanup_lab_session(session_id)
            except Exception:
                logger.exception("Could not clean up partially provisioned session %s.", session_id)
        with SessionLocal() as db:
            session = db.scalar(select(LabSession).where(LabSession.id == session_id))
            if session is not None:
                session.status = "failed"
                session.ended_at = datetime.now(UTC)
                db.commit()
        raise RuntimeError(
            f"Failed to provision lab session {session_id}: {exc}"
        ) from exc


def delete_lab_vm(
    session_id: str,
    resource_group: str,
    vm_name: str | None = None,
) -> None:
    settings = get_settings()
    if not settings.azure_subscription_id:
        raise RuntimeError("AZURE_SUBSCRIPTION_ID is required for cleanup.")

    credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
    try:
        resource_client = ResourceManagementClient(
            credential, settings.azure_subscription_id
        )
        tagged_resources = [
            resource
            for resource in resource_client.resources.list_by_resource_group(resource_group)
            if resource.tags and resource.tags.get("session_id") == session_id
        ]
        if vm_name:
            resource_ids = {
                resource.id.lower()
                for resource in tagged_resources
                if resource.id
            }
            tagged_resources.extend(
                resource
                for resource in resource_client.resources.list_by_resource_group(resource_group)
                if (resource.type or "").lower() == "microsoft.compute/disks"
                and (resource.name or "").startswith(vm_name)
            )
            fallback_types = {
                "microsoft.compute/virtualmachines": vm_name,
                "microsoft.network/networkinterfaces": f"{vm_name}-nic",
            }
            for resource_type, name in fallback_types.items():
                namespace, _, type_name = resource_type.partition("/")
                resource_id = (
                    f"/subscriptions/{settings.azure_subscription_id}/resourceGroups/"
                    f"{resource_group}/providers/{namespace}/{type_name}/{name}"
                )
                if resource_id.lower() not in resource_ids:
                    provider = resource_client.providers.get(namespace)
                    api_version = next(
                        (
                            candidate.api_versions[0]
                            for candidate in provider.resource_types or []
                            if candidate.resource_type.lower() == type_name.lower()
                        ),
                        None,
                    )
                    if api_version:
                        tagged_resources.append(
                            type(
                                "FallbackResource",
                                (),
                                {
                                    "id": resource_id,
                                    "type": resource_type,
                                    "tags": {"session_id": session_id},
                                },
                            )()
                        )
        delete_order = {
            "microsoft.compute/virtualmachines": 0,
            "microsoft.network/networkinterfaces": 1,
            "microsoft.compute/disks": 2,
        }
        tagged_resources.sort(
            key=lambda resource: delete_order.get((resource.type or "").lower(), 3)
        )
        for resource in tagged_resources:
            if not resource.id or not resource.type:
                continue
            namespace, _, type_name = resource.type.partition("/")
            provider = resource_client.providers.get(namespace)
            api_version = next(
                (
                    candidate.api_versions[0]
                    for candidate in provider.resource_types or []
                    if candidate.resource_type.lower() == type_name.lower()
                    and candidate.api_versions
                ),
                None,
            )
            if api_version:
                resource_client.resources.begin_delete_by_id(
                    resource.id, api_version
                ).result()
    finally:
        credential.close()


def cleanup_lab_session(session_id: str) -> None:
    with SessionLocal() as db:
        session = db.scalar(select(LabSession).where(LabSession.id == session_id))
        if session is None:
            raise RuntimeError(f"Lab session {session_id} does not exist.")
        if session.status == "ended":
            return
        resource_group = session.resource_group
        if not resource_group:
            raise RuntimeError(f"Lab session {session_id} has no resource group.")
        secret_names = [
            session.vm_password_secret_name,
            session.azure_username_secret_name,
            session.azure_password_secret_name,
        ]
        secret_names = [name for name in secret_names if name]
    delete_lab_vm(session_id, resource_group, session.vm_name)
    delete_sandbox(session)
    settings = get_settings()
    if settings.key_vault_url and secret_names:
        credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
        try:
            secret_client = SecretClient(
                vault_url=settings.key_vault_url, credential=credential
            )
            for secret_name in secret_names:
                try:
                    secret_client.begin_delete_secret(secret_name).result()
                except Exception:
                    pass
        finally:
            credential.close()
    with SessionLocal() as db:
        session = db.scalar(select(LabSession).where(LabSession.id == session_id))
        if session is not None:
            session.status = "ended"
            session.ended_at = datetime.now(UTC)
            db.commit()


def expire_sessions() -> int:
    now = datetime.now(UTC)
    expired_ids: list[str] = []
    with SessionLocal() as db:
        sessions = db.scalars(
            select(LabSession).where(
                LabSession.status.in_(["ready", "provisioning"]),
                LabSession.expires_at <= now,
            )
        )
        for session in sessions:
            session.status = "ending"
            expired_ids.append(session.id)
        db.commit()
    return len(expired_ids)


def reap_orphaned_lab_resources() -> int:
    settings = get_settings()
    if not settings.azure_subscription_id:
        return 0
    credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
    removed = 0
    try:
        compute = ComputeManagementClient(credential, settings.azure_subscription_id)
        for vm in compute.virtual_machines.list(settings.azure_resource_group):
            tags = vm.tags or {}
            if tags.get("labforge") != "true":
                continue
            session_id = tags.get("session_id")
            if not session_id:
                continue
            with SessionLocal() as db:
                session = db.scalar(
                    select(LabSession).where(LabSession.id == session_id)
                )
                orphaned = session is None or session.status in {
                    "ended",
                    "ending",
                    "failed",
                }
            if orphaned:
                delete_lab_vm(session_id, settings.azure_resource_group)
                removed += 1
    finally:
        credential.close()
    return removed


def maintain_warm_pool(course_id: str | None = None) -> int:
    # Pool maintenance is implementation-ready but defaults to zero to prevent
    # development subscriptions from paying for idle Windows compute.
    for course in load_courses():
        if course_id and course["id"] != course_id:
            continue
        if int(course.get("warm_pool_size", 0)) > 0:
            return 0
    return 0

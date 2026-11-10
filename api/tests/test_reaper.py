from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

from ops.reap_vms import (
    TARGET_RESOURCE_GROUP,
    ResourceRef,
    delete_resources,
    select_resources_to_delete,
    select_vms_to_delete,
)

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


def _resource(
    kind: str,
    name: str,
    *,
    session_id: str | None = "session-1",
    age: timedelta = timedelta(minutes=5),
    tagged: bool = True,
    resource_group: str = TARGET_RESOURCE_GROUP,
    **attributes: object,
) -> SimpleNamespace:
    resource_id = (
        f"/subscriptions/sub/resourceGroups/{resource_group}/providers/"
        f"Microsoft.{kind}/{name}"
    )
    tags = {"created_at": (NOW - age).isoformat()}
    if tagged:
        tags["labforge"] = "true"
    if session_id:
        tags["session_id"] = session_id
    return SimpleNamespace(
        id=resource_id,
        name=name,
        type=f"Microsoft.{kind}",
        tags=tags,
        **attributes,
    )


def test_vm_selection_applies_age_and_ignores_out_of_scope_resources() -> None:
    old_vm = _resource("Compute/virtualMachines", "old", age=timedelta(minutes=241))
    wrong_tag_vm = _resource("Compute/virtualMachines", "untagged", tagged=False)
    wrong_group_vm = _resource(
        "Compute/virtualMachines",
        "wrong-group",
        resource_group="rg-other",
        age=timedelta(minutes=500),
    )
    recent_vm = _resource("Compute/virtualMachines", "recent")

    selected = select_vms_to_delete(
        [old_vm, wrong_tag_vm, wrong_group_vm, recent_vm],
        {},
        NOW,
        120,
        db_available=False,
    )

    assert selected == [old_vm]


def test_vm_selection_handles_ended_failed_missing_and_grace_period() -> None:
    ended_vm = _resource("Compute/virtualMachines", "ended", session_id="ended")
    failed_vm = _resource("Compute/virtualMachines", "failed", session_id="failed")
    missing_old_vm = _resource(
        "Compute/virtualMachines",
        "missing-old",
        session_id="missing-old",
        age=timedelta(minutes=16),
    )
    missing_recent_vm = _resource(
        "Compute/virtualMachines",
        "missing-recent",
        session_id="missing-recent",
    )
    active_vm = _resource("Compute/virtualMachines", "active", session_id="active")

    selected = select_vms_to_delete(
        [ended_vm, failed_vm, missing_old_vm, missing_recent_vm, active_vm],
        {"ended": "ended", "failed": "failed", "active": "ready"},
        NOW,
        120,
    )

    assert selected == [ended_vm, failed_vm, missing_old_vm]


def test_db_unavailable_disables_session_rules_but_keeps_age_rule() -> None:
    old_vm = _resource(
        "Compute/virtualMachines",
        "old",
        session_id="still-active",
        age=timedelta(minutes=241),
    )
    ended_vm = _resource("Compute/virtualMachines", "ended", session_id="ended")

    selected = select_vms_to_delete(
        [old_vm, ended_vm],
        {"ended": "ended"},
        NOW,
        120,
        db_available=False,
    )

    assert selected == [old_vm]


def test_selection_includes_tagged_nic_disk_and_schedule_for_ended_session() -> None:
    vm = _resource("Compute/virtualMachines", "vm-1")
    nic = _resource(
        "Network/networkInterfaces",
        "vm-1-nic",
        virtual_machine=SimpleNamespace(id=vm.id),
    )
    disk = _resource("Compute/disks", "orphan-disk", managed_by=None)
    schedule = _resource(
        "DevTestLab/schedules",
        "shutdown-computevm-vm-1",
        properties={"target_resource_id": vm.id},
    )
    selected = select_resources_to_delete(
        [vm],
        [nic],
        [disk],
        [schedule],
        {"session-1": "failed"},
        NOW,
        120,
    )

    assert [(resource.resource_type, resource.name) for resource in selected] == [
        ("schedule", "shutdown-computevm-vm-1"),
        ("vm", "vm-1"),
        ("nic", "vm-1-nic"),
        ("disk", "orphan-disk"),
    ]


def test_active_vm_nic_and_attached_disk_are_not_selected() -> None:
    vm = _resource("Compute/virtualMachines", "active-vm")
    nic = _resource(
        "Network/networkInterfaces",
        "active-nic",
        session_id="active",
        virtual_machine=SimpleNamespace(id=vm.id),
    )
    disk = _resource("Compute/disks", "active-disk", session_id="active", managed_by=vm.id)
    selected = select_resources_to_delete(
        [vm],
        [nic],
        [disk],
        [],
        {"session-1": "ready", "active": "ready"},
        NOW,
        120,
    )

    assert selected == []


def test_dry_run_and_delete_brake_never_delete_resources() -> None:
    compute = Mock()
    network = Mock()
    resource_client = Mock()
    resources = [
        ResourceRef("vm", f"vm-{index}", f"/resources/vm-{index}")
        for index in range(2)
    ]

    refused = delete_resources(
        resources,
        compute,
        network,
        resource_client,
        dry_run=False,
        max_delete=1,
        force=False,
    )
    preview = delete_resources(
        resources[:1],
        compute,
        network,
        resource_client,
        dry_run=True,
        max_delete=1,
        force=False,
    )

    assert refused == {"deleted": 0, "would_delete": 0, "skipped": 2, "errors": 1}
    assert preview["would_delete"] == 1
    compute.virtual_machines.begin_delete.assert_not_called()
    network.network_interfaces.begin_delete.assert_not_called()
    resource_client.resources.begin_delete_by_id.assert_not_called()

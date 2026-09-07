from app.api.v1 import automation


async def test_run_now_rejects_duplicate_click_while_lease_is_active(client, monkeypatch):
    queued = []
    monkeypatch.setattr(
        automation.run_single_automation_task,
        "delay",
        lambda *args: queued.append(args),
    )
    created = await client.post(
        "/v1/automation-settings",
        json={"jobTitles": ["Site and Events Administrator"], "locations": ["Australia"], "enabled": True},
    )
    assert created.status_code == 200
    setting_id = created.json()["id"]

    first = await client.post(f"/v1/automation-settings/{setting_id}/run-now")
    assert first.status_code == 200
    assert first.json()["status"] == "queued"
    assert len(queued) == 1

    second = await client.post(f"/v1/automation-settings/{setting_id}/run-now")
    assert second.status_code == 409
    assert len(queued) == 1

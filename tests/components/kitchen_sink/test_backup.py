"""Test the Kitchen Sink backup platform."""

from collections.abc import AsyncGenerator
from io import StringIO
from unittest.mock import patch
from uuid import UUID

import pytest

from homeassistant.components.backup import DOMAIN as BACKUP_DOMAIN, BaseBackup
from homeassistant.components.kitchen_sink import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from tests.typing import ClientSessionGenerator, WebSocketGenerator


@pytest.fixture(autouse=True)
async def backup_only() -> AsyncGenerator[None]:
    """Enable only the backup platform.

    The backup platform is not an entity platform.
    """
    with patch(
        "homeassistant.components.kitchen_sink.COMPONENTS_WITH_DEMO_PLATFORM",
        [],
    ):
        yield


@pytest.fixture(autouse=True)
async def setup_integration(hass: HomeAssistant) -> AsyncGenerator[None]:
    """Set up Kitchen Sink integration."""
    with patch("homeassistant.components.backup.is_hassio", return_value=False):
        assert await async_setup_component(hass, BACKUP_DOMAIN, {BACKUP_DOMAIN: {}})
        assert await async_setup_component(hass, DOMAIN, {DOMAIN: {}})
        await hass.async_block_till_done()
        yield


async def test_agents_info(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """Test backup agents info."""
    client = await hass_ws_client(hass)

    await client.send_json_auto_id({"type": "backup/agents/info"})
    response = await client.receive_json()

    assert response["success"]
    assert response["result"] == {
        "agents": [{"agent_id": "backup.local"}, {"agent_id": "kitchen_sink.syncer"}],
        "syncing": False,
    }


async def test_agents_list_backups(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """Test backup agents list backups."""
    client = await hass_ws_client(hass)

    await client.send_json_auto_id({"type": "backup/agents/list_backups"})
    response = await client.receive_json()

    assert response["success"]
    assert response["result"] == [
        {
            "agent_id": "kitchen_sink.syncer",
            "date": "1970-01-01T00:00:00Z",
            "id": "def456",
            "slug": "abc123",
            "size": 1234,
            "name": "Kitchen sink syncer",
            "protected": False,
        }
    ]


async def test_agents_download(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test backup agents download."""
    client = await hass_ws_client(hass)
    backup_id = "def456"
    slug = "abc123"

    await client.send_json_auto_id(
        {
            "type": "backup/agents/download",
            "slug": slug,
            "agent_id": "kitchen_sink.syncer",
            "backup_id": backup_id,
        }
    )
    response = await client.receive_json()

    assert response["success"]
    path = hass.config.path(f"tmp_backups/{slug}.tar")
    assert f"Downloading backup {backup_id} to {path}" in caplog.text


async def test_agents_upload(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    hass_ws_client: WebSocketGenerator,
    caplog: pytest.LogCaptureFixture,
    hass_supervisor_access_token: str,
) -> None:
    """Test backup agents upload."""
    ws_client = await hass_ws_client(hass, hass_supervisor_access_token)
    client = await hass_client()
    slug = "test-backup"
    test_backup = BaseBackup(
        slug=slug,
        name="Test",
        date="1970-01-01T00:00:00.000Z",
        size=0.0,
        protected=False,
    )
    uuid = UUID(int=123456)

    with (
        patch("homeassistant.components.kitchen_sink.backup.uuid4", return_value=uuid),
        patch(
            "homeassistant.components.backup.manager.BackupManager.async_get_backup",
        ) as fetch_backup,
        patch(
            "homeassistant.components.backup.manager.read_backup",
            return_value=test_backup,
        ),
    ):
        fetch_backup.return_value = test_backup
        resp = await client.post(
            "/api/backup/upload?agent_id=kitchen_sink.syncer",
            data={"file": StringIO("test")},
        )

    assert resp.status == 201
    backup_name = f"{slug}.tar"
    assert f"Uploading backup {backup_name}" in caplog.text

    with patch("homeassistant.components.kitchen_sink.backup.uuid4", return_value=uuid):
        await ws_client.send_json_auto_id({"type": "backup/agents/list_backups"})
        response = await ws_client.receive_json()

    assert response["success"]
    backup_list = response["result"]
    assert len(backup_list) == 2
    assert backup_list[1] == {
        "agent_id": "kitchen_sink.syncer",
        "date": test_backup.date,
        "id": uuid.hex,
        "slug": slug,
        "size": 0.0,
        "name": test_backup.name,
        "protected": test_backup.protected,
    }

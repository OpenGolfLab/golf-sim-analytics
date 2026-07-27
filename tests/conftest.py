"""Test-wide isolation for per-user state.

contribute.get_contributor_uuid mirrors the locked contributor id into the
per-user application-data folder, so it survives the app folder being wiped or
reinstalled elsewhere. That is exactly the behaviour a test run must not touch:
without this fixture the suite would read the developer's real id (making every
tmp_path app_dir resolve to the same contributor), and would create that file on
a machine that has never run the app.

Every test gets its own throwaway mirror instead, so an app_dir under tmp_path
starts genuinely fresh.
"""
import pytest

import contribute


@pytest.fixture(autouse=True)
def isolated_contributor_id(tmp_path_factory, monkeypatch):
    monkeypatch.setenv(contribute._ID_DIR_ENV,
                       str(tmp_path_factory.mktemp("contributor_id_mirror")))

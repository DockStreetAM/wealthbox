"""Integration tests for household member operations.

These tests hit the real Wealthbox API and are skipped unless
the WEALTHBOX_ACCESS_TOKEN (or WEALTHBOX_TOKEN) environment variable is set.

Note: The household_members endpoint (used by add_household_member /
remove_household_member) returns 404. The working approach is to link
contacts to households via update_contact with household.name.
See the wealthbox-household-linking skill for details.
"""
import os
import time

import pytest

from wealthbox import WealthBox, WealthBoxResponseError

WEALTHBOX_TOKEN = os.environ.get("WEALTHBOX_ACCESS_TOKEN") or os.environ.get("WEALTHBOX_TOKEN")
pytestmark = pytest.mark.skipif(
    not WEALTHBOX_TOKEN,
    reason="WEALTHBOX_ACCESS_TOKEN env var not set"
)


@pytest.fixture
def wb():
    return WealthBox(token=WEALTHBOX_TOKEN)


@pytest.fixture
def household_contact(wb):
    """Create a temporary household contact and clean up after the test."""
    result = wb.create_contact({
        "first_name": "TestInteg",
        "last_name": "Household",
        "contact_type": "Person"
    })
    contact_id = result["id"]
    household_name = result["name"]
    yield {"id": contact_id, "name": household_name}
    time.sleep(1)
    wb.delete_contact(contact_id)


@pytest.fixture
def member_contact(wb):
    """Create a temporary member contact and clean up after the test."""
    result = wb.create_contact({
        "first_name": "TestInteg",
        "last_name": "Member",
        "contact_type": "Person"
    })
    contact_id = result["id"]
    yield contact_id
    time.sleep(1)
    wb.delete_contact(contact_id)


class TestHouseholdLinkingIntegration:
    def test_link_contact_to_household_via_update(self, wb, household_contact, member_contact):
        """Link a contact to a household using household.name (the working approach)."""
        time.sleep(1)
        result = wb.update_contact(member_contact, {
            "household": {
                "name": household_contact["name"],
                "title": "Child"
            }
        })

        assert result.get("household") is not None
        assert result["household"]["name"] == household_contact["name"]
        assert result["household"]["title"] == "Child"

    def test_household_members_endpoint_returns_404(self, wb, household_contact):
        """Document that the household_members POST endpoint does not work."""
        time.sleep(1)
        with pytest.raises(WealthBoxResponseError):
            wb.add_household_member(household_contact["id"], 999999)

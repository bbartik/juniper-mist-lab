"""Delete everything push.py created, using state/created_objects.json as the
source of truth (never deletes by name-prefix guessing).

Dry-run by default — prints what would be deleted. Pass --yes to actually delete.
Deletes in reverse dependency order: sites, then wlans, then wlan templates,
then device profiles, then rf profiles, then site groups.
"""
import json
import os
import sys

from mist_client import MistClient

STATE_PATH = os.path.join(os.path.dirname(__file__), "..", "state", "created_objects.json")

DELETE_PLAN = [
    ("sites", lambda c, i: f"/api/v1/sites/{i}"),
    ("wlans", lambda c, i: c.org_path(f"/wlans/{i}")),
    ("wlan_templates", lambda c, i: c.org_path(f"/templates/{i}")),
    ("device_profiles", lambda c, i: c.org_path(f"/deviceprofiles/{i}")),
    ("network_templates", lambda c, i: c.org_path(f"/networktemplates/{i}")),
    ("rf_profiles", lambda c, i: c.org_path(f"/rftemplates/{i}")),
    ("site_groups", lambda c, i: c.org_path(f"/sitegroups/{i}")),
]


def main():
    if not os.path.exists(STATE_PATH):
        sys.exit(f"No state file at {STATE_PATH} — nothing tracked to delete. "
                  f"Nothing will be removed by name-guessing.")

    with open(STATE_PATH, encoding="utf-8") as f:
        state = json.load(f)

    dry_run = "--yes" not in sys.argv
    client = MistClient() if not dry_run else None

    total = 0
    for category, path_fn in DELETE_PLAN:
        items = state.get(category, {})
        for name, obj_id in items.items():
            total += 1
            if dry_run:
                print(f"[dry-run] would delete {category}: {name} ({obj_id})")
            else:
                client.delete(path_fn(client, obj_id))
                print(f"[deleted] {category}: {name} ({obj_id})")

    if dry_run:
        print(f"\n{total} objects would be deleted. Re-run with --yes to actually delete them.")
    else:
        os.remove(STATE_PATH)
        print(f"\n{total} objects deleted. {STATE_PATH} removed.")


if __name__ == "__main__":
    main()

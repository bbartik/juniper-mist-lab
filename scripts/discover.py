"""Bootstrap helper: confirms the token works and lists orgs/sites so you can
fill in MIST_ORG_ID / MIST_SITE_ID in .env. Read-only.
"""
from mist_client import MistClient


def main():
    client = MistClient()
    me = client.get("/api/v1/self")
    print(f"Authenticated as: {me.get('name')}")
    for priv in me.get("privileges", []):
        if priv.get("scope") == "org":
            print(f"  org: {priv['name']}  id: {priv['org_id']}  role: {priv['role']}")

    if client.org_id:
        print(f"\nSites in org {client.org_id}:")
        for site in client.get(client.org_path("/sites")):
            print(f"  {site['name']:40s} {site['id']}")


if __name__ == "__main__":
    main()

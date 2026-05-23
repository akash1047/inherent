#!/usr/bin/env python3
"""Weaviate schema migration script.

This script:
1. Connects to Weaviate
2. Ensures the legacy DocumentChunk collection exists (for backward compatibility)
3. Lists all existing collections
4. Verifies Weaviate connection and version

Run with: python -m scripts.migrate_weaviate
"""

import asyncio
import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from src.config.settings import Settings
from src.services.weaviate import WeaviateService

# Load environment variables
load_dotenv()


def get_weaviate_url() -> str:
    """Get Weaviate URL from environment."""
    url = os.getenv("WEAVIATE_URL")
    if not url:
        url = "http://localhost:8080"
        print(f"⚠️  WEAVIATE_URL not set, using default: {url}")
    return url


async def run_weaviate_migration():
    """Run the Weaviate schema migration."""
    weaviate_url = get_weaviate_url()

    print("🔄 Starting Weaviate migration...")
    print(f"📍 Weaviate URL: {weaviate_url}")

    # Create settings object
    settings = Settings(
        DATABASE_URL=os.getenv(
            "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/knowledge_base"
        ),
        WEAVIATE_URL=weaviate_url,
        WEAVIATE_API_KEY=os.getenv("WEAVIATE_API_KEY"),
        GCP_PROJECT_ID=os.getenv("GCP_PROJECT_ID", "dummy"),
        STORAGE_BUCKET=os.getenv("STORAGE_BUCKET", "dummy"),
        PUBSUB_SUBSCRIPTION=os.getenv("PUBSUB_SUBSCRIPTION", "dummy"),
    )

    # Initialize Weaviate service
    weaviate_service = WeaviateService(settings)

    try:
        # Connect to Weaviate
        print("\n🔌 Connecting to Weaviate...")
        weaviate_service.connect()

        if not weaviate_service.is_connected():
            print("❌ Failed to connect to Weaviate")
            return

        print("✅ Connected to Weaviate successfully")

        # Get Weaviate version info
        try:
            import requests

            meta_response = requests.get(f"{weaviate_url}/v1/meta", timeout=5)
            if meta_response.status_code == 200:
                meta = meta_response.json()
                version = meta.get("version", "unknown")
                print(f"📦 Weaviate version: {version}")
        except Exception as e:
            print(f"⚠️  Could not fetch version info: {e}")

        # Ensure legacy collection exists
        print("\n📋 Ensuring legacy collection exists...")
        weaviate_service._ensure_legacy_collection_exists()
        print("✅ Legacy collection check completed")

        # List all collections
        print("\n📚 Listing all collections...")
        try:
            all_collections = weaviate_service.client.collections.list_all()
            if all_collections:
                print(f"\n   Found {len(all_collections)} collection(s):")
                for collection_name, collection_info in all_collections.items():
                    print(f"\n   📦 Collection: {collection_name}")

                    # Get collection details
                    try:
                        collection = weaviate_service.client.collections.get(collection_name)

                        # Check if multitenancy is enabled
                        config = collection.config.get()
                        multi_tenancy = config.multi_tenancy_config
                        if multi_tenancy and multi_tenancy.enabled:
                            print("      ✓ Multi-tenancy: Enabled")

                            # List tenants
                            try:
                                tenants = collection.tenants.get()
                                if tenants:
                                    print(f"      ✓ Tenants: {len(tenants)}")
                                    for tenant_name, tenant_obj in list(tenants.items())[
                                        :5
                                    ]:  # Show first 5
                                        status = (
                                            tenant_obj.activity_status.name
                                            if tenant_obj.activity_status
                                            else "UNKNOWN"
                                        )
                                        print(f"         - {tenant_name}: {status}")
                                    if len(tenants) > 5:
                                        print(f"         ... and {len(tenants) - 5} more tenants")
                                else:
                                    print("      ✓ Tenants: 0 (none created yet)")
                            except Exception as e:
                                print(f"      ⚠️  Could not list tenants: {e}")
                        else:
                            print("      - Multi-tenancy: Disabled")

                        # Get object count
                        try:
                            # Try to get total from aggregate if available
                            try:
                                aggregate_result = collection.query.aggregate.over_all(
                                    total_count=True
                                )
                                count = (
                                    aggregate_result.total_count
                                    if hasattr(aggregate_result, "total_count")
                                    else "unknown"
                                )
                            except Exception:
                                count = "unknown"
                            print(f"      ✓ Objects: {count}")
                        except Exception as e:
                            print(f"      ⚠️  Could not get object count: {e}")

                    except Exception as e:
                        print(f"      ⚠️  Could not get collection details: {e}")
            else:
                print("   No collections found")
        except Exception as e:
            print(f"❌ Error listing collections: {e}")

        # List workspace collections specifically
        print("\n🏢 Workspace Collections:")
        try:
            workspace_collections = weaviate_service.list_workspace_collections()
            if workspace_collections:
                print(f"   Found {len(workspace_collections)} workspace collection(s):")
                for coll_name in workspace_collections:
                    print(f"   - {coll_name}")
            else:
                print(
                    "   No workspace collections found (will be created on first document upload)"
                )
        except Exception as e:
            print(f"⚠️  Could not list workspace collections: {e}")

        print("\n✅ Weaviate migration completed successfully!")
        print("\n💡 Note: Workspace collections and tenants are created automatically")
        print("   when documents are processed. No manual migration needed.")

    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        # Disconnect
        if weaviate_service.is_connected():
            weaviate_service.disconnect()
            print("\n🔌 Disconnected from Weaviate")


if __name__ == "__main__":
    asyncio.run(run_weaviate_migration())

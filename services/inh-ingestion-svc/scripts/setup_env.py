#!/usr/bin/env python3
"""Helper script to set up .env file with actual GCP values."""

import subprocess
import sys
from pathlib import Path


def get_gcloud_project():
    """Get current GCP project from gcloud."""
    try:
        result = subprocess.run(
            ["gcloud", "config", "get-value", "project"], capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def main():
    """Main setup function."""
    env_file = Path(__file__).parent.parent / ".env"
    env_example = Path(__file__).parent.parent / ".env.example"

    if not env_file.exists():
        if env_example.exists():
            print("📋 Creating .env from .env.example...")
            env_file.write_text(env_example.read_text())
        else:
            print("❌ .env.example not found!")
            sys.exit(1)

    # Read current .env
    env_content = env_file.read_text()

    # Get GCP project ID
    gcp_project = get_gcloud_project()

    if gcp_project:
        print(f"✅ Found GCP project: {gcp_project}")

        # Update GCP_PROJECT_ID if it's a placeholder
        if "your-project-id" in env_content or "GCP_PROJECT_ID=your-project-id" in env_content:
            env_content = env_content.replace(
                "GCP_PROJECT_ID=your-project-id", f"GCP_PROJECT_ID={gcp_project}"
            )
            # Also update in PUBSUB paths
            env_content = env_content.replace("projects/your-project-id", f"projects/{gcp_project}")
            print(f"✅ Updated GCP_PROJECT_ID to: {gcp_project}")
        else:
            print("ℹ️  GCP_PROJECT_ID already set")
    else:
        print("⚠️  Could not detect GCP project from gcloud")
        print("   Please set GCP_PROJECT_ID manually in .env")
        print("   Or run: gcloud config set project YOUR_PROJECT_ID")

    # Write updated .env
    env_file.write_text(env_content)
    print(f"\n✅ .env file updated: {env_file}")
    print("\n💡 Next steps:")
    print("   1. Review and update other values in .env if needed")
    print(
        "   2. Create Pub/Sub topic: gcloud pubsub topics create document-upload --project=$(gcloud config get-value project)"
    )
    print("   3. Run: make test-pubsub")


if __name__ == "__main__":
    main()

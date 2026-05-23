#!/usr/bin/env python3
"""Test script to publish a message to Cloud Pub/Sub."""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog

from src.config.settings import get_settings
from src.services.mq import MQService
from src.utils.logger import setup_logging

logger = structlog.get_logger(__name__)


async def publish_test_message():
    """Publish a test message to Pub/Sub."""
    settings = get_settings()
    setup_logging(settings.log_level)

    # Validate project ID is not a placeholder
    if (
        "your-project" in settings.gcp_project_id.lower()
        or "example" in settings.gcp_project_id.lower()
    ):
        logger.error(
            "❌ Invalid GCP Project ID",
            project_id=settings.gcp_project_id,
            hint="Please update GCP_PROJECT_ID in your .env file with your actual GCP project ID",
        )
        logger.info(
            "💡 To find your project ID:",
            command1="gcloud config get-value project",
            command2="Or check: https://console.cloud.google.com/iam-admin/settings",
        )
        sys.exit(1)

    logger.info("Publishing test message to Pub/Sub", project=settings.gcp_project_id)

    # Create MQ service
    mq_service = MQService(settings)

    try:
        # Connect to Pub/Sub
        await mq_service.connect()

        # Extract topic name from PUBSUB_TOPIC or use default
        if settings.pubsub_topic:
            # Extract topic name from full path: projects/PROJECT_ID/topics/TOPIC_NAME
            topic_name = settings.pubsub_topic.split("/")[-1]
        else:
            # Default topic name
            topic_name = "document-upload"
            logger.warning("PUBSUB_TOPIC not set, using default", topic=topic_name)

        # Create test message
        test_message = {
            "id": "test-message-001",
            "file_location": "gs://test-bucket/test-document.pdf",
            "metadata_location": "gs://test-bucket/test-metadata.json",
            "workspace_id": "test-workspace-123",
            "user_id": "test-user-456",
            "timestamp": "2026-01-02T10:00:00Z",
        }

        logger.info("Publishing message", topic=topic_name, message=test_message)

        # Publish message (will attempt to create topic if it doesn't exist)
        try:
            await mq_service.publish(topic_name, test_message, create_topic_if_not_exists=True)
            logger.info("✅ Message published successfully!")
        except RuntimeError as e:
            logger.error("❌ Failed to publish message", error=str(e))
            logger.info(
                "💡 Tip: Create the topic first with:",
                command=f"gcloud pubsub topics create {topic_name} --project={settings.gcp_project_id}",
            )
            raise
        except Exception as e:
            error_str = str(e)
            if "403" in error_str or "PermissionDenied" in error_str:
                logger.error(
                    "❌ Permission denied. You need Pub/Sub Admin or Editor role.", error=error_str
                )
                logger.info(
                    "💡 Solutions:",
                    option1=f"1. Create topic manually: gcloud pubsub topics create {topic_name} --project={settings.gcp_project_id}",
                    option2="2. Grant yourself Pub/Sub Admin role",
                    option3="3. Use a service account with proper permissions",
                )
            else:
                logger.error("❌ Failed to publish message", error=error_str)
            raise

    except Exception as e:
        logger.error("Failed to publish message", error=str(e), exc_info=True)
        sys.exit(1)
    finally:
        mq_service.disconnect()


if __name__ == "__main__":
    asyncio.run(publish_test_message())

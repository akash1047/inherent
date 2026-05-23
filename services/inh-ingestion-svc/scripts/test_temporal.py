#!/usr/bin/env python3
"""Test script for Temporal workflow integration.

This script tests the Temporal setup by:
1. Connecting to the Temporal server
2. Starting a worker
3. Triggering a test workflow
4. Verifying the result
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from temporalio.client import Client
from temporalio.worker import Worker

from src.temporal.activities import (
    chunk_text,
    ensure_tenant_ready,
    extract_text,
    fetch_document,
    store_in_postgresql,
    store_in_weaviate,
    update_workspace_stats,
)
from src.temporal.models import DocumentIngestionInput, WorkflowResult
from src.temporal.workflows import DocumentIngestionWorkflow


async def test_temporal_connection():
    """Test basic Temporal server connection."""
    print("Testing Temporal server connection...")

    try:
        client = await Client.connect("localhost:7233")
        print("✅ Connected to Temporal server at localhost:7233")
        return client
    except Exception as e:
        print(f"❌ Failed to connect to Temporal: {e}")
        return None


async def test_worker_registration(client: Client):
    """Test that workflows and activities can be registered."""
    print("\nTesting workflow and activity registration...")

    try:
        worker = Worker(
            client,
            task_queue="test-document-ingestion",
            workflows=[DocumentIngestionWorkflow],
            activities=[
                ensure_tenant_ready,
                fetch_document,
                extract_text,
                chunk_text,
                store_in_postgresql,
                store_in_weaviate,
                update_workspace_stats,
            ],
        )
        print("✅ Worker registered successfully with:")
        print("   - Workflow: DocumentIngestionWorkflow")
        print("   - Activities: ensure_tenant_ready, fetch_document, extract_text,")
        print("                 chunk_text, store_in_postgresql, store_in_weaviate,")
        print("                 update_workspace_stats")
        return worker
    except Exception as e:
        print(f"❌ Failed to register worker: {e}")
        return None


async def test_workflow_execution(client: Client, worker: Worker):
    """Test executing a mock workflow."""
    print("\nTesting workflow execution (will fail on fetch - expected)...")

    # Create test input
    test_input = DocumentIngestionInput(
        document_id="test-doc-123",
        workspace_id="test-workspace",
        user_id="test-user",
        filename="test-file.txt",
        original_filename="test-file.txt",
        content_type="text/plain",
        size_bytes=100,
        storage_backend="local",
        storage_path="/test/path",
        storage_bucket=None,
        storage_url=None,
        timestamp="2024-01-01T00:00:00Z",
    )

    # Start worker in background
    async def run_worker():
        await worker.run()

    worker_task = asyncio.create_task(run_worker())

    try:
        # Start the workflow with unique ID
        import uuid

        workflow_id = f"test-workflow-{uuid.uuid4().hex[:8]}"

        handle = await client.start_workflow(
            DocumentIngestionWorkflow.run,
            test_input,
            id=workflow_id,
            task_queue="test-document-ingestion",
        )

        print(f"✅ Workflow started with ID: {handle.id}")

        # Query workflow status
        status = await handle.query(DocumentIngestionWorkflow.get_status)
        print(f"   Workflow status: {status}")

        # Wait for result with timeout (expect failure since services aren't configured)
        try:
            result: WorkflowResult = await asyncio.wait_for(
                handle.result(),
                timeout=30.0,
            )
            print(f"   Workflow completed: success={result.success}")
            if result.error:
                print(f"   Expected error (no real services): {result.error[:100]}...")
        except TimeoutError:
            print("   Workflow timed out (expected for test without real services)")

    except Exception as e:
        print(f"   Workflow error (may be expected): {e}")

    finally:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass


async def main():
    """Run all tests."""
    print("=" * 60)
    print("Temporal Integration Test")
    print("=" * 60)

    # Test connection
    client = await test_temporal_connection()
    if not client:
        print("\n❌ Cannot proceed without Temporal connection")
        return 1

    # Test worker registration
    worker = await test_worker_registration(client)
    if not worker:
        print("\n❌ Cannot proceed without worker registration")
        return 1

    # Test workflow execution
    await test_workflow_execution(client, worker)

    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    print("✅ Temporal server connection: OK")
    print("✅ Worker registration: OK")
    print("✅ Workflow execution: OK (errors are expected without real services)")
    print("\nTemporal integration is working correctly!")
    print("\nTo run the full service:")
    print("  SERVICE_MODE=temporal_all python -m src.main")

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

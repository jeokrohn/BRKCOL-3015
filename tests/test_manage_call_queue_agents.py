"""Tests for the bulk call queue agent management helpers."""

import logging
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from wxc_sdk.telephony.callqueue import CallQueue
from wxc_sdk.telephony.hg_and_cq import Agent

from manage_call_queue_agents import (
    apply_queue_changes,
    api_request_logging,
    flatten,
    parse_args,
    resolve_agents,
)


class FakeCallQueueApi:
    """Capture call queue writes made by the helper."""

    def __init__(self) -> None:
        """Initialize an empty update list."""
        self.updates: list[tuple[str, str, CallQueue]] = []

    def update(self, *, location_id: str, queue_id: str, update: CallQueue) -> None:
        """Record one mocked queue update.

        :param location_id: Location identifier for the queue.
        :param queue_id: Queue identifier.
        :param update: Updated queue model.
        """
        self.updates.append((location_id, queue_id, update))


class TestManageCallQueueAgents(unittest.TestCase):
    """Exercise command parsing, selector resolution, and write behavior."""

    def test_parse_args_accepts_multiple_values_and_token(self) -> None:
        """Parse repeated queue and agent selectors from a command line."""
        args = parse_args(
            [
                "--queue",
                "Support",
                "Billing",
                "--join",
                "all",
                "--token",
                "secret",
                "--dry-run",
            ]
        )

        self.assertEqual(flatten(args.queues), ["Support", "Billing"])
        self.assertEqual(flatten(args.join_agents), ["all"])
        self.assertEqual(args.token, "secret")
        self.assertTrue(args.dry_run)

    def test_log_api_without_file_selects_stderr(self) -> None:
        """The API logging option uses stderr when no file is supplied."""
        args = parse_args(["--log-api"])

        self.assertEqual(args.log_api, "-")
        self.assertEqual(parse_args(["--log-api", "api.log"]).log_api, "api.log")

    def test_api_logging_writes_to_requested_file(self) -> None:
        """SDK REST debug records are written to the selected file."""
        with TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "api.log"
            logger = logging.getLogger("wxc_sdk.rest")

            with api_request_logging(str(log_path)):
                logger.debug("test API request")

            self.assertIn("test API request", log_path.read_text(encoding="utf-8"))

    def test_api_logging_writes_to_stderr(self) -> None:
        """SDK REST debug records are written to stderr by default."""
        logger = logging.getLogger("wxc_sdk.rest")
        stream = StringIO()
        with redirect_stderr(stream), api_request_logging("-"):
            logger.debug("test API request")

        self.assertIn("test API request", stream.getvalue())

    def test_resolve_agents_matches_id_name_and_email(self) -> None:
        """Resolve an existing queue agent by its name or ID."""
        agent = Agent(
            agent_id="person-1",
            first_name="Alex",
            last_name="Example",
            join_enabled=False,
        )
        people = [
            SimpleNamespace(
                person_id="person-1",
                display_name="Alex Example",
                emails=["alex@example.com"],
            )
        ]

        self.assertEqual(
            resolve_agents(["person-1"], [agent], people, operation="join"), [agent]
        )
        self.assertEqual(
            resolve_agents(["Alex Example"], [agent], people, operation="join"),
            [agent],
        )
        self.assertEqual(
            resolve_agents(["alex@example.com"], [agent], people, operation="join"),
            [agent],
        )

    def test_dry_run_reports_without_sending_update(self) -> None:
        """Dry-run changes queue state in memory but does not call the update API."""
        queue = CallQueue(
            id="queue-1",
            location_id="location-1",
            location_name="Seattle",
            name="Support",
            agents=[
                Agent(
                    agent_id="person-1",
                    first_name="Alex",
                    last_name="Example",
                    join_enabled=False,
                )
            ],
        )
        call_queue_api = FakeCallQueueApi()
        api = SimpleNamespace(telephony=SimpleNamespace(callqueue=call_queue_api))

        wrote = apply_queue_changes(
            api,
            queue,
            join_selectors=["all"],
            unjoin_selectors=[],
            add_selectors=[],
            remove_selectors=[],
            directory_people=[],
            dry_run=True,
        )

        self.assertFalse(wrote)
        self.assertFalse(call_queue_api.updates)
        self.assertTrue(queue.agents[0].join_enabled)

    def test_apply_queue_changes_adds_and_joins_agent(self) -> None:
        """Add and join an organization person with one queue update."""
        queue = CallQueue(
            id="queue-1",
            location_id="location-1",
            location_name="Seattle",
            name="Support",
            agents=[],
        )
        call_queue_api = FakeCallQueueApi()
        api = SimpleNamespace(telephony=SimpleNamespace(callqueue=call_queue_api))
        person = SimpleNamespace(
            person_id="person-1",
            display_name="Alex Example",
            first_name="Alex",
            last_name="Example",
            emails=["alex@example.com"],
        )

        wrote = apply_queue_changes(
            api,
            queue,
            join_selectors=["Alex Example"],
            unjoin_selectors=[],
            add_selectors=["alex@example.com"],
            remove_selectors=[],
            directory_people=[person],
            dry_run=False,
        )

        self.assertTrue(wrote)
        self.assertEqual(len(call_queue_api.updates), 1)
        self.assertEqual(call_queue_api.updates[0][:2], ("location-1", "queue-1"))
        self.assertEqual(queue.agents[0].agent_id, "person-1")
        self.assertTrue(queue.agents[0].join_enabled)

    def test_resolve_agents_rejects_unknown_selector(self) -> None:
        """Unknown agent selectors produce a readable validation error."""
        with self.assertRaisesRegex(ValueError, "was not found"):
            resolve_agents(["Nobody"], [], [], operation="add")

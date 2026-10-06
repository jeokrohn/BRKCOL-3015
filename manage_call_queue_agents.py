#!/usr/bin/env python
"""Read and bulk-update Webex Calling call queue agent membership and join state.

This script is created using ChatGPT and is intended for demonstration purposes. It may not be suitable for production
use without further testing and validation.

Prompt:

    Create a script to bulk Read/update call queue agent join states. The script should accept parameters to:
    - define a location by name. If missing the script operates on all locations
    - define one or more queue names
    - list agents that should join the given queues. Can be "all" to act on all agents
    - list agents to unjoin from given queue(s). Can be "all" to act on all agents
    - list agents to add to queues
    - list agents to remove from queues
    - set "dry-run" mode. The script executes normally but does not apply write operations
    - pass a token via the command line. If no token is given, then a token in the WEBEX_TOKEN environment variable is
      used

    Add a CLI option to enable logging of API requests to stderr (default) or a given file.

"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager

from dotenv import load_dotenv
from wxc_sdk import WebexSimpleApi
from wxc_sdk.telephony.callqueue import CallQueue
from wxc_sdk.telephony.hg_and_cq import Agent


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line options.

    :param argv: Optional argument sequence; defaults to the process arguments.
    :returns: Parsed command-line options.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Read call queue agents and optionally update their join state or "
            "queue membership. Agent selectors may be Webex IDs, email addresses, "
            "or exact display names."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--location", help="Location name; omit to search every location"
    )
    parser.add_argument(
        "--queue",
        action="append",
        nargs="+",
        dest="queues",
        metavar="NAME",
        help="Call queue name (repeat the option or provide multiple names)",
    )
    parser.add_argument(
        "--join",
        action="append",
        nargs="+",
        dest="join_agents",
        metavar="AGENT",
        help=(
            'Join these agents to the selected queues; use "all" '
            "for every current member"
        ),
    )
    parser.add_argument(
        "--unjoin",
        action="append",
        nargs="+",
        dest="unjoin_agents",
        metavar="AGENT",
        help=(
            'Unjoin these agents from the selected queues; use "all" '
            "for every current member"
        ),
    )
    parser.add_argument(
        "--add",
        action="append",
        nargs="+",
        dest="add_agents",
        metavar="AGENT",
        help="Add these agents to the selected queues",
    )
    parser.add_argument(
        "--remove",
        action="append",
        nargs="+",
        dest="remove_agents",
        metavar="AGENT",
        help="Remove these agents from the selected queues",
    )
    parser.add_argument("--token", help="Webex access token (overrides WEBEX_TOKEN)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read and report changes without sending write operations",
    )
    parser.add_argument(
        "--log-api",
        nargs="?",
        const="-",
        default=None,
        metavar="FILE",
        help="Log Webex API request/response details to stderr or FILE",
    )
    return parser.parse_args(argv)


@contextmanager
def api_request_logging(destination: str | None) -> Iterator[None]:
    """Temporarily enable detailed Webex REST request logging.

    :param destination: Log file path, ``-`` for stderr, or None to disable logging.
    :yields: Nothing; logging is configured for the duration of the context.
    :raises OSError: If the requested log file cannot be opened.
    """
    if destination is None:
        yield
        return

    logger = logging.getLogger("wxc_sdk.rest")
    handler = (
        logging.StreamHandler(sys.stderr)
        if destination == "-"
        else logging.FileHandler(destination, encoding="utf-8")
    )
    original_level = logger.level
    original_propagate = logger.propagate
    handler.setLevel(logging.DEBUG)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.addHandler(handler)
    try:
        yield
    finally:
        logger.removeHandler(handler)
        logger.setLevel(original_level)
        logger.propagate = original_propagate
        handler.close()


def flatten(values: list[list[str]] | None) -> list[str]:
    """Flatten repeated list-valued command-line arguments.

    :param values: Values returned by argparse for an append/nargs option.
    :returns: A flat list with surrounding whitespace removed and duplicates omitted.
    """
    if not values:
        return []
    flattened = (value.strip() for group in values for value in group if value.strip())
    return list(dict.fromkeys(flattened))


def person_name(person: object) -> str:
    """Return a person's display name from common SDK fields.

    :param person: A Webex person or call queue agent model.
    :returns: Display name, or an empty string if no name is available.
    """
    display_name = getattr(person, "display_name", None) or getattr(
        person, "displayName", None
    )
    if display_name:
        return str(display_name)
    first_name = getattr(person, "first_name", None) or ""
    last_name = getattr(person, "last_name", None) or ""
    return f"{first_name} {last_name}".strip()


def person_emails(person: object) -> set[str]:
    """Return normalized email addresses exposed by a Webex SDK model.

    :param person: A Webex person model.
    :returns: Lowercase email addresses.
    """
    emails = getattr(person, "emails", None) or []
    email = getattr(person, "email", None)
    if email:
        emails = [*emails, email]
    return {str(value).strip().casefold() for value in emails if value}


def selector_matches(
    selector: str, agent: Agent, directory_people: Iterable[object]
) -> bool:
    """Check whether a selector identifies an agent.

    :param selector: Webex ID, email address, or exact display name.
    :param agent: Queue agent being matched.
    :param directory_people: People directory models, if the agent is a person.
    :returns: True when the selector matches the agent.
    """
    normalized = selector.casefold()
    if selector == agent.agent_id:
        return True
    if person_name(agent).casefold() == normalized:
        return True
    for person in directory_people:
        if getattr(person, "person_id", None) != agent.agent_id:
            continue
        return (
            normalized in person_emails(person)
            or person_name(person).casefold() == normalized
        )
    return False


def resolve_agents(
    selectors: list[str],
    candidates: list[Agent],
    directory_people: list[object],
    *,
    operation: str,
) -> list[Agent]:
    """Resolve agent selectors against a queue or organization directory.

    :param selectors: Agent IDs, emails, or exact names to resolve.
    :param candidates: Agents currently associated with the queue.
    :param directory_people: People available to add to the queue.
    :param operation: Operation name included in validation errors.
    :returns: Matching agents, in selector order without duplicates.
    :raises ValueError: If an agent is missing or a selector is ambiguous.
    """
    resolved: list[Agent] = []
    for selector in selectors:
        matches = [
            agent
            for agent in candidates
            if selector_matches(selector, agent, directory_people)
        ]
        if not matches:
            people_matches = [
                person
                for person in directory_people
                if selector.casefold() == person_name(person).casefold()
                or selector.casefold() in person_emails(person)
                or selector == getattr(person, "person_id", None)
            ]
            matches.extend(
                Agent(
                    agent_id=str(getattr(person, "person_id")),
                    first_name=getattr(person, "first_name", None),
                    last_name=getattr(person, "last_name", None),
                    join_enabled=True,
                )
                for person in people_matches
            )
        unique = {agent.agent_id: agent for agent in matches}
        if not unique:
            raise ValueError(f"Agent {selector!r} for {operation} was not found.")
        if len(unique) > 1:
            options = ", ".join(sorted(agent.agent_id for agent in unique.values()))
            raise ValueError(
                f"Agent selector {selector!r} is ambiguous; use a Webex ID ({options})."
            )
        agent = next(iter(unique.values()))
        if all(existing.agent_id != agent.agent_id for existing in resolved):
            resolved.append(agent)
    return resolved


def print_queue(queue: CallQueue) -> None:
    """Print a queue's agent membership and join states.

    :param queue: Queue detail model to print.
    """
    print(f"\n{queue.name} [{queue.location_name or queue.location_id}]")
    agents = queue.agents or []
    if not agents:
        print("  (no agents)")
        return
    for agent in sorted(
        agents, key=lambda item: (person_name(item).casefold(), item.agent_id)
    ):
        name = person_name(agent) or agent.agent_id
        state = "joined" if agent.join_enabled else "unjoined"
        print(f"  {name}  {agent.agent_id}  {state}")


def apply_queue_changes(
    api: WebexSimpleApi,
    queue: CallQueue,
    *,
    join_selectors: list[str],
    unjoin_selectors: list[str],
    add_selectors: list[str],
    remove_selectors: list[str],
    directory_people: list[object],
    dry_run: bool,
) -> bool:
    """Apply requested queue membership and join-state changes.

    :param api: Authenticated Webex API client.
    :param queue: Detailed call queue model, mutated in memory as needed.
    :param join_selectors: Selectors to mark joined; ``all`` targets current members.
    :param unjoin_selectors: Selectors to mark unjoined; ``all`` targets current
        members.
    :param add_selectors: Selectors to add to the queue.
    :param remove_selectors: Selectors to remove from the queue.
    :param directory_people: People directory used for selector resolution.
    :param dry_run: When true, describe updates without sending writes.
    :returns: True if a write was needed and sent.
    :raises ValueError: If requested selectors cannot be resolved.
    """
    current_agents = list(queue.agents or [])
    add_agents = resolve_agents(
        add_selectors, current_agents, directory_people, operation="add"
    )
    remove_agents = resolve_agents(
        remove_selectors, current_agents, directory_people, operation="remove"
    )

    by_id = {agent.agent_id: agent for agent in current_agents}
    changes: list[str] = []
    for agent in add_agents:
        if agent.agent_id not in by_id:
            agent.join_enabled = True
            current_agents.append(agent)
            by_id[agent.agent_id] = agent
            changes.append(f"add {person_name(agent) or agent.agent_id}")

    join_all = any(selector.casefold() == "all" for selector in join_selectors)
    unjoin_all = any(selector.casefold() == "all" for selector in unjoin_selectors)
    join_agents = current_agents if join_all else resolve_agents(
        join_selectors, current_agents, directory_people, operation="join"
    )
    unjoin_agents = current_agents if unjoin_all else resolve_agents(
        unjoin_selectors, current_agents, directory_people, operation="unjoin"
    )
    for agent in join_agents:
        current = by_id.get(agent.agent_id)
        if current is None:
            raise ValueError(
                f"Agent {person_name(agent)!r} must be added before it can be joined."
            )
        if current.join_enabled is not True:
            current.join_enabled = True
            changes.append(f"join {person_name(current) or current.agent_id}")
    for agent in unjoin_agents:
        current = by_id.get(agent.agent_id)
        if current is None:
            raise ValueError(
                f"Agent {person_name(agent)!r} must be added before it can be unjoined."
            )
        if current.join_enabled is not False:
            current.join_enabled = False
            changes.append(f"unjoin {person_name(current) or current.agent_id}")

    removed_ids = {agent.agent_id for agent in remove_agents}
    for agent in remove_agents:
        if agent.agent_id in by_id:
            changes.append(
                f"remove {person_name(by_id[agent.agent_id]) or agent.agent_id}"
            )
    if removed_ids:
        current_agents = [
            agent for agent in current_agents if agent.agent_id not in removed_ids
        ]
    queue.agents = current_agents

    if not changes:
        print("  No changes needed.")
        return False
    prefix = "Would " if dry_run else "Will "
    print(f"  {prefix}{'; '.join(changes)}")
    if dry_run:
        return False
    api.telephony.callqueue.update(
        location_id=queue.location_id,
        queue_id=queue.id,
        update=queue,
    )
    return True


def main(argv: Sequence[str] | None = None) -> int:
    """Run queue reads and requested updates.

    :param argv: Optional command-line arguments.
    :returns: Process exit code, with zero indicating success.
    """
    load_dotenv()
    args = parse_args(argv)
    token = args.token or os.getenv("WEBEX_TOKEN")
    if not token:
        print("Error: pass --token or set WEBEX_TOKEN.", file=sys.stderr)
        return 2

    queue_names = flatten(args.queues)
    join_selectors = flatten(args.join_agents)
    unjoin_selectors = flatten(args.unjoin_agents)
    add_selectors = flatten(args.add_agents)
    remove_selectors = flatten(args.remove_agents)
    has_action = any(
        (join_selectors, unjoin_selectors, add_selectors, remove_selectors)
    )
    if has_action and not queue_names:
        print(
            "Error: specify at least one --queue when requesting changes.",
            file=sys.stderr,
        )
        return 2
    if any(
        selector.casefold() == "all" for selector in add_selectors + remove_selectors
    ):
        print(
            'Error: "all" is supported only for --join and --unjoin.',
            file=sys.stderr,
        )
        return 2

    try:
        with api_request_logging(args.log_api):
            with WebexSimpleApi(tokens=token) as api:
                locations = list(api.locations.list())
                if args.location:
                    location_matches = [
                        loc
                        for loc in locations
                        if (loc.name or "").casefold() == args.location.casefold()
                    ]
                    if len(location_matches) != 1:
                        names = ", ".join(loc.name or "(unnamed)" for loc in locations)
                        raise ValueError(
                            f"Location {args.location!r} was not found or is ambiguous. "
                            f"Available locations: {names}"
                        )
                    location_ids = {location_matches[0].location_id}
                else:
                    location_ids = {location.location_id for location in locations}

                queues = [
                    queue
                    for queue in api.telephony.callqueue.list()
                    if queue.location_id in location_ids
                ]
                if queue_names:
                    requested = {name.casefold() for name in queue_names}
                    queues = [
                        queue
                        for queue in queues
                        if (queue.name or "").casefold() in requested
                    ]
                    found_names = {(queue.name or "").casefold() for queue in queues}
                    missing = [
                        name for name in queue_names if name.casefold() not in found_names
                    ]
                    if missing:
                        raise ValueError(
                            "Call queue(s) not found in the selected location scope: "
                            f"{', '.join(missing)}"
                        )
                if not queues:
                    print("No call queues found.")
                    return 0

                directory_people = list(api.people.list()) if add_selectors else []
                dry_run_note = " Dry run: no writes will be sent." if args.dry_run else ""
                print(f"Found {len(queues)} call queue(s).{dry_run_note}")
                for summary in queues:
                    detail = api.telephony.callqueue.details(
                        location_id=summary.location_id,
                        queue_id=summary.id,
                    )
                    print_queue(detail)
                    if has_action:
                        apply_queue_changes(
                            api,
                            detail,
                            join_selectors=join_selectors,
                            unjoin_selectors=unjoin_selectors,
                            add_selectors=add_selectors,
                            remove_selectors=remove_selectors,
                            directory_people=directory_people,
                            dry_run=args.dry_run,
                        )
                        if not args.dry_run:
                            print_queue(detail)
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

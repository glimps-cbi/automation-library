import datetime
import time
from functools import cached_property

import orjson
from requests.exceptions import HTTPError
from sekoia_automation.connector import Connector, DefaultConnectorConfiguration
from sekoia_automation.storage import PersistentJSON
from urllib3.exceptions import HTTPError as BaseHTTPError

from lacework_module.base import LaceworkModule
from lacework_module.client import LaceworkApiClient
from lacework_module.client.auth import LaceworkAuthentication
from lacework_module.metrics import EVENTS_LAG, FORWARD_EVENTS_DURATION, INCOMING_EVENTS, OUTCOMING_EVENTS


class LaceworkConfiguration(DefaultConnectorConfiguration):
    frequency: int = 60
    exclude_types: list[str] | None = None
    chunk_size: int = 1000


class LaceworkEventsTrigger(Connector):
    """
    The Lacework trigger reads the next batch of messages and forward it to the playbook run.

    Quick notes
    - Authentication on API is OAuth2 and access token expiration is handled.
    - A margin of 300sec is added to the expiration date of oauth2 token.

    """
    module: LaceworkModule
    configuration: LaceworkConfiguration

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.context = PersistentJSON("context.json", self._data_path)

    @property
    def cursor(self) -> str | None:
        with self.context as cache:
            return cache.get("cursor")

    @cursor.setter
    def cursor(self, cursor: str):
        with self.context as cache:
            cache["cursor"] = cursor

    @cached_property
    def pagination_limit(self):
        return max(self.configuration.chunk_size, 1000)

    @cached_property
    def client(self):
        auth = LaceworkAuthentication(
            lacework_url=self.module.configuration.lacework_url,
            access_key=self.module.configuration.access_key,
            secret_key=self.module.configuration.secret_key
        )
        return LaceworkApiClient(base_url=self.module.configuration.lacework_url, auth=auth)

    def run(self):
        self.log(message="Lacework Events Trigger has started", level="info")

        try:
            while self.running:
                start = time.time()

                try:
                    self.forward_next_batches()
                except (HTTPError, BaseHTTPError) as ex:
                    self.log_exception(ex, message="Failed to get next batch of events")
                except Exception as ex:
                    self.log_exception(ex, message="An unknown exception occurred")
                    raise

                # compute the duration of the last events fetching
                duration = int(time.time() - start)
                FORWARD_EVENTS_DURATION.labels(intake_key=self.configuration.intake_key).observe(duration)

                # Compute the remaining sleeping time
                delta_sleep = self.configuration.frequency - duration
                # if greater than 0, sleep
                if delta_sleep > 0:
                    time.sleep(delta_sleep)
        finally:
            self.log(message="Lacework Events Trigger has stopped", level="info")

    def get_next_events(self, cursor: str | None) -> dict | None:
        # set parameters
        parameters = {
            "limit": self.pagination_limit,
        }

        # if defined, set the cursor
        if cursor:
            parameters["cursor"] = cursor
        # otherwise, get events starting from the last 5 minutes
        else:
            parameters["startTime"] = int(time.time()) - 300

        # Get the events
        response = self.client.list_alerts(parameters=parameters)

        # Something failed
        if not response.ok:
            self.log(
                message=(
                    "Request on Lacework Central API to fetch events of failed with"
                    f" status {response.status_code} - {response.reason}"
                ),
                level="error",
            )

            return None

        return response.json()

    def _get_most_recent_timestamp_from_items(self, items: list[dict]):
        def _extract_timestamp(item: dict) -> float:
            RFC3339_STRICT_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
            return datetime.datetime.strptime(item["startTime"], RFC3339_STRICT_FORMAT).timestamp()

        latest_message = max(items, key=lambda item: item["startTime"])
        latest_message_timestamp = _extract_timestamp(latest_message)
        return latest_message_timestamp

    def forward_next_batches(self) -> None:
        """
        Successively queries the Lacework Central API while more are available
        and the current batch is not too big.
        """
        has_more_messages = True
        cursor = self.cursor

        messages = []
        while has_more_messages and self.running:
            has_more_messages = False

            batch = self.get_next_events(cursor)
            if batch is None:
                break

            if batch.get("content", {}).get("paging", {}).get("urls", {}).get("nextPage") != None:
                has_more_messages = True,
                cursor = max(item.get("startTime") for item in self.get_next_events(cursor).data)

            items = batch.get("data", [])
            if len(items) > 0:
                most_recent_timestamp_seen = self._get_most_recent_timestamp_from_items(items)
                events_lag = int(time.time() - most_recent_timestamp_seen)
                EVENTS_LAG.labels(intake_key=self.configuration.intake_key).set(events_lag)
                INCOMING_EVENTS.labels(intake_key=self.configuration.intake_key).inc(len(items))

            for message in items:
                messages.append(orjson.dumps(message).decode("utf-8"))

            if len(messages) > self.pagination_limit:
                self.log(message=f"Sending a batch of {len(messages)} messages", level="info")
                OUTCOMING_EVENTS.labels(intake_key=self.configuration.intake_key).inc(len(messages))
                self.push_events_to_intakes(events=messages)
                messages = []

        self.cursor = cursor

        if messages:
            self.log(message=f"Sending a batch of {len(messages)} messages", level="info")
            OUTCOMING_EVENTS.labels(intake_key=self.configuration.intake_key).inc(len(messages))
            self.push_events_to_intakes(events=messages)
        else:
            self.log(message="No messages to forward", level="info")
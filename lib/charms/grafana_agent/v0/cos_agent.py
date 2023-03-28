# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

r"""## Overview.

This library can be used to manage the cos_agent relation interface:

- `COSAgentProvider`: Use in machine charms that need to have a workload's metrics
  or logs scraped, or forward rule files or dashboards to Prometheus, Loki or Grafana through
  the Grafana Agent machine charm.

- `COSAgentConsumer`: Used in the Grafana Agent machine charm to manage the requirer side of
  the `cos_agent` interface.


## COSAgentProvider Library Usage

Grafana Agent machine Charmed Operator interacts with its clients using the cos_agent library.
Charms seeking to send telemetry, must do so using the `COSAgentProvider` object from
this charm library.

Using the `COSAgentProvider` object only requires instantiating it,
typically in the `__init__` method of your charm (the one which sends telemetry).

The constructor of `COSAgentProvider` has only one required and eight optional parameters:

```python
    def __init__(
        self,
        charm: CharmType,
        relation_name: str = DEFAULT_RELATION_NAME,
        metrics_endpoints: Optional[List[dict]] = None,
        metrics_rules_dir: str = "./src/prometheus_alert_rules",
        logs_rules_dir: str = "./src/loki_alert_rules",
        recurse_rules_dirs: bool = False,
        log_slots: Optional[List[str]] = None,
        dashboard_dirs: Optional[List[str]] = None,
        refresh_events: Optional[List] = None,
    ):
```

### Parameters

- `charm`: The instance of the charm that instantiates `COSAgentProvider`, typically `self`.

- `relation_name`: If your charmed operator uses a relation name other than `cos-agent` to use
    the `cos_agent` interface, this is where you have to specify that.

- `metrics_endpoints`: In this parameter you can specify the metrics endpoints that Grafana Agent
    machine Charmed Operator will scrape.

- `metrics_rules_dir`: The directory in which the Charmed Operator stores its metrics alert rules
  files.

- `logs_rules_dir`: The directory in which the Charmed Operator stores its logs alert rules files.

- `recurse_rules_dirs`: This parameters set whether Grafana Agent machine Charmed Operator has to
  search alert rules files recursively in the previous two directories or not.

- `log_slots`: Snap slots to connect to for scraping logs in the form ["snap-name:slot", ...].

- `dashboard_dirs`: List of directories where the dashboards are stored in the Charmed Operator.

- `refresh_events`: List of events on which to refresh relation data.


### Example 1 - Minimal instrumentation:

In order to use this object the following should be in the `charm.py` file.

```python
from charms.grafana_agent.v0.cos_agent import COSAgentProvider
...
class TelemetryProviderCharm(CharmBase):
    def __init__(self, *args):
        ...
        self._grafana_agent = COSAgentProvider(self)
```

### Example 2 - Full instrumentation:

In order to use this object the following should be in the `charm.py` file.

```python
from charms.grafana_agent.v0.cos_agent import COSAgentProvider
...
class TelemetryProviderCharm(CharmBase):
    def __init__(self, *args):
        ...
        self._grafana_agent = COSAgentProvider(
            self,
            relation_name="custom-cos-agent",
            metrics_endpoints=[
                {"path": "/metrics", "port": 9000},
                {"path": "/metrics", "port": 9001},
                {"path": "/metrics", "port": 9002},
            ],
            metrics_rules_dir="./src/alert_rules/prometheus",
            logs_rules_dir="./src/alert_rules/loki",
            recursive_rules_dir=True,
            log_slots=["my-app:slot"],
            dashboard_dirs=["./src/dashboards_1", "./src/dashboards_2"],
            refresh_events=["update-status", "upgrade-charm"],
        )
```

## COSAgentConsumer Library Usage

This object may be used by any Charmed Operator which gathers telemetry data by
implementing the consumer side of the `cos_agent` interface.
For instance Grafana Agent machine Charmed Operator.

For this purpose the charm needs to instantiate the `COSAgentConsumer` object with one mandatory
and two optional arguments.

### Parameters

- `charm`: A reference to the parent (Grafana Agent machine) charm.

- `relation_name`: The name of the relation that the charm uses to interact
  with its clients that provides telemetry data using the `COSAgentProvider` object.

  If provided, this relation name must match a provided relation in metadata.yaml with the
  `cos_agent` interface.
  The default value of this argument is "cos-agent".

- `refresh_events`: List of events on which to refresh relation data.


### Example 1 - Minimal instrumentation:

In order to use this object the following should be in the `charm.py` file.

```python
from charms.grafana_agent.v0.cos_agent import COSAgentConsumer
...
class GrafanaAgentMachineCharm(GrafanaAgentCharm)
    def __init__(self, *args):
        ...
        self._cos = COSAgentRequirer(self)
```


### Example 2 - Full instrumentation:

In order to use this object the following should be in the `charm.py` file.

```python
from charms.grafana_agent.v0.cos_agent import COSAgentConsumer
...
class GrafanaAgentMachineCharm(GrafanaAgentCharm)
    def __init__(self, *args):
        ...
        self._cos = COSAgentRequirer(
            self,
            relation_name="cos-agent-consumer",
            refresh_events=["update-status", "upgrade-charm"],
        )
```
"""

import base64
import json
import logging
import lzma
from collections import namedtuple
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from cosl import JujuTopology
from cosl.rules import AlertRules
from ops.charm import RelationEvent
from ops.framework import EventBase, EventSource, Object, ObjectEvents
from ops.model import Relation, Unit
from ops.testing import CharmType

LIBID = "dc15fa84cef84ce58155fb84f6c6213a"
LIBAPI = 0
LIBPATCH = 2

PYDEPS = ["cosl"]

DEFAULT_RELATION_NAME = "cos-agent"
DEFAULT_METRICS_ENDPOINT = {
    "path": "/metrics",
    "port": 80,
}

logger = logging.getLogger(__name__)
SnapEndpoint = namedtuple("SnapEndpoint", "owner, name")


class COSAgentProvider(Object):
    """Integration endpoint wrapper for the provider side of the cos_agent interface."""

    def __init__(
        self,
        charm: CharmType,
        relation_name: str = DEFAULT_RELATION_NAME,
        metrics_endpoints: Optional[List[dict]] = None,
        metrics_rules_dir: str = "./src/prometheus_alert_rules",
        logs_rules_dir: str = "./src/loki_alert_rules",
        recurse_rules_dirs: bool = False,
        log_slots: Optional[List[str]] = None,
        dashboard_dirs: Optional[List[str]] = None,
        refresh_events: Optional[List] = None,
    ):
        """Create a COSAgentProvider instance.

        Args:
            charm: The `CharmBase` instance that is instantiating this object.
            relation_name: The name of the relation to communicate over.
            metrics_endpoints: List of endpoints in the form [{"path": path, "port": port}, ...].
            metrics_rules_dir: Directory where the metrics rules are stored.
            logs_rules_dir: Directory where the logs rules are stored.
            recurse_rules_dirs: Whether to recurse into rule paths.
            log_slots: Snap slots to connect to for scraping logs
                in the form ["snap-name:slot", ...].
            dashboard_dirs: Directory where the dashboards are stored.
            refresh_events: List of events on which to refresh relation data.
        """
        super().__init__(charm, relation_name)
        metrics_endpoints = metrics_endpoints or [DEFAULT_METRICS_ENDPOINT]
        dashboard_dirs = dashboard_dirs or ["./src/grafana_dashboards"]

        self._charm = charm
        self._relation_name = relation_name
        self._metrics_endpoints = metrics_endpoints
        self._metrics_rules = metrics_rules_dir
        self._logs_rules = logs_rules_dir
        self._recursive = recurse_rules_dirs
        self._log_slots = log_slots or []
        self._dashboard_dirs = dashboard_dirs
        self._refresh_events = refresh_events or [self._charm.on.config_changed]

        events = self._charm.on[relation_name]
        self.framework.observe(events.relation_joined, self._on_refresh)
        self.framework.observe(events.relation_changed, self._on_refresh)
        for event in self._refresh_events:
            self.framework.observe(event, self._on_refresh)

    def _on_refresh(self, event):
        """Trigger the class to update relation data."""
        if isinstance(event, RelationEvent):
            relations = [event.relation]
        else:
            relations = self._charm.model.relations[self._relation_name]

        for relation in relations:
            if relation.data:
                if self._charm.unit.is_leader():
                    relation.data[self._charm.app].update(
                        {"config": self._generate_application_databag_content()}
                    )
                relation.data[self._charm.unit].update(
                    {"config": self._generate_unit_databag_content()}
                )

    def _generate_application_databag_content(self) -> str:
        """Collate the data for each nested app databag and return it."""
        # The application databag is divided in three chunks: alert rules (metrics and logs) and
        # dashboards.
        # Scrape jobs and log slots are unit-dependent and are therefore stored in unit databag.

        data = {
            # primary key
            "metrics": {
                # secondary key
                "alert_rules": self._metrics_alert_rules,
            },
            "logs": {
                "alert_rules": self._log_alert_rules,
            },
            "dashboards": {
                "dashboards": self._dashboards,
            },
        }

        return json.dumps(data)

    def _generate_unit_databag_content(self) -> str:
        """Collate the data for each nested unit databag and return it."""
        # The unit databag is divided in two chunks: metrics (scrape jobs only) and logs.
        # Alert rules and dashboards are unit-independent and are therefore stored in app databag.

        data = {
            # primary key
            "metrics": {
                # secondary key
                "scrape_jobs": self._scrape_jobs,
            },
            "logs": {
                "targets": self._log_slots,
            },
        }

        return json.dumps(data)

    @property
    def _scrape_jobs(self) -> List[Dict]:
        """Return a prometheus_scrape-like data structure for jobs."""
        job_name_prefix = self._charm.app.name
        return [
            {"job_name": f"{job_name_prefix}_{key}", **endpoint}
            for key, endpoint in enumerate(self._metrics_endpoints)
        ]

    @property
    def _metrics_alert_rules(self) -> Dict:
        """Use (for now) the prometheus_scrape AlertRules to initialize this."""
        alert_rules = AlertRules(
            query_type="promql", topology=JujuTopology.from_charm(self._charm)
        )
        alert_rules.add_path(self._metrics_rules, recursive=self._recursive)
        return alert_rules.as_dict()

    @property
    def _log_alert_rules(self) -> Dict:
        """Use (for now) the loki_push_api AlertRules to initialize this."""
        alert_rules = AlertRules(query_type="logql", topology=JujuTopology.from_charm(self._charm))
        alert_rules.add_path(self._logs_rules, recursive=self._recursive)
        return alert_rules.as_dict()

    @property
    def _dashboards(self) -> List[str]:
        dashboards = []
        for d in self._dashboard_dirs:
            for path in Path(d).glob("*"):
                dashboards.append(self._encode_dashboard_content(path.read_bytes()))

        return dashboards

    @staticmethod
    def _encode_dashboard_content(content: Union[str, bytes]) -> str:
        if isinstance(content, str):
            content = bytes(content, "utf-8")

        return base64.b64encode(lzma.compress(content)).decode("utf-8")


class COSAgentDataChanged(EventBase):
    """Event emitted by `COSAgentRequirer` when relation data changes."""


class COSAgentRequirerEvents(ObjectEvents):
    """`COSAgentRequirer` events."""

    data_changed = EventSource(COSAgentDataChanged)


class COSAgentRequirer(Object):
    """Integration endpoint wrapper for the Requirer side of the cos_agent interface."""

    on = COSAgentRequirerEvents()

    def __init__(
        self,
        charm: CharmType,
        relation_name: str = DEFAULT_RELATION_NAME,
        refresh_events: Optional[List[str]] = None,
    ):
        """Create a COSAgentRequirer instance.

        Args:
            charm: The `CharmBase` instance that is instantiating this object.
            relation_name: The name of the relation to communicate over.
            refresh_events: List of events on which to refresh relation data.
        """
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name
        self._refresh_events = refresh_events or [self._charm.on.config_changed]

        events = self._charm.on[relation_name]
        self.framework.observe(events.relation_joined, self._on_relation_data_changed)
        self.framework.observe(events.relation_changed, self._on_relation_data_changed)
        for event in self._refresh_events:
            self.framework.observe(event, self.trigger_refresh)

    def _on_relation_data_changed(self, _):
        self.on.data_changed.emit()

    def trigger_refresh(self, _):
        """Trigger a refresh of relation data."""
        # FIXME: Figure out what we should do here
        self.on.data_changed.emit()

    @staticmethod
    def _relation_unit(relation: Relation) -> Optional[Unit]:
        """Return the principal unit for a relation."""
        if relation and relation.units:
            # With subordiante charms, relation.units is always either empty or has only the
            # principal unit, so next(iter(...)) is fine.
            return next(iter(relation.units))
        return None

    @property
    def _relations(self):
        return self._charm.model.relations[self._relation_name]

    @staticmethod
    def _fetch_data_from_relation(relation: Relation, primary_key: str, secondary_key: str):
        """Extract data by path from a relation's app data."""
        # ensure that whatever context we're running this in, we take the necessary precautions:
        if not relation.data or not relation.app:
            return None

        config = {}
        if primary_key == "dashboards" or secondary_key == "alert_rules":
            config = json.loads(relation.data[relation.app].get("config", "{}"))
        else:
            unit = COSAgentRequirer._relation_unit(relation)
            if unit and relation.data[unit]:
                config = json.loads(relation.data[unit].get("config", "{}"))
        return config.get(primary_key, {}).get(secondary_key, None)

    @property
    def metrics_alerts(self) -> Dict[str, Any]:
        """Fetch metrics alerts."""
        alert_rules = {}
        for relation in self._relations:
            unit = self._relation_unit(relation)
            # This is only used for naming the file, so be as specific as we
            # can be, but it's ok if the unit name isn't exactly correct, so
            # long as we don't dedupe away the alerts, which will be
            identifier = JujuTopology(
                model=self._charm.model.name,
                model_uuid=self._charm.model.uuid,
                application=relation.app.name if relation.app else "unknown",
                unit=unit.name if unit else "unknown",
            ).identifier
            if data := self._fetch_data_from_relation(relation, "metrics", "alert_rules"):
                alert_rules.update({identifier: data})
        return alert_rules

    @property
    def metrics_jobs(self) -> List[Dict]:
        """Parse the relation data contents and extract the metrics jobs."""
        scrape_jobs = []
        for relation in self._relations:
            if jobs := self._fetch_data_from_relation(relation, "metrics", "scrape_jobs"):
                for job in jobs:
                    job_config = {
                        "job_name": job["job_name"],
                        "metrics_path": job["path"],
                        "static_configs": [{"targets": [f"localhost:{job['port']}"]}],
                    }
                    scrape_jobs.append(job_config)

        return scrape_jobs

    @property
    def snap_log_endpoints(self) -> List[SnapEndpoint]:
        """Fetch logging endpoints exposed by related snaps."""
        plugs = []
        for relation in self._relations:
            if targets := self._fetch_data_from_relation(relation, "logs", "targets"):
                for target in targets:
                    if target in plugs:
                        logger.warning(
                            f"plug {target} already listed. "
                            "The same snap is being passed from multiple "
                            "endpoints; this should not happen."
                        )
                    else:
                        plugs.append(target)

        endpoints = []
        for plug in plugs:
            if ":" not in plug:
                logger.error(f"invalid plug definition received: {plug}. Ignoring...")
            else:
                endpoint = SnapEndpoint(*plug.split(":"))
                endpoints.append(endpoint)
        return endpoints

    @property
    def logs_alerts(self) -> Dict[str, Any]:
        """Fetch log alerts."""
        alert_rules = {}
        for relation in self._relations:
            # This is only used for naming the file, so be as specific as we
            # can be, but it's ok if the unit name isn't exactly correct, so
            # long as we don't dedupe away the alerts, which will be
            identifier = JujuTopology(
                model=self._charm.model.name,
                model_uuid=self._charm.model.uuid,
                application=relation.app.name if relation.app else "unknown",
                unit=self._charm.unit.name,
            ).identifier
            if rules := self._fetch_data_from_relation(relation, "logs", "alert_rules"):
                alert_rules.update({identifier: rules})
        return alert_rules

    @property
    def dashboards(self) -> List[Dict[str, str]]:
        """Fetch dashboards as encoded content."""
        dashboards = []  # type: List[Dict[str, str]]
        for relation in self._relations:
            if dashboard_data := self._fetch_data_from_relation(
                relation, "dashboards", "dashboards"
            ):
                for dashboard in dashboard_data:
                    content = self._decode_dashboard_content(dashboard)
                    title = json.loads(content).get("title", "no_title")
                    dashboards.append(
                        {
                            "relation_id": str(relation.id),
                            # We don't have the remote charm name, but give us an identifier
                            "charm": f"{relation.name}-{relation.app.name if relation.app else 'unknown'}",
                            "content": content,
                            "title": title,
                        }
                    )
        return dashboards

    @staticmethod
    def _decode_dashboard_content(encoded_content: str) -> str:
        return lzma.decompress(base64.b64decode(encoded_content.encode("utf-8"))).decode()

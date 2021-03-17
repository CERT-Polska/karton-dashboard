import json
import logging
import re
import textwrap
from collections import defaultdict
from datetime import datetime
from operator import itemgetter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import mistune  # type: ignore
from flask import (  # type: ignore
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
)
from karton.core import Producer
from karton.core.backend import KartonMetrics
from karton.core.base import KartonBase
from karton.core.inspect import KartonAnalysis, KartonQueue, KartonState
from karton.core.task import Task, TaskPriority, TaskState
from prometheus_client import Gauge, generate_latest  # type: ignore

logging.basicConfig(level=logging.INFO)

app_path = Path(__file__).parent
static_folder = app_path / "static"
app = Flask(__name__, static_folder=None, template_folder=str(app_path / "templates"))

karton = KartonBase(identity="karton.dashboard")


def restart_tasks(tasks: List[Task]) -> None:
    identity = "karton.dashboard-retry"
    producer = Producer(identity=identity)

    for task in tasks:
        # spawn a new task and mark the original one as finished
        producer.send_task(task.fork_task())
        karton.backend.set_task_status(
            task=task, status=TaskState.FINISHED, consumer=identity
        )


def cancel_tasks(tasks: List[Task]) -> None:
    for task in tasks:
        karton.backend.set_task_status(
            task=task, status=TaskState.FINISHED, consumer="karton.dashboard-cancel"
        )


class TaskView:
    """
    All problems in computer science can be solved by another
    layer of indirection.
    """

    def __init__(self, task: Task) -> None:
        self._task = task

    @property
    def headers(self) -> Dict[str, Any]:
        return self._task.headers

    @property
    def uid(self) -> str:
        return self._task.uid

    @property
    def parent_uid(self) -> Optional[str]:
        return self._task.parent_uid

    @property
    def root_uid(self) -> str:
        return self._task.root_uid

    @property
    def priority(self) -> TaskPriority:
        return self._task.priority

    @property
    def status(self) -> TaskState:
        return self._task.status

    @property
    def last_update(self) -> datetime:
        return datetime.fromtimestamp(self._task.last_update)

    @property
    def last_update_delta(self) -> str:
        return pretty_delta(self.last_update)

    def to_dict(self) -> Dict[str, Any]:
        return json.loads(self._task.serialize())

    def to_json(self, indent=None) -> str:
        return self._task.serialize(indent=indent)


class QueueView:
    def __init__(self, queue: KartonQueue) -> None:
        self._queue = queue

    def to_dict(self) -> Dict[str, Any]:
        tasks = sorted(
            self._queue.pending_tasks, key=lambda t: t.last_update, reverse=True
        )
        crashed = sorted(
            self._queue.crashed_tasks, key=lambda t: t.last_update, reverse=True
        )

        return {
            "identity": self._queue.bind.identity,
            "filters": self._queue.bind.filters,
            "description": self._queue.bind.info,
            "persistent": self._queue.bind.persistent,
            "version": self._queue.bind.version,
            "replicas": self._queue.online_consumers_count,
            "service_version": self._queue.bind.service_version,
            "tasks": [task.uid for task in tasks],
            "crashed": [task.uid for task in crashed],
        }


class AnalysisView:
    def __init__(self, analysis: KartonAnalysis) -> None:
        self._analysis = analysis

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uid": self._analysis.root_uid,
            "queues": {
                queue_name: [TaskView(task).to_dict() for task in queue.pending_tasks]
                for queue_name, queue in self._analysis.pending_queues.items()
            },
        }


def pretty_delta(dt: datetime) -> str:
    diff = datetime.now() - dt
    seconds_diff = int(diff.total_seconds())
    if seconds_diff < 180:
        return f"{seconds_diff} seconds ago"
    minutes_diff = seconds_diff // 60
    if minutes_diff < 180:
        return f"{minutes_diff} minutes ago"
    hours_diff = minutes_diff // 60
    return f"{hours_diff} hours ago"


@app.template_filter("render_description")
def render_description(description) -> Optional[str]:
    if not description:
        return None
    return mistune.markdown(textwrap.dedent(description))


def get_xrefs(root_uid) -> List[Tuple[str, str]]:
    config = karton.config.config
    if not config.has_option("dashboard", "xrefs"):
        return []
    xrefs = json.loads(config.get("dashboard", "xrefs"))
    return sorted(
        (
            (label, url_template.format(root_uid=root_uid))
            for label, url_template in xrefs.items()
        ),
        key=itemgetter(0),
    )


karton_logs = Gauge("karton_logs", "Pending logs")
karton_tasks = Gauge("karton_tasks", "Pending tasks", ("name", "priority", "status"))
karton_replicas = Gauge("karton_replicas", "Replicas", ("name", "version"))
karton_metrics = Gauge("karton_metrics", "Metrics", ("metric", "name"))


def add_metrics(state: KartonState, metric: KartonMetrics, key: str) -> None:
    metrics = {k: int(v) for k, v in state.backend.redis.hgetall(metric.value).items()}
    for name, value in metrics.items():
        karton_metrics.labels(key, name).set(value)


@app.route("/varz", methods=["GET"])
def varz():
    """ Update and get prometheus metrics """

    state = KartonState(karton.backend)
    for _key, gauge in karton_tasks._metrics.items():
        gauge.set(0)

    for queue in state.queues.values():
        safe_name = re.sub("[^a-z0-9]", "_", queue.bind.identity.lower())
        task_infos = defaultdict(int)
        for task in queue.tasks:
            task_infos[(safe_name, task.priority, task.status)] += 1

        for (name, priority, status), count in task_infos.items():
            karton_tasks.labels(name, priority.value, status.value).set(count)
        replicas = len(state.replicas[queue.bind.identity])
        karton_replicas.labels(safe_name, queue.bind.version).set(replicas)

    add_metrics(state, KartonMetrics.TASK_ASSIGNED, "assigned")
    add_metrics(state, KartonMetrics.TASK_CONSUMED, "consumed")
    add_metrics(state, KartonMetrics.TASK_CRASHED, "crashed")
    add_metrics(state, KartonMetrics.TASK_GARBAGE_COLLECTED, "garbage-collected")
    add_metrics(state, KartonMetrics.TASK_PRODUCED, "produced")

    return generate_latest()


@app.route("/static/<path:path>", methods=["GET"])
def static(path: str):
    return send_from_directory(static_folder, path)


@app.route("/", methods=["GET"])
def get_queues():
    state = KartonState(karton.backend)
    return render_template("index.html", queues=state.queues)


@app.route("/api/queues", methods=["GET"])
def get_queues_api():
    state = KartonState(karton.backend)
    return jsonify(
        {
            identity: QueueView(queue).to_dict()
            for identity, queue in state.queues.items()
        }
    )


@app.route("/<queue_name>/restart", methods=["POST"])
def restart_queue_tasks(queue_name):
    state = KartonState(karton.backend)
    queue = state.queues.get(queue_name)
    if not queue:
        return jsonify({"error": "Queue doesn't exist"}), 404

    restart_tasks(queue.crashed_tasks)
    return redirect(request.referrer)


@app.route("/<queue_name>/cancel", methods=["POST"])
def cancel_queue_tasks(queue_name):
    state = KartonState(karton.backend)
    queue = state.queues.get(queue_name)
    if not queue:
        return jsonify({"error": "Queue doesn't exist"}), 404

    cancel_tasks(queue.crashed_tasks)
    return redirect(request.referrer)


@app.route("/restart_task/<task_id>/restart", methods=["POST"])
def restart_task(task_id):
    task = karton.backend.get_task(task_id)
    if not task:
        return jsonify({"error": "Task doesn't exist"}), 404

    restart_tasks([task])
    return redirect(request.referrer)


@app.route("/cancel_task/<task_id>/cancel", methods=["POST"])
def cancel_task(task_id):
    task = karton.backend.get_task(task_id)
    if not task:
        return jsonify({"error": "Task doesn't exist"}), 404

    cancel_tasks([task])
    return redirect(request.referrer)


@app.route("/queue/<queue_name>", methods=["GET"])
def get_queue(queue_name):
    state = KartonState(karton.backend)
    queue = state.queues.get(queue_name)
    if not queue:
        return jsonify({"error": "Queue doesn't exist"}), 404

    return render_template("queue.html", name=queue_name, queue=queue)


@app.route("/queue/<queue_name>/crashed", methods=["GET"])
def get_crashed_queue(queue_name):
    state = KartonState(karton.backend)
    queue = state.queues.get(queue_name)
    if not queue:
        return jsonify({"error": "Queue doesn't exist"}), 404

    return render_template("crashed.html", name=queue_name, queue=queue)


@app.route("/api/queue/<queue_name>", methods=["GET"])
def get_queue_api(queue_name):
    state = KartonState(karton.backend)
    queue = state.queues.get(queue_name)
    if not queue:
        return jsonify({"error": "Queue doesn't exist"}), 404
    return jsonify(QueueView(queue).to_dict())


@app.route("/task/<task_id>", methods=["GET"])
def get_task(task_id):
    task = karton.backend.get_task(task_id)
    if not task:
        return jsonify({"error": "Task doesn't exist"}), 404

    return render_template(
        "task.html", task=TaskView(task), xrefs=get_xrefs(task.root_uid)
    )


@app.route("/api/task/<task_id>", methods=["GET"])
def get_task_api(task_id):
    task = karton.backend.get_task(task_id)
    if not task:
        return jsonify({"error": "Task doesn't exist"}), 404
    return jsonify(TaskView(task).to_dict())


@app.route("/analysis/<root_id>", methods=["GET"])
def get_analysis(root_id):
    state = KartonState(karton.backend)
    analysis = state.analyses.get(root_id)
    if not analysis:
        return jsonify({"error": "Analysis doesn't exist"}), 404

    return render_template(
        "analysis.html", analysis=analysis, xrefs=get_xrefs(analysis.root_uid)
    )


@app.route("/api/analysis/<root_id>", methods=["GET"])
def get_analysis_api(root_id):
    state = KartonState(karton.backend)
    analysis = state.analyses.get(root_id)
    if not analysis:
        return jsonify({"error": "Analysis doesn't exist"}), 404

    return jsonify(AnalysisView(analysis).to_dict())

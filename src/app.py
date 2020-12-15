import logging
import json
import textwrap
import re

from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from flask import abort, Flask, render_template, send_from_directory, \
    jsonify, request, redirect  # type: ignore
from karton.core.base import KartonBase  # type: ignore
from karton.core.task import TaskState  # type: ignore
from karton.core import Producer  # type: ignore
from karton.core.task import Task as KartonTask  # type: ignore
from mworks import CommonRoutes  # type: ignore
from prometheus_client import Gauge, generate_latest  # type: ignore
from collections import defaultdict

import mistune  # type: ignore


app = Flask(__name__, static_folder=None)
mworks = CommonRoutes(app)
logging.basicConfig(level=logging.INFO)

karton = KartonBase(identity="karton.dashboard")

Filters = Dict[str, str]
Registration = Union[List[Filters], Dict[str, Any]]


class Queue:
    def __init__(self, name: str, registration: Registration) -> None:
        self.name: str = name
        self.tasks: List[Task] = []
        self.crashed: List[Task] = []
        if isinstance(registration, list):
            # v2.2.0 compatibility
            self.binds: List[Filters] = registration
            self.raw_description: Optional[str] = None
            self.persistent: bool = not name.endswith(".test")
            self.version: str = "2.x.x"
        else:
            self.binds = registration["filters"]
            self.raw_description = registration["info"]
            self.persistent = registration["persistent"]
            self.version = registration["version"]
        self.description: Optional[str] = render_description(
            self.raw_description
        )
        self.replicas: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "identity": self.name,
            "filters": self.binds,
            "description": self.raw_description,
            "persistent": self.persistent,
            "version": self.version,
            "replicas": self.replicas,
            "tasks": [task.taskid for task in self.tasks],
            "crashed": [task.taskid for task in self.crashed]
        }


class Task:
    def __init__(self, data: Dict[str, Any]) -> None:
        self.taskid: str = data["uid"]
        self.data: Dict[str, Any] = data

    def prettyprint(self) -> str:
        return json.dumps(self.data, indent=4)

    @property
    def error(self) -> str:
        return self.data["error"]

    @property
    def status(self) -> str:
        return self.data["status"]

    @property
    def priority(self) -> str:
        return self.data["priority"]

    def last_update(self) -> datetime:
        return datetime.fromtimestamp(self.data["last_update"])

    def last_update_delta(self) -> str:
        return pretty_delta(self.last_update())

    def to_dict(self) -> Dict[str, Any]:
        return self.data


class Analysis:
    def __init__(self, uid: str) -> None:
        self.rootid: str = uid
        self.queues: Dict[str, List[Task]] = {}

    def add_task(self, identity: str, taskdata: Dict[str, Any]):
        if identity not in self.queues:
            self.queues[identity] = []
        self.queues[identity].append(Task(taskdata))

    def last_update(self) -> datetime:
        return max([task.last_update()
                    for queue, tasks in self.queues.items()
                    for task in tasks])

    def last_update_delta(self) -> str:
        return pretty_delta(self.last_update())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uid": self.rootid,
            "queues": {identity: [task.to_dict() for task in queue]
                       for identity, queue in self.queues.items()},
            "last_update": self.last_update().timestamp()
        }


class KartonState:
    def __init__(self):
        # Log queue length
        self.log_queue_len = karton.rs.llen("karton.logs")

        # Queues
        binds = karton.rs.hgetall("karton.binds")
        queues: Dict[str, Queue] = {k: Queue(k, json.loads(v))
                                    for k, v in sorted(binds.items())}
        # Analyses (aka root tasks)
        analyses: Dict[str, Analysis] = {}

        # Filter tasks and add them to queues
        keys = karton.rs.keys("karton.task:*")
        for task in karton.rs.mget(keys):
            if task is None:
                # Harmless race condition, task removed in the meantime.
                continue

            taskdata = json.loads(task)
            if "receiver" not in taskdata["headers"]:
                # Task without a receiver. Weid flex, but ok.
                continue

            if taskdata["status"] == TaskState.FINISHED:
                # Don't count finished tasks (waiting for GC).
                continue

            queue_name = taskdata["headers"]["receiver"]
            if queue_name not in queues:
                # Queue removed but task is still in redis (waiting for GC).
                continue

            root_uid = taskdata["root_uid"]
            if root_uid not in analyses:
                analyses[root_uid] = Analysis(root_uid)

            analyses[root_uid].add_task(queue_name, taskdata)

            if taskdata["status"] == TaskState.CRASHED:
                queues[queue_name].crashed.append(Task(taskdata))
            else:
                queues[queue_name].tasks.append(Task(taskdata))

        # Count replicas
        for client in karton.rs.client_list():
            queue_name = client["name"]
            if queue_name not in queues:
                continue

            queues[queue_name].replicas += 1

        self.queues = queues
        self.analyses = analyses


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


def render_description(description) -> Optional[str]:
    if not description:
        return None
    return mistune.markdown(textwrap.dedent(description))


karton_logs = Gauge("karton_logs", "Pending logs")
karton_tasks = Gauge(
    "karton_tasks",
    "Pending tasks",
    ("name", "priority", "status")
)
karton_replicas = Gauge("karton_replicas", "Replicas", ("name", "version"))


@app.route("/varz", methods=["GET"])
def varz():
    """ Update and get prometheus metrics """

    state = KartonState()
    for _key, gauge in karton_tasks._metrics.items():
        gauge.set(0)

    for queue in state.queues.values():
        safe_name = re.sub("[^a-z0-9]", "_", queue.name.lower())
        task_infos = defaultdict(int)
        for task in queue.tasks:
            task_infos[(safe_name, task.priority, task.status)] += 1

        for (name, priority, status), count in task_infos.items():
            karton_tasks.labels(name, priority, status).set(count)
        karton_replicas.labels(safe_name, queue.version).set(queue.replicas)

    karton_logs.set(state.log_queue_len)

    return generate_latest()


@app.route("/static/<path:path>", methods=["GET"])
def static(path: str):
    return send_from_directory("static", path)


@app.route("/", methods=["GET"])
def get_queues():
    state = KartonState()
    return render_template(
        "index.html", queues=state.queues.values(), log_len=state.log_queue_len
    )


@app.route("/api/queues", methods=["GET"])
def get_queues_api():
    state = KartonState()
    return jsonify({identity: queue.to_dict()
                    for identity, queue in state.queues.items()})


@app.route("/restart_task/<task_id>/restart", methods=["POST"])
def restart_task(task_id):
    producer = Producer(identity="karton.dashboard-retry")

    taskdata = karton.rs.get(f"karton.task:{task_id}")
    if not taskdata:
        return jsonify({
            "error": "Task doesn't exist"
        }), 404
    task = KartonTask.unserialize(taskdata)
    forked = task.fork_task()
    # spawn a new task and mark the original one as finished
    producer.send_task(forked)
    producer.declare_task_state(task=task, status=TaskState.FINISHED)
    return redirect(request.referrer)


@app.route("/queue/<queue_name>", methods=["GET"])
def get_queue(queue_name):
    state = KartonState()
    queue = state.queues.get(queue_name)
    if not queue:
        abort(404)
    return render_template("queue.html", name=queue_name, queue=queue)


@app.route("/queue/<queue_name>/crashed", methods=["GET"])
def get_crashed_queue(queue_name):
    state = KartonState()
    queue = state.queues.get(queue_name)
    if not queue:
        abort(404)
    return render_template("crashed.html", name=queue_name, queue=queue)


@app.route("/api/queue/<queue_name>", methods=["GET"])
def get_queue_api(queue_name):
    state = KartonState()
    queue = state.queues.get(queue_name)
    if not queue:
        return jsonify({
            "error": "Queue doesn't exist"
        }), 404
    return jsonify(queue.to_dict())


@app.route("/task/<task_id>", methods=["GET"])
def get_task(task_id):
    task = karton.rs.get(f"karton.task:{task_id}")
    if not task:
        abort(404)
    taskdata = Task(json.loads(task))
    return render_template("task.html", task=taskdata,)


@app.route("/api/task/<task_id>", methods=["GET"])
def get_task_api(task_id):
    task = karton.rs.get(f"karton.task:{task_id}")
    if not task:
        return jsonify({
            "error": "Task doesn't exist"
        }), 404
    taskdata = Task(json.loads(task))
    return jsonify(taskdata.to_dict())


@app.route("/analysis/<root_id>", methods=["GET"])
def get_analysis(root_id):
    state = KartonState()
    analysis = state.analyses.get(root_id)
    if not analysis:
        abort(404)
    return render_template("analysis.html", analysis=analysis)


@app.route("/api/analysis/<root_id>", methods=["GET"])
def get_analysis_api(root_id):
    state = KartonState()
    analysis = state.analyses.get(root_id)
    if not analysis:
        return jsonify({
            "error": "Analysis doesn't exist"
        }), 404
    return jsonify(analysis.to_dict())

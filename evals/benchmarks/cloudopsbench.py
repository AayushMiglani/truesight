import asyncio
import importlib.util
import json
import os
import re
import socket
import subprocess
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import ModuleType

from pydantic import DirectoryPath
from pydantic_settings import BaseSettings, SettingsConfigDict

from evals.benchmark import Case, Score
from evals.benchmarks.cloudopsbench_labels import LABEL_SIGNS
from truesight.answer import Answer
from truesight.settings import load

SYSTEM_NAME = {"boutique": "boutique", "trainticket": "train-ticket"}
CONTRACTS = "agents/cloudops_agent/runtime/contracts.py"
SERVER_START_SECONDS = 60.0
SERVER_STOP_SECONDS = 10.0
PORT_POLL_SECONDS = 0.3


class CloudOpsBenchSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CLOUDOPSBENCH_", frozen=True)

    dir: DirectoryPath


class CloudOpsBench:
    name = "cloudopsbench"
    metrics = ("CA", "FA", "JRA")

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or load(CloudOpsBenchSettings).dir).expanduser().resolve()

    def cases(self) -> list[Case]:
        contracts = _load_contracts(self.root / CONTRACTS)
        contexts = {system: _context(contracts, system) for system in SYSTEM_NAME.values()}
        paths = sorted(p.parent for p in self.root.glob("benchmark/*/*/*/metadata.json"))
        return [self._case(path, contexts) for path in paths]

    def _case(self, path: Path, contexts: dict[str, str]) -> Case:
        system_dir, category = path.parts[-3], path.parts[-2]
        meta = json.loads((path / "metadata.json").read_text(encoding="utf-8"))
        return Case(
            id=f"{system_dir}/{category}/{path.name}",
            group=f"{system_dir}/{category}",
            alert=meta["query"],
            context=contexts[SYSTEM_NAME[system_dir]],
            truth=meta["result"],
            source=str(path),
        )

    @asynccontextmanager
    async def environment(self, case: Case, log_dir: Path) -> AsyncIterator[list[str]]:
        path = Path(case.source)
        port = _free_port()
        env = {
            **os.environ,
            "CLOUDOPSBENCH_CASE_PATH": str(path),
            "CLOUDOPSBENCH_SYSTEM": SYSTEM_NAME[path.parts[-3]],
            "CLOUDOPSBENCH_FAULT_CATEGORY": path.parts[-2],
            "CLOUDOPSBENCH_RUN_ID": log_dir.name,
            "CLOUDOPSBENCH_TRACE_PATH": str(log_dir / "mcp.jsonl"),
            "CLOUDOPSBENCH_MCP_PORT": str(port),
        }
        with (log_dir / "server.log").open("w", encoding="utf-8") as log:
            proc = await asyncio.create_subprocess_exec(
                str(self.root / ".venv/bin/python"),
                "-m",
                "cloudopsbench_mcp",
                cwd=self.root,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                await _wait_for_port(port, proc)
                yield [f"http://127.0.0.1:{port}/mcp"]
            finally:
                await _stop(proc)

    def score(self, case: Case, answer: Answer) -> Score:
        ca = _normalize(answer.component) == _normalize(case.truth["fault_object"])
        fa = _normalize(answer.fault_type) == _normalize(case.truth["root_cause"])
        return Score(metrics={"CA": ca, "FA": fa, "JRA": ca and fa}, passed=ca and fa)


def create_benchmark() -> CloudOpsBench:
    return CloudOpsBench()


def _load_contracts(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("cloudopsbench_contracts", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Cloud-OpsBench contracts from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _label_list(contracts: ModuleType) -> str:
    lines = contracts.root_cause_list_str.strip().splitlines()
    labels = [line.split()[1] for line in lines]
    if set(labels) != set(LABEL_SIGNS):
        raise RuntimeError(f"label lists differ: {sorted(set(labels) ^ set(LABEL_SIGNS))}")
    return "\n".join(
        f"{line}; seen as: {LABEL_SIGNS[label]}" for line, label in zip(lines, labels, strict=True)
    )


def _context(contracts: ModuleType, system: str) -> str:
    return f"""This is a Kubernetes incident. Pick labels strictly from the lists below.

Set "component" to Kind/Name, where Kind is node, app or namespace and Name comes
from List B (for example app/adservice or node/worker-01). Kind must match the
(Requires Target: ...) tag of the root cause you choose.
Set "fault_type" to exactly one label from List A (for example missing_service_account).

List A, valid root causes, each with what it looks like in tool output:
{_label_list(contracts)}
List B, valid names:
- Nodes: {contracts.VALID_NODES}
- APP: {contracts.SYSTEM_VALID_SERVICES[system]}
- Namespaces: {contracts.SYSTEM_VALID_NAMESPACES[system]}
"""


def _normalize(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def _wait_for_port(port: int, proc: asyncio.subprocess.Process) -> None:
    async with asyncio.timeout(SERVER_START_SECONDS):
        while True:
            if proc.returncode is not None:
                raise RuntimeError(f"Cloud-OpsBench server exited with code {proc.returncode}")
            try:
                _, writer = await asyncio.open_connection("127.0.0.1", port)
            except OSError:
                await asyncio.sleep(PORT_POLL_SECONDS)
                continue
            writer.close()
            await writer.wait_closed()
            return


async def _stop(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), SERVER_STOP_SECONDS)
    except TimeoutError:
        proc.kill()
        await proc.wait()

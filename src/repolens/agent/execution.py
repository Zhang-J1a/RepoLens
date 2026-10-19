"""Spawn-only workers; timeout never leaves a background operation running."""

import multiprocessing
import time

from repolens.agent.models import AgentStop


def _finish(process):
    if process.is_alive():
        process.terminate()
    process.join(timeout=0.5)
    if process.is_alive():
        process.kill()
        process.join()
    process.close()


def _operation_worker(connection, function, arguments):
    try:
        connection.send(("ok", function(*arguments)))
    except AgentStop as exc:
        connection.send(("error", str(exc)))
    except Exception:
        connection.send(("error", "operation_failed"))
    finally:
        connection.close()


def _receive(connection, process, timeout):
    if timeout <= 0 or not connection.poll(timeout):
        raise AgentStop("deadline_exceeded")
    try:
        status, value = connection.recv()
    except (EOFError, OSError):
        raise AgentStop("worker_failed") from None
    if status != "ok":
        raise AgentStop(value)
    return value


def execute_bounded(function, arguments, timeout):
    deadline = time.monotonic() + timeout
    context = multiprocessing.get_context("spawn")
    receiving, sending = context.Pipe(duplex=False)
    process = context.Process(target=_operation_worker, args=(sending, function, arguments), daemon=True)
    try:
        process.start()
        sending.close()
        return _receive(receiving, process, max(0, deadline - time.monotonic()))
    finally:
        receiving.close()
        sending.close()
        if process.pid is not None:
            _finish(process)


def _model_worker(connection, provider):
    try:
        while True:
            request = connection.recv()
            if request is None:
                return
            try:
                connection.send(("ok", provider.generate(request)))
            except Exception:
                connection.send(("error", "provider_failed"))
    except (EOFError, BrokenPipeError):
        return
    finally:
        connection.close()


class ModelSession:
    """One provider instance per task, preserving state for scripted providers."""

    def __init__(self, provider):
        self.provider = provider
        self.process = None
        self.connection = None

    def generate(self, request, timeout):
        deadline = time.monotonic() + timeout
        if self.process is None:
            context = multiprocessing.get_context("spawn")
            self.connection, child = context.Pipe()
            self.process = context.Process(target=_model_worker, args=(child, self.provider), daemon=True)
            try:
                self.process.start()
            except Exception:
                self.connection.close()
                self.process = None
                raise AgentStop("provider_unavailable") from None
            finally:
                child.close()
        try:
            self.connection.send(request)
            return _receive(self.connection, self.process, max(0, deadline - time.monotonic()))
        except (OSError, EOFError):
            raise AgentStop("provider_failed") from None

    def close(self):
        if self.connection is not None:
            self.connection.close()
        if self.process is not None:
            _finish(self.process)
            self.process = None

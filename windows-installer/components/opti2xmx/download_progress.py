"""Bounded, thread-safe in-memory operation snapshots; no game state or URLs."""
import copy
import re
import threading
import uuid

LIMIT = 200 * 1024 * 1024
PHASES = {'started', 'downloading', 'cache-hit', 'extracting', 'installing',
          'awaiting-launch', 'completed', 'failed'}


class OperationProgress:
    def __init__(self):
        self._lock = threading.Lock()
        self.instance_id = uuid.uuid4().hex
        self._value = dict(schema=1, instance_id=self.instance_id, operation_id=None, appid=None, kind='', version='',
                           phase='completed', running=False, downloaded_bytes=0,
                           total_bytes=None, error=None, revision=0)

    def snapshot(self):
        with self._lock:
            return copy.deepcopy(self._value)

    def begin(self, appid, kind, version=''):
        with self._lock:
            if self._value['running']:
                raise RuntimeError('Opti operation already running')
            identity = uuid.uuid4().hex
            self._value = dict(schema=1, instance_id=self.instance_id, operation_id=identity, appid=appid, kind=kind,
                               version=version, phase='started', running=True,
                               downloaded_bytes=0, total_bytes=None, error=None,
                               revision=self._value['revision'] + 1)
            return identity

    def update(self, identity, phase, downloaded_bytes=None, total_bytes=None):
        if phase not in PHASES:
            raise ValueError('Invalid operation phase')
        if downloaded_bytes is not None and (type(downloaded_bytes) is not int or not 0 <= downloaded_bytes <= LIMIT):
            raise ValueError('Invalid downloaded byte count')
        total = total_bytes if type(total_bytes) is int and 0 < total_bytes <= LIMIT else None
        with self._lock:
            if identity != self._value['operation_id'] or not self._value['running']:
                return False
            self._value['phase'] = phase
            if downloaded_bytes is not None:
                self._value['downloaded_bytes'] = downloaded_bytes
                self._value['total_bytes'] = total if total is None or downloaded_bytes <= total else None
            self._value['revision'] += 1
            return True

    def finish(self, identity, error=None, phase='completed'):
        if phase not in ('completed', 'failed', 'awaiting-launch'):
            raise ValueError('Invalid final operation phase')
        with self._lock:
            if identity != self._value['operation_id']:
                return False
            self._value['running'] = False
            self._value['phase'] = 'failed' if error is not None else phase
            if error is not None:
                text = re.sub(r'https?://\S+', '[download source]', str(error))
                self._value['error'] = text[:512]
            self._value['revision'] += 1
            return True

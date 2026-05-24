from __future__ import annotations

import math
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass


@dataclass
class PresenceSnapshot:
    """One reading from the presence detector. Consumers call snapshot() each
    tick to get current values; `onset` is consumed (cleared) on read so each
    onset event is reported to exactly one consumer."""
    last_db: float          # most recent ~block_ms RMS in dBFS
    smoothed_db: float      # exponentially-smoothed RMS (~2 s window by default)
    onset: bool             # sharp jump above recent baseline since last snapshot


class PresenceDetector:
    """Captures audio from an ALSA device by spawning `arecord` and reading
    raw S16_LE stereo samples from its stdout. Computes per-block RMS in
    dBFS, an exponentially-smoothed dBFS, and flags onsets when a block
    jumps significantly above the recent median.

    Runs the capture+analysis on a daemon thread; the agent calls
    .snapshot() from its main loop to read current state.
    """

    def __init__(
        self,
        device: str = "hw:1,0",
        samplerate: int = 48000,
        block_ms: int = 100,
        smoothing_seconds: float = 2.0,
        onset_db_jump: float = 16.0,
        onset_baseline_blocks: int = 8,
    ):
        self.device = device
        self.samplerate = samplerate
        self.block_samples = (samplerate * block_ms) // 1000
        self.block_bytes = self.block_samples * 2 * 2  # 16-bit stereo
        # EMA factor matched to the smoothing window.
        block_seconds = block_ms / 1000.0
        self.alpha = 1.0 - math.exp(-block_seconds / smoothing_seconds)
        self.onset_db_jump = onset_db_jump
        self.onset_baseline_blocks = onset_baseline_blocks

        self._lock = threading.Lock()
        self._last_db = -120.0
        self._smoothed_db = -120.0
        self._recent = deque(maxlen=20)  # ~2 s of per-block dBFS
        self._onset_pending = False
        self._blank_until = 0.0  # monotonic deadline; suppress audio updates until then

        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        self._proc = subprocess.Popen(
            [
                "arecord",
                "-q",
                "-D", self.device,
                "-f", "S16_LE",
                "-c", "2",
                "-r", str(self.samplerate),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except Exception:
                self._proc.kill()

    def blank_for(self, seconds: float) -> None:
        """Discard audio blocks for the next `seconds`. Use this immediately
        before the agent fires its own actuator so the resulting click does
        not trigger self-onsets and feed back into alarm."""
        with self._lock:
            deadline = time.monotonic() + seconds
            if deadline > self._blank_until:
                self._blank_until = deadline

    def _loop(self) -> None:
        import numpy as np

        assert self._proc is not None
        stdout = self._proc.stdout
        assert stdout is not None
        while not self._stop.is_set():
            raw = stdout.read(self.block_bytes)
            if not raw or len(raw) < self.block_bytes:
                return
            # Drop blocks during self-noise blanking — agent has told us its
            # own actuator is firing, ignore the resulting acoustic spike.
            with self._lock:
                if time.monotonic() < self._blank_until:
                    continue
            samples = np.frombuffer(raw, dtype=np.int16).reshape(-1, 2)
            mono = samples.mean(axis=1).astype(np.float32) / 32768.0
            rms = float(np.sqrt(np.mean(mono * mono)))
            db = 20.0 * math.log10(max(rms, 1e-7))
            with self._lock:
                # Onset = jump > onset_db_jump above the recent median baseline.
                if len(self._recent) >= self.onset_baseline_blocks:
                    sorted_recent = sorted(self._recent)
                    baseline = sorted_recent[len(sorted_recent) // 2]
                    if db > baseline + self.onset_db_jump:
                        self._onset_pending = True
                self._recent.append(db)
                self._last_db = db
                self._smoothed_db = self.alpha * db + (1.0 - self.alpha) * self._smoothed_db

    def snapshot(self) -> PresenceSnapshot:
        with self._lock:
            snap = PresenceSnapshot(
                last_db=self._last_db,
                smoothed_db=self._smoothed_db,
                onset=self._onset_pending,
            )
            self._onset_pending = False
            return snap

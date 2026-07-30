import threading
from typing import Callable, Optional, Any

from PyQt6.QtCore import QObject, pyqtSignal


class _Signals(QObject):
    done = pyqtSignal(object)
    error = pyqtSignal(str)


def _make_slot(callback, signal):
    def slot(value):
        callback(value)
        try:
            signal.disconnect(slot)
        except TypeError:
            pass
    return slot


def run_async(
    fn: Callable[[], Any],
    on_done: Optional[Callable[[Any], None]] = None,
    on_error: Optional[Callable[[str], None]] = None,
) -> threading.Thread:
    invoker = _Signals()
    slot_done = _make_slot(on_done, invoker.done) if on_done else None
    slot_error = _make_slot(on_error, invoker.error) if on_error else None

    if slot_done:
        invoker.done.connect(slot_done)
    if slot_error:
        invoker.error.connect(slot_error)

    def wrapper():
        import os as _os
        _os.write(2, b"DBG: run_async wrapper START\n")
        try:
            result = fn()
            _os.write(2, b"DBG: run_async wrapper SUCCESS, emitting done\n")
            if slot_done:
                invoker.done.emit(result)
        except Exception as e:
            msg = str(e)
            _os.write(2, f"DBG: run_async wrapper FAILED: {msg}\n".encode())
            if slot_error:
                invoker.error.emit(msg)
            else:
                import traceback
                traceback.print_exc()

    t = threading.Thread(target=wrapper, daemon=True)
    t.start()
    return t


def run_async_callback(fn, callback, *args, **kwargs):
    return run_async(fn, on_done=callback, *args, **kwargs)

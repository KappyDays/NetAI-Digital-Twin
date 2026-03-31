_on_change = set()


def subscribe_on_change(on_change):
    """Subscribe to module change events. Triggered when commands added, executed."""
    global _on_change
    _on_change.add(on_change)


def unsubscribe_on_change(on_change):
    """Unsubscribe to module change events."""
    global _on_change
    _on_change.discard(on_change)


def _dispatch_changed():
    for f in _on_change:
        f()

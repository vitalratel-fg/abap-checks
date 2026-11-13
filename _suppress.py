"""Known-good findings, excused with a reason, and a record of which were used.

    # abapcheck.toml
    [suppress.design.owners]
    "zt_x:zcl_y" = "why someone looked"

    suppressed = Suppressions(table)        # _runner.suppressions(script)
    if suppressed("owners", key): ...

The point is not to hide findings: an UNEXPLAINED finding has to be the only
thing in the output, or nobody reads the output. A suppression is a claim that
someone looked, and it must name exactly what it excuses.
"""


class Suppressions:
    def __init__(self, table):
        self._table = table
        self._used = {}

    def __call__(self, check, key):
        """EXACT match, and it records the hit.

        Substring matching in either direction means a suppression for one
        thing silently covers anything containing it. A suppression has to say
        exactly what it excuses, or it is a hole rather than an annotation.
        """
        if key not in self._table.get(check, {}):
            return False
        self._used.setdefault(check, set()).add(key)
        return True

    def used(self, check):
        """[(key, reason)] this run excused for one check, sorted."""
        return [(k, self._table[check][k]) for k in sorted(self._used.get(check, ()))]

    def stale(self):
        """[(check, key)] declared and never consulted.

        A suppression outlives the thing it excuses: the code gets fixed, the
        entry stays, and from then on it is a standing permission nobody
        remembers granting. Only meaningful after a FULL run, because a
        filtered run never consults the checks it skipped.
        """
        return [(check, key) for check, entries in sorted(self._table.items())
                for key in sorted(entries) if key not in self._used.get(check, ())]

    def checks(self):
        """The check names the table has entries for. One that names no
        check of the script is a typo, and excuses nothing forever."""
        return set(self._table)

"""An in-memory stand-in for the slice of the Firestore client the store
uses, so whole flows (book -> plan -> accept -> collect -> pay -> deliver)
run in tests without credentials.

`use_fake_firestore(monkeypatch)` installs it and returns the fake. The
booking-status transaction is replaced by direct read-then-write, which is
equivalent in a single-threaded test; ledger transactions buffer their writes
and apply them only if the whole function succeeds.
"""
from __future__ import annotations

import copy

import firestore_store as store


class Snap:
    def __init__(self, ref, data):
        self.reference, self.id, self._data = ref, ref.id, data

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self):
        return copy.deepcopy(self._data)


class DocRef:
    def __init__(self, coll, doc_id):
        self._coll, self.id = coll, doc_id

    def get(self, transaction=None):
        return Snap(self, self._coll.docs.get(self.id))

    def set(self, data, merge=False):
        if merge and self.id in self._coll.docs:
            self._coll.docs[self.id].update(copy.deepcopy(data))
        else:
            self._coll.docs[self.id] = copy.deepcopy(data)

    def update(self, fields):
        if self.id not in self._coll.docs:
            raise KeyError(self.id)
        self._coll.docs[self.id].update(copy.deepcopy(fields))

    def delete(self):
        self._coll.docs.pop(self.id, None)


class Query:
    def __init__(self, coll, filters, order=None, limit=None):
        self._coll, self._filters, self._order, self._limit = coll, filters, order, limit

    def where(self, field, op, value):
        return Query(self._coll, self._filters + [(field, op, value)], self._order, self._limit)

    def order_by(self, field, direction="ASCENDING"):
        return Query(self._coll, self._filters, (field, direction == "DESCENDING"), self._limit)

    def limit(self, n):
        return Query(self._coll, self._filters, self._order, n)

    def stream(self):
        rows = [(doc_id, data) for doc_id, data in list(self._coll.docs.items())
                if all(_match(data, f, op, v) for f, op, v in self._filters)]
        if self._order:
            field, desc = self._order
            rows = sorted((r for r in rows if field in r[1]), key=lambda r: r[1][field], reverse=desc)
        for doc_id, data in rows[: self._limit]:
            yield Snap(DocRef(self._coll, doc_id), data)


def _match(data, field, op, value) -> bool:
    if field not in data:
        return False
    if op == "==":
        return data[field] == value
    if op == "in":
        return data[field] in value
    raise NotImplementedError(op)


class Collection:
    def __init__(self):
        self.docs: dict[str, dict] = {}

    def document(self, doc_id):
        return DocRef(self, doc_id)

    def where(self, field, op, value):
        return Query(self, [(field, op, value)])

    def order_by(self, field, direction="ASCENDING"):
        return Query(self, []).order_by(field, direction)

    def stream(self):
        return Query(self, []).stream()


class Batch:
    def __init__(self):
        self._ops = []

    def set(self, ref, data, merge=False):
        self._ops.append(lambda: ref.set(data, merge=merge))

    def update(self, ref, fields):
        self._ops.append(lambda: ref.update(fields))

    def delete(self, ref):
        self._ops.append(ref.delete)

    def commit(self):
        for op in self._ops:
            op()
        self._ops = []


class Transaction(Batch):
    """Buffers writes until commit, so a function that raises halfway
    through leaves nothing behind -- the property real transactions give."""

    def rollback(self):
        self._ops = []


class FakeFirestore:
    def __init__(self):
        self._collections: dict[str, Collection] = {}

    def collection(self, name):
        return self._collections.setdefault(name, Collection())

    def batch(self):
        return Batch()

    def transaction(self):
        return Transaction()

    def docs(self, name) -> list[dict]:
        return [copy.deepcopy(d) for d in self.collection(name).docs.values()]


def _transition_without_transaction(transaction, ref, new_status, extra):
    snap = ref.get()
    if not snap.exists:
        raise KeyError("booking not found")
    booking = snap.to_dict()
    update = store.booking_transition_update(booking, new_status, extra)
    ref.update(update)
    return {**booking, **update}


def use_fake_firestore(monkeypatch) -> FakeFirestore:
    db = FakeFirestore()
    monkeypatch.setattr(store, "get_firestore_client", lambda: db)
    monkeypatch.setattr(store, "_transition_booking", _transition_without_transaction)
    return db

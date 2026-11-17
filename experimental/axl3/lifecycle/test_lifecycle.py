import unittest
from lifecycle import *
from axl3 import pack


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.s = open_task(
            session="s1",
            task="t1",
            peer="worker",
            recipient="manager",
            request="r1",
            expires=100,
            now=0,
        )

    def message(self, id="m1", seq=0, kind="status", status="running", **extra):
        m = {
            "id": id,
            "task": "t1",
            "sender": "worker",
            "to": "manager",
            "kind": kind,
            "seq": seq,
            "body": {},
            "reply": "r1",
        }
        if status is not None:
            m["status"] = status
        m.update(extra)
        return m

    def propose(self, s, *rows, **kw):
        return propose(
            s,
            pack(list(rows), MESSAGE),
            transport_session=kw.get("session", "s1"),
            authenticated_peer=kw.get("peer", "worker"),
            now=kw.get("now", 1),
        )

    def test_lifecycle(self):
        p = self.propose(self.s, self.message())
        s = commit(self.s, p, now=2)
        p = self.propose(s, self.message("m2", 1, status="blocked"))
        s = commit(s, p, now=2)
        p = self.propose(s, self.message("m3", 2, status="running"))
        s = commit(s, p, now=2)
        p = self.propose(s, self.message("m4", 3, kind="result", status="done"))
        s = commit(s, p, now=2)
        self.assertEqual((s.phase, s.next_seq, s.revision), ("done", 4, 4))

    def test_idempotent_ack(self):
        m = self.message(kind="result", status="done")
        s = commit(self.s, self.propose(self.s, m), now=2)
        p = self.propose(s, m)
        self.assertEqual(p.state, s)
        self.assertEqual(p.duplicates, ("m1",))
        self.assertEqual(p.accepted, ())

    def test_collision(self):
        m = self.message()
        s = commit(self.s, self.propose(self.s, m), now=2)
        m["body"] = {"evil": 1}
        with self.assertRaisesRegex(Error, "ID_COLLISION"):
            self.propose(s, m)

    def test_gap_stale(self):
        with self.assertRaisesRegex(Error, "SEQUENCE_GAP"):
            self.propose(self.s, self.message(seq=1))
        s = commit(self.s, self.propose(self.s, self.message()), now=2)
        with self.assertRaisesRegex(Error, "STALE_SEQUENCE"):
            self.propose(s, self.message("m2", 0))

    def test_session_auth_expiry(self):
        for kw in [{"session": "s2"}, {"peer": "attacker"}, {"now": 100}, {"now": float("nan")}]:
            with self.assertRaises(Error):
                self.propose(self.s, self.message(), **kw)

    def test_cancel(self):
        s = cancel(self.s, expected_revision=0)
        with self.assertRaisesRegex(Error, "TERMINAL_TASK"):
            self.propose(s, self.message(kind="result", status="done"))
        with self.assertRaisesRegex(Error, "REVISION_CONFLICT"):
            cancel(s, expected_revision=0)

    def test_cas_conflict(self):
        p = self.propose(self.s, self.message())
        s = cancel(self.s, expected_revision=0)
        with self.assertRaisesRegex(Error, "REVISION_CONFLICT"):
            commit(s, p, now=2)
        other = replace(self.s, task="other")
        with self.assertRaisesRegex(Error, "REVISION_CONFLICT"):
            commit(other, p, now=2)

    def test_atomic_rejection(self):
        with self.assertRaises(Error):
            self.propose(self.s, self.message(), self.message("m2", 8))
        self.assertEqual((self.s.revision, self.s.next_seq, self.s.ledger), (0, 0, ()))

    def test_correlation(self):
        with self.assertRaisesRegex(Error, "CORRELATION"):
            self.propose(self.s, self.message(reply="other"))

    def test_no_effect_from_request(self):
        with self.assertRaisesRegex(Error, "UNEXPECTED_KIND"):
            self.propose(
                self.s, self.message(kind="request", status=None, body={"tools_allowed": ["all"]})
            )

    def test_batch_dup(self):
        with self.assertRaisesRegex(Error, "BATCH_DUPLICATE"):
            self.propose(self.s, self.message(), self.message())

    def test_ledger_bound(self):
        s = replace(self.s, ledger=tuple((str(i), "x") for i in range(MAX_LEDGER)))
        with self.assertRaisesRegex(Error, "LEDGER_FULL"):
            self.propose(s, self.message())

    def test_status_requirements(self):
        for m in [
            self.message(kind="result", status=None),
            self.message(kind="error", status="running"),
            self.message(kind="evidence", status="running"),
            self.message(status="new"),
        ]:
            with self.assertRaises(Error):
                self.propose(self.s, m)

    def test_evidence(self):
        s = commit(self.s, self.propose(self.s, self.message(kind="evidence", status=None)), now=2)
        self.assertEqual(s.phase, "new")
        self.assertEqual(s.next_seq, 1)

    def test_remote_cancel_rejected(self):
        with self.assertRaises(Error):
            self.propose(self.s, self.message(status="cancelled"))

    def test_immutable_accepted(self):
        p = self.propose(self.s, self.message())
        self.assertIsInstance(p.accepted[0], str)
        with self.assertRaises(TypeError):
            p.accepted[0]["body"] = {}

    def test_clock_and_commit_expiry(self):
        with self.assertRaises(Error):
            open_task(
                session="s", task="t", peer="p", recipient="r", request="q", expires=10**1000, now=0
            )
        p = self.propose(self.s, self.message())
        with self.assertRaisesRegex(Error, "EXPIRED"):
            commit(self.s, p, now=100)

    def test_terminal_reserved(self):
        s = replace(self.s, ledger=tuple((str(i), "x") for i in range(MAX_LEDGER - 1)))
        with self.assertRaisesRegex(Error, "TERMINAL_SLOT_RESERVED"):
            self.propose(s, self.message())
        p = self.propose(s, self.message(kind="result", status="done"))
        self.assertEqual(p.state.phase, "done")


if __name__ == "__main__":
    unittest.main()

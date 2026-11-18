import unittest, subprocess, tempfile, json, sys, os
from pathlib import Path
from adapter import *

HERE = Path(__file__).resolve().parent


class AdapterTests(unittest.TestCase):
    def host(self, session="s1"):
        return Host(
            open_task(
                session=session,
                task="t1",
                peer="worker",
                recipient="manager",
                request="r1",
                expires=100,
                now=0,
            ),
            Cache(session, ()),
        )

    def rows(self, seq=0):
        return [
            {
                "id": f"m{i}",
                "task": "t1",
                "sender": "worker",
                "to": "manager",
                "kind": "status",
                "seq": i,
                "body": {
                    "evidence": "unchanged observed source " * 10,
                    "source": "file1",
                    "confidence": None,
                },
                "reply": "r1",
                "status": "running",
            }
            for i in range(seq, seq + 2)
        ]

    def request(self, h, format="axl", delivery="d1", seq=0):
        rs = self.rows(seq)
        payload = (
            axl_encode(rs, MESSAGE, ("task", "sender", "to"), scope=h.task.session, cache=h.cache)[
                0
            ]
            if format == "axl"
            else encode_json(rs, h.task.session, h.cache)
        )
        return {
            "delivery": delivery,
            "expected_revision": h.task.revision,
            "format": format,
            "payload": payload,
        }

    def receive(self, h, r, **kw):
        return receive(
            h,
            r,
            transport_session=kw.get("session", h.task.session),
            authenticated_peer=kw.get("peer", "worker"),
            now=kw.get("now", 1),
        )

    def test_equivalent_policies(self):
        a = self.host()
        b = self.host()
        for k in range(3):
            a, acka = self.receive(a, self.request(a, "axl", f"d{k}", k * 2))
            b, ackb = self.receive(b, self.request(b, "json", f"d{k}", k * 2))
            self.assertEqual(a.task, b.task)
            self.assertEqual(a.cache, b.cache)
            self.assertEqual(acka, ackb)

    def test_request_snapshot(self):
        from unittest.mock import patch
        import adapter

        h = self.host()
        r = self.request(h)
        original = adapter.request_digest

        def mutate_caller(snapshot):
            digest = original(snapshot)
            r["payload"] = "invalid external mutation"
            return digest

        with patch("adapter.request_digest", mutate_caller):
            updated, ack = self.receive(h, r)
        self.assertEqual(ack["accepted"], 2)
        self.assertEqual(updated.task.revision, 1)

    def test_native_json_payload(self):
        h = self.host()
        r = self.request(h, "json")
        native = {**r, "payload": load(r["payload"])}
        a, aa = self.receive(h, r)
        b, bb = self.receive(h, native)
        self.assertEqual(a.task, b.task)
        self.assertEqual(a.cache, b.cache)
        self.assertEqual(aa, bb)

    def test_duplicate_receipt(self):
        h = self.host()
        r = self.request(h)
        h, ack = self.receive(h, r)
        same, retry = self.receive(h, r)
        self.assertEqual(same, h)
        self.assertTrue(retry["duplicate"])
        self.assertEqual(retry["accepted"], 0)

    def test_collision_stale_missing(self):
        initial = self.host()
        r = self.request(initial)
        h, _ = self.receive(initial, r)
        changed = {**r, "payload": r["payload"] + " "}
        with self.assertRaisesRegex(Error, "DELIVERY_COLLISION"):
            self.receive(h, changed)
        with self.assertRaisesRegex(Error, "STALE_REVISION"):
            self.receive(h, {**r, "delivery": "other"})
        req = self.request(h, delivery="d2", seq=2)
        req["payload"] = req["payload"].replace("^e0", "^missing")
        with self.assertRaisesRegex(Error, "Unknown evidence reference"):
            self.receive(h, req)

    def test_transport_expiry(self):
        h = self.host()
        r = self.request(h)
        for kw in [{"session": "s2"}, {"peer": "other"}, {"now": 100}]:
            with self.assertRaises(Error):
                self.receive(h, r, **kw)

    def test_commit_clock_refresh(self):
        h = self.host()
        r = self.request(h)
        ticks = iter([1, 1, 100])
        with self.assertRaisesRegex(Error, "EXPIRED"):
            self.receive(h, r, now=lambda: next(ticks))
        self.assertEqual(h.task.revision, 0)
        self.assertEqual(h.cache.entries, ())

    def test_cancel_race(self):
        from lifecycle import cancel

        h = self.host()
        r = self.request(h)
        h = replace(h, task=cancel(h.task, expected_revision=0))
        with self.assertRaisesRegex(Error, "STALE_REVISION"):
            self.receive(h, r)

    def test_receipt_reserve(self):
        h = replace(self.host(), receipts=tuple((str(i), "x", 0) for i in range(MAX_RECEIPTS - 1)))
        with self.assertRaisesRegex(Error, "TERMINAL_RECEIPT_RESERVED"):
            self.receive(h, self.request(h))

    def test_hydration_failure_rolls_back(self):
        for mode in ("axl", "json"):
            h = self.host()
            rs = self.rows()
            rs[1]["seq"] = 3
            payload = (
                axl_encode(rs, MESSAGE, ("task", "sender", "to"), scope="s1", cache=h.cache)[0]
                if mode == "axl"
                else encode_json(rs, "s1", h.cache)
            )
            req = {"delivery": "bad", "expected_revision": 0, "format": mode, "payload": payload}
            with self.assertRaisesRegex(Error, "SEQUENCE_GAP"):
                self.receive(h, req)
            self.assertEqual(h.cache.entries, ())
            self.assertEqual(h.receipts, ())
            self.assertEqual(h.task.revision, 0)

    def test_json_malformed(self):
        h = self.host()
        r = self.request(h, "json")
        o = load(r["payload"])
        for bad in [[True] + o[1:], o[:4] + [{"9": None}] + o[5:], o[:6] + [[[True]]]]:
            with self.assertRaises(Error):
                self.receive(h, {**r, "payload": dump(bad)})

    @unittest.skipIf(
        os.name == "nt", "Process fixture uses POSIX flock; Windows locking is not implemented"
    )
    def test_real_process_sessions(self):
        calls = []
        with tempfile.TemporaryDirectory() as folder:
            a = self.host("a")
            b = self.host("b")
            pa = Path(folder) / "a.json"
            pb = Path(folder) / "b.json"
            pa.write_text(json.dumps(serialize(a)))
            pb.write_text(json.dumps(serialize(b)))

            def run(path, session, request):
                p = subprocess.run(
                    [
                        sys.executable,
                        str(HERE / "worker.py"),
                        "--state",
                        str(path),
                        "--session",
                        session,
                        "--peer",
                        "worker",
                    ],
                    input=dump(request),
                    text=True,
                    capture_output=True,
                    timeout=10,
                    check=True,
                )
                result = json.loads(p.stdout)
                calls.append(result)
                return result

            ra = self.request(a, "axl")
            rb = self.request(b, "json")
            self.assertTrue(run(pa, "a", ra)["ok"])
            self.assertTrue(run(pb, "b", rb)["ok"])
            self.assertTrue(run(pa, "a", ra)["ack"]["duplicate"])  # lost ACK, new process retry
            self.assertEqual(run(pa, "a", {**ra, "delivery": "stale"})["error"], "STALE_REVISION")
            current = restore(json.loads(pa.read_text()))
            missing = self.request(current, "axl", "missing", 2)
            missing["payload"] = missing["payload"].replace("^e0", "^absent")
            self.assertFalse(run(pa, "a", missing)["ok"])
            self.assertEqual(restore(json.loads(pa.read_text())), current)
            badrows = self.rows(2)
            badrows[1]["seq"] = 5
            for row in badrows:
                row["body"] = {"new": "Different evidence " * 20}
            badreq = {
                "delivery": "badstate",
                "expected_revision": current.task.revision,
                "format": "axl",
                "payload": axl_encode(
                    badrows, MESSAGE, ("task", "sender", "to"), scope="a", cache=current.cache
                )[0],
            }
            self.assertFalse(run(pa, "a", badreq)["ok"])
            self.assertEqual(restore(json.loads(pa.read_text())), current)
            valid = self.request(current, "axl", "next", 2)
            self.assertTrue(run(pa, "a", valid)["ok"])
            cross = self.request(restore(json.loads(pb.read_text())), "json", "cross", 2)
            # Matching outer revision but wrong inner dictionary scope/task stream.
            self.assertFalse(run(pa, "a", {**cross, "expected_revision": 2})["ok"])
            self.assertEqual(restore(json.loads(pb.read_text())).task.revision, 1)
        self.assertEqual(len(calls), 8)


if __name__ == "__main__":
    unittest.main()

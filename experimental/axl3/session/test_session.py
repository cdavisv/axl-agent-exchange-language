import unittest
from session import *


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.schema = Schema("session.example", (("value", "any", True),))
        self.wire = offer(self.schema, epoch="e1", alias="s0")
        self.binding, self.ack = accept_offer(
            self.wire,
            registry(self.schema),
            approved_schema=self.schema.fingerprint,
            approved_epoch="e1",
            approved_alias="s0",
            transport_session="connection1",
            authenticated_peer="peer1",
        )
        self.context = {"transport_session": "connection1", "authenticated_peer": "peer1"}

    def test_handshake_and_data(self):
        verify_ack(self.ack, self.binding, **self.context)
        for value in ["001", True, 1, 1.0, None, {"x": [1, "1"]}]:
            wire = encode([{"value": value}], self.binding, seq=0)
            state, rows, duplicate = receive(wire, self.binding, **self.context)
            self.assertEqual(dump(rows), dump([{"value": value}]))
            self.assertEqual(state.next_seq, 1)
            self.assertFalse(duplicate)
            self.assertEqual(self.binding.next_seq, 0)

    def test_explicit_control_same_semantics_and_replay(self):
        rows = [{"value": {"a": [1, True, "001"]}}]
        for sender, receiver in [(encode, receive), (encode_explicit, receive_explicit)]:
            wire = sender(rows, self.binding, seq=0)
            state, actual, duplicate = receiver(wire, self.binding, **self.context)
            self.assertEqual(dump(actual), dump(rows))
            self.assertFalse(duplicate)
            self.assertEqual(receiver(wire, state, **self.context), (state, [], True))
            with self.assertRaises(Error):
                receiver(sender(rows, state, seq=2), state, **self.context)
        full = load(encode_explicit(rows, self.binding, seq=0))
        full[1] = "0" * 64
        with self.assertRaises(Error):
            receive_explicit(dump(full), self.binding, **self.context)

    def test_retry_collision_and_gap(self):
        wire = encode([{"value": "a"}], self.binding, seq=0)
        state, _, _ = receive(wire, self.binding, **self.context)
        self.assertEqual(receive(wire, state, **self.context), (state, [], True))
        for seq in [0, 2]:
            with self.assertRaises(Error):
                receive(encode([{"value": "b"}], state, seq=seq), state, **self.context)

    def test_reconnect_requires_new_binding(self):
        wire = encode([{"value": 1}], self.binding, seq=0)
        with self.assertRaises(Error):
            receive(wire, self.binding, transport_session="connection2", authenticated_peer="peer1")
        new, _ = accept_offer(
            offer(self.schema, epoch="e2", alias="s0"),
            registry(self.schema),
            approved_schema=self.schema.fingerprint,
            approved_epoch="e2",
            approved_alias="s0",
            transport_session="connection2",
            authenticated_peer="peer1",
        )
        with self.assertRaises(Error):
            receive(wire, new, transport_session="connection2", authenticated_peer="peer1")
        result = receive(
            encode([{"value": 2}], new, seq=0),
            new,
            transport_session="connection2",
            authenticated_peer="peer1",
        )
        self.assertEqual(result[1], [{"value": 2}])

    def test_transport_and_ack_checks(self):
        for session, peer in [("wrong", "peer1"), ("connection1", "wrong")]:
            with self.assertRaises(Error):
                verify_ack(
                    self.ack, self.binding, transport_session=session, authenticated_peer=peer
                )
        obj = load(self.ack)
        for value in [True, 4]:
            altered = obj.copy()
            altered[1] = value
            with self.assertRaises(Error):
                verify_ack(dump(altered), self.binding, **self.context)

    def test_unapproved_and_unpinned(self):
        for schemas, alias in [(registry(), "s0"), (registry(self.schema), "wrong")]:
            with self.assertRaises(Error):
                accept_offer(
                    self.wire,
                    schemas,
                    approved_schema=self.schema.fingerprint,
                    approved_epoch="e1",
                    approved_alias=alias,
                    **self.context,
                )

    def test_malformed_atomicity(self):
        wire = encode([{"value": 1}], self.binding, seq=0)
        original = load(wire)
        for index, value in [
            (0, "e2"),
            (1, "s1"),
            (2, True),
            (2, -1),
            (2, 2**53),
            (3, {"9": 1}),
            (4, [[1, 2]]),
        ]:
            obj = original.copy()
            obj[index] = value
            with self.assertRaises(Error):
                receive(dump(obj), self.binding, **self.context)
            self.assertEqual(self.binding.next_seq, 0)

    def test_last_retry_only(self):
        first = encode([{"value": 0}], self.binding, seq=0)
        state, _, _ = receive(first, self.binding, **self.context)
        state, _, _ = receive(encode([{"value": 1}], state, seq=1), state, **self.context)
        with self.assertRaises(Error):
            receive(first, state, **self.context)

    def test_exhausted_sequence(self):
        state = replace(self.binding, next_seq=MAX_SEQ)
        state, _, _ = receive(encode([{"value": 1}], state, seq=MAX_SEQ), state, **self.context)
        with self.assertRaises(Error):
            encode([{"value": 2}], state, seq=state.next_seq)


if __name__ == "__main__":
    unittest.main()

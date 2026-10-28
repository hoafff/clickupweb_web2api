"""Synthetic-only tests for a one-owner / one-browser session lease."""
from concurrent.futures import ThreadPoolExecutor
import unittest

from tools.session_lease import (
    ExclusiveSessionLease,
    SessionAccessDeniedError,
    SessionAlreadyClaimedError,
    SessionNotClaimedError,
)


class ExclusiveLeaseTests(unittest.TestCase):
    def test_only_single_claim_and_constant_time_validation(self):
        lease = ExclusiveSessionLease()
        self.assertFalse(lease.has_owner())
        with self.assertRaises(SessionNotClaimedError):
            lease.check("anything")
        token = lease.claim()
        self.assertGreaterEqual(len(token), 32)
        self.assertTrue(lease.has_owner())
        lease.check(token)
        for value in ("", "bad", None, "x" * 300):
            with self.subTest(value=value):
                with self.assertRaises(SessionAccessDeniedError):
                    lease.check(value)
        with self.assertRaises(SessionAlreadyClaimedError):
            lease.claim()
        self.assertNotIn(token, vars(lease).__repr__().replace(
            "'_owner_secret': '" + token + "'", "'_owner_secret': '<private>'"
        ))

    def test_concurrent_claim_has_exactly_one_winner(self):
        lease = ExclusiveSessionLease()

        def try_claim(i: int):
            try:
                return ("ok", lease.claim())
            except SessionAlreadyClaimedError:
                return ("rejected", None)

        with ThreadPoolExecutor(max_workers=16) as pool:
            outcomes = list(pool.map(try_claim, range(40)))
        winners = [x for x in outcomes if x[0] == "ok"]
        self.assertEqual(len(winners), 1)
        self.assertEqual(
            sum(x[0] == "rejected" for x in outcomes), 39
        )
        lease.check(winners[0][1])


if __name__ == "__main__":
    unittest.main()

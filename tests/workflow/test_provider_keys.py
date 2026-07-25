"""One provider-key contract, proven against both drivers (bead 2afe.9).

A hosted user saves a model credential once and finds it on their next
device. The store that holds it is the same class over either driver -- a
SQLite file locally, libSQL when hosted -- for the reason the session catalog
is: one schema and one set of statements, so the two profiles cannot drift.

These tests exercise the store's public behaviour. What the bytes look like at
rest is a separate concern with its own tests, because "encrypted" is a claim
about the database, not about this interface.
"""

from __future__ import annotations

import base64
import os
import sqlite3
import tempfile
import unittest
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pydexpi_datalog.workflow.provider_keys import (
    CorruptProviderKey,
    ProviderKeyStore,
    libsql_provider_keys,
    local_provider_keys,
)

LIBSQL_URL_ENV_VAR = "PYDEXPI_LIBSQL_TEST_URL"
SECRET = b"0" * 32


@contextmanager
def _local_driver() -> Iterator[ProviderKeyStore]:
    with tempfile.TemporaryDirectory() as tmp:
        yield local_provider_keys(Path(tmp) / "keys.sqlite3", secret=SECRET)


@contextmanager
def _libsql_driver() -> Iterator[ProviderKeyStore]:
    """The real libSQL server, isolated by a per-test user id.

    Skipped rather than faked when no server is configured: a fake would
    prove the fake works. `tests/conftest.py` turns the skip into a failure
    under CI, where the server is supposed to be there.
    """

    url = os.environ.get(LIBSQL_URL_ENV_VAR, "").strip()
    if not url:
        raise unittest.SkipTest(f"{LIBSQL_URL_ENV_VAR} unset: nothing claimed")
    yield libsql_provider_keys(url=url, auth_token="", secret=SECRET)


DRIVERS = {"local-sqlite": _local_driver, "hosted-libsql": _libsql_driver}


def _user() -> str:
    return f"user-{uuid.uuid4().hex[:12]}"


class ProviderKeyContractTests(unittest.TestCase):
    """Behaviour every driver owes, whatever it talks to."""

    def _for_each_driver(self, check) -> None:
        ran = 0
        for name, driver in DRIVERS.items():
            with self.subTest(driver=name):
                with driver() as store:
                    check(store)
                ran += 1
        self.assertGreater(ran, 0, "no driver ran")

    def test_a_saved_credential_comes_back_usable(self) -> None:
        """The point of the store: the key returns as the key, not as a hash."""

        def check(store: ProviderKeyStore) -> None:
            user = _user()
            store.save(
                user_id=user, provider="openai", model="gpt-4.1", credential="sk-secret"
            )
            self.assertEqual("sk-secret", store.credential(user_id=user, provider="openai"))

        self._for_each_driver(check)

    def test_a_missing_credential_is_absent_rather_than_an_error(self) -> None:
        def check(store: ProviderKeyStore) -> None:
            self.assertIsNone(store.credential(user_id=_user(), provider="openai"))

        self._for_each_driver(check)

    def test_saving_again_replaces_rather_than_duplicates(self) -> None:
        def check(store: ProviderKeyStore) -> None:
            user = _user()
            store.save(user_id=user, provider="openai", model="gpt-4.1", credential="old")
            store.save(user_id=user, provider="openai", model="gpt-5.1", credential="new")
            self.assertEqual("new", store.credential(user_id=user, provider="openai"))
            saved = store.list_saved(user_id=user)
            self.assertEqual(1, len(saved), "replacing must not list twice")
            self.assertEqual("gpt-5.1", saved[0].model)

        self._for_each_driver(check)

    def test_deleting_removes_the_credential(self) -> None:
        def check(store: ProviderKeyStore) -> None:
            user = _user()
            store.save(user_id=user, provider="openai", model="gpt-4.1", credential="sk")
            self.assertTrue(store.delete(user_id=user, provider="openai"))
            self.assertIsNone(store.credential(user_id=user, provider="openai"))
            self.assertEqual([], store.list_saved(user_id=user))

        self._for_each_driver(check)

    def test_deleting_what_was_never_there_reports_it(self) -> None:
        """A caller can tell a delete from a no-op, so an API can answer 404."""

        def check(store: ProviderKeyStore) -> None:
            self.assertFalse(store.delete(user_id=_user(), provider="openai"))

        self._for_each_driver(check)

    def test_one_user_never_sees_another_users_credential(self) -> None:
        """The isolation rule of the whole hosted epic, at this seam."""

        def check(store: ProviderKeyStore) -> None:
            mine, theirs = _user(), _user()
            store.save(user_id=mine, provider="openai", model="gpt-4.1", credential="mine")
            store.save(
                user_id=theirs, provider="openai", model="gpt-4.1", credential="theirs"
            )
            self.assertEqual("mine", store.credential(user_id=mine, provider="openai"))
            self.assertEqual(
                [], [s for s in store.list_saved(user_id=mine) if s.provider != "openai"]
            )
            self.assertNotIn(
                "theirs",
                [store.credential(user_id=mine, provider="openai")],
            )

        self._for_each_driver(check)

    def test_a_user_keeps_one_credential_per_provider(self) -> None:
        def check(store: ProviderKeyStore) -> None:
            user = _user()
            store.save(user_id=user, provider="openai", model="gpt-4.1", credential="a")
            store.save(
                user_id=user, provider="anthropic", model="claude-sonnet-4-5", credential="b"
            )
            self.assertEqual("a", store.credential(user_id=user, provider="openai"))
            self.assertEqual("b", store.credential(user_id=user, provider="anthropic"))
            self.assertEqual(
                ["anthropic", "openai"],
                sorted(s.provider for s in store.list_saved(user_id=user)),
            )

        self._for_each_driver(check)

    def test_listing_describes_a_key_without_disclosing_it(self) -> None:
        """What a settings page needs: enough to recognise, never enough to use."""

        def check(store: ProviderKeyStore) -> None:
            user = _user()
            store.save(
                user_id=user,
                provider="openai",
                model="gpt-4.1",
                credential="sk-abcdefghijklmnop",
            )
            [saved] = store.list_saved(user_id=user)
            self.assertEqual("openai", saved.provider)
            self.assertEqual("gpt-4.1", saved.model)
            self.assertNotIn("abcdefghijklmnop", saved.hint)
            self.assertNotIn("abcdefghijklmnop", repr(saved))
            self.assertTrue(saved.saved_at)

        self._for_each_driver(check)


class EncryptionAtRestTests(unittest.TestCase):
    """What is actually in the database, checked by reading the database.

    The interface tests above would pass identically if `save` wrote the key
    in plaintext, because they only ever read it back through the same
    object. "Encrypted at rest" is a claim about the row, so these read the
    row. The local SQLite driver is used because it can be opened with the
    standard library; the schema and the sealing code are shared, so what is
    true of one driver's bytes is true of the other's.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "keys.sqlite3"
        self.store = local_provider_keys(self.path, secret=SECRET)

    def _rows(self) -> list[tuple]:
        with sqlite3.connect(self.path) as connection:
            return connection.execute("SELECT * FROM provider_key").fetchall()

    def test_the_credential_is_not_in_the_database_in_any_readable_form(self) -> None:
        secret_key = "sk-do-not-store-me-in-the-clear"
        self.store.save(
            user_id="alice", provider="openai", model="gpt-4.1", credential=secret_key
        )
        on_disk = self.path.read_bytes()
        self.assertNotIn(secret_key.encode(), on_disk)
        # Not merely absent as one string: no run of the key survives either.
        self.assertNotIn(b"do-not-store-me", on_disk)
        self.assertNotIn(base64.b64encode(secret_key.encode()), on_disk)

    def test_the_stored_columns_carry_no_key_material(self) -> None:
        """Everything except the sealed blob is readable, so it must be safe."""

        self.store.save(
            user_id="alice",
            provider="openai",
            model="gpt-4.1",
            credential="sk-abcdefghijklmnop",
        )
        [row] = self._rows()
        readable = [value for value in row if "abcdefghijklmnop" in str(value)]
        self.assertEqual([], readable, "a column disclosed the key")

    def test_the_same_key_saved_twice_does_not_produce_the_same_ciphertext(self) -> None:
        """A fresh nonce each time: equal ciphertexts would leak equal keys."""

        self.store.save(user_id="a", provider="openai", model="m", credential="same")
        self.store.save(user_id="b", provider="openai", model="m", credential="same")
        sealed = {row[4] for row in self._rows()}
        self.assertEqual(2, len(sealed))

    def test_a_row_moved_to_another_user_does_not_decrypt(self) -> None:
        """The isolation rule survives write access to the database itself.

        Someone who can edit rows -- a bug in a query, an operator, an
        attacker with the database but not the secret -- cannot hand
        themselves a working key by renaming its owner.
        """

        self.store.save(
            user_id="alice", provider="openai", model="gpt-4.1", credential="sk-alice"
        )
        with sqlite3.connect(self.path) as connection:
            connection.execute("UPDATE provider_key SET user_id = 'mallory'")
        with self.assertRaises(CorruptProviderKey):
            self.store.credential(user_id="mallory", provider="openai")

    def test_a_row_moved_to_another_provider_does_not_decrypt(self) -> None:
        """A key for one provider must not become a key for another."""

        self.store.save(
            user_id="alice", provider="openai", model="gpt-4.1", credential="sk-alice"
        )
        with sqlite3.connect(self.path) as connection:
            connection.execute("UPDATE provider_key SET provider = 'anthropic'")
        with self.assertRaises(CorruptProviderKey):
            self.store.credential(user_id="alice", provider="anthropic")

    def test_a_tampered_ciphertext_is_refused_rather_than_returned(self) -> None:
        self.store.save(
            user_id="alice", provider="openai", model="gpt-4.1", credential="sk-alice"
        )
        [row] = self._rows()
        flipped = base64.b64decode(row[4])
        flipped = flipped[:-1] + bytes([flipped[-1] ^ 0x01])
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "UPDATE provider_key SET ciphertext = ?",
                (base64.b64encode(flipped).decode("ascii"),),
            )
        with self.assertRaises(CorruptProviderKey):
            self.store.credential(user_id="alice", provider="openai")

    def test_another_deployments_secret_cannot_read_these_keys(self) -> None:
        """Rotating or mis-setting the secret fails loudly, not silently."""

        self.store.save(
            user_id="alice", provider="openai", model="gpt-4.1", credential="sk-alice"
        )
        other = local_provider_keys(self.path, secret=b"1" * 32)
        with self.assertRaises(CorruptProviderKey):
            other.credential(user_id="alice", provider="openai")

    def test_the_failure_message_does_not_quote_the_key_or_the_user(self) -> None:
        """This error reaches a log, and a log is where a key must never be."""

        self.store.save(
            user_id="alice", provider="openai", model="gpt-4.1", credential="sk-alice"
        )
        other = local_provider_keys(self.path, secret=b"1" * 32)
        with self.assertRaises(CorruptProviderKey) as caught:
            other.credential(user_id="alice", provider="openai")
        message = str(caught.exception)
        self.assertNotIn("sk-alice", message)
        self.assertNotIn("alice", message)

    def test_a_secret_of_the_wrong_size_is_refused_at_construction(self) -> None:
        """Fail where the mistake is, not on the first user who saves a key."""

        with self.assertRaises(ValueError) as caught:
            local_provider_keys(self.path, secret=b"too-short")
        self.assertIn("32", str(caught.exception))


if __name__ == "__main__":
    unittest.main()

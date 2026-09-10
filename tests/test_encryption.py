"""
tests/test_encryption.py
Tests for security/encryption.py — the shared Fernet encrypt/decrypt helper
used by api/routes/workspaces.py's BYOK key storage.

What this file validates:
  - encrypt() -> decrypt() round-trips the original value
  - encrypt() never returns the plaintext value
  - decrypt() of garbage ciphertext raises (never silently returns junk)
  - missing ENCRYPTION_KEY raises EnvironmentError instead of failing later
"""

from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet, InvalidToken

from security import encryption


@pytest.fixture(autouse=True)
def _encryption_key():
    key = Fernet.generate_key().decode()
    with patch.dict("os.environ", {"ENCRYPTION_KEY": key}):
        yield key


class TestEncryptDecrypt:
    def test_round_trip(self):
        ciphertext = encryption.encrypt("sk-ant-api03-realkey")
        assert encryption.decrypt(ciphertext) == "sk-ant-api03-realkey"

    def test_ciphertext_is_not_plaintext(self):
        ciphertext = encryption.encrypt("sk-ant-api03-realkey")
        assert ciphertext != "sk-ant-api03-realkey"
        assert "sk-ant-api03-realkey" not in ciphertext

    def test_decrypt_garbage_raises(self):
        with pytest.raises(InvalidToken):
            encryption.decrypt("not-a-real-fernet-token")


class TestMissingKey:
    def test_encrypt_without_key_raises(self):
        with patch.dict("os.environ", {"ENCRYPTION_KEY": ""}):
            with pytest.raises(EnvironmentError):
                encryption.encrypt("value")

    def test_decrypt_without_key_raises(self):
        with patch.dict("os.environ", {"ENCRYPTION_KEY": ""}):
            with pytest.raises(EnvironmentError):
                encryption.decrypt("value")

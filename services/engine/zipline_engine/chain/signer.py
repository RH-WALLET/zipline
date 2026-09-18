"""Local transaction signer. The private key never leaves this process and is never logged."""

from __future__ import annotations

from typing import Any


class SignerNotConfiguredError(RuntimeError):
    pass


class LocalSigner:
    def __init__(self, private_key: str) -> None:
        if not private_key:
            raise SignerNotConfiguredError("EXECUTOR_PRIVATE_KEY is not set")
        from eth_account import Account

        try:
            self._account = Account.from_key(private_key)
        except Exception as e:
            raise SignerNotConfiguredError(
                "EXECUTOR_PRIVATE_KEY is not a valid 32-byte hex key"
            ) from e

    @property
    def address(self) -> str:
        return str(self._account.address)

    def sign(self, tx: dict[str, Any]) -> bytes:
        signed = self._account.sign_transaction(tx)
        raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
        return bytes(raw)

    def __repr__(self) -> str:  # never reveal key material
        return f"LocalSigner(address={self.address})"

    __str__ = __repr__

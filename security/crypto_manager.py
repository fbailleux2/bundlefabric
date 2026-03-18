"""BundleFabric — Bundle cryptographic signing (ed25519) + SHA-256 hashing."""
from __future__ import annotations

import base64
import hashlib
import os
import pathlib
from typing import Dict

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_private_key,
    load_pem_public_key,
)

_SECRETS_DIR = pathlib.Path(
    os.getenv("USERS_FILE", "/app/secrets_vault/users.json")
).parent
_KEYS_DIR = _SECRETS_DIR / "node_keys"


class BundleCryptoManager:
    """Manages ed25519 node keypair and bundle signing/verification."""

    def __init__(self, keys_dir: pathlib.Path | None = None):
        self.keys_dir = keys_dir or _KEYS_DIR
        self._private_key_path = self.keys_dir / "node_private.pem"
        self._public_key_path = self.keys_dir / "node_public.pem"

    # ── Keypair ────────────────────────────────────────────────────────────────

    def generate_node_keypair(self) -> Dict[str, str]:
        """Generate ed25519 keypair for this node. Overwrites existing keys."""
        self.keys_dir.mkdir(parents=True, exist_ok=True)
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()

        # Write private key (PEM, permissions 600)
        priv_pem = private_key.private_bytes(
            encoding=Encoding.PEM,
            format=PrivateFormat.PKCS8,
            encryption_algorithm=NoEncryption(),
        )
        self._private_key_path.write_bytes(priv_pem)
        self._private_key_path.chmod(0o600)

        # Write public key (PEM, readable)
        pub_pem = public_key.public_bytes(
            encoding=Encoding.PEM,
            format=PublicFormat.SubjectPublicKeyInfo,
        )
        self._public_key_path.write_bytes(pub_pem)
        self._public_key_path.chmod(0o644)

        node_id = self.get_node_id()
        print(f"[Crypto] Node keypair generated. node_id={node_id}")
        return {
            "private_key_path": str(self._private_key_path),
            "public_key_path": str(self._public_key_path),
            "node_id": node_id,
        }

    def get_node_id(self) -> str:
        """Return first 16 hex chars of public key SHA-256 fingerprint."""
        if not self._public_key_path.exists():
            return "unsigned-node"
        pub_bytes = self._public_key_path.read_bytes()
        return hashlib.sha256(pub_bytes).hexdigest()[:16]

    def _load_private_key(self) -> Ed25519PrivateKey:
        if not self._private_key_path.exists():
            raise FileNotFoundError(
                f"Private key not found at {self._private_key_path}. "
                "Run generate_node_keypair() first."
            )
        return load_pem_private_key(self._private_key_path.read_bytes(), password=None)  # type: ignore

    def _load_public_key(self, public_key_path: pathlib.Path | None = None) -> Ed25519PublicKey:
        p = public_key_path or self._public_key_path
        return load_pem_public_key(p.read_bytes())  # type: ignore

    # ── Hashing ────────────────────────────────────────────────────────────────

    def hash_bundle(self, bundle_path: pathlib.Path) -> str:
        """Return SHA-256 hex digest of the bundle's manifest.yaml."""
        manifest = bundle_path / "manifest.yaml"
        if not manifest.exists():
            raise ValueError(f"manifest.yaml not found in {bundle_path}")
        return hashlib.sha256(manifest.read_bytes()).hexdigest()

    # ── Signing ────────────────────────────────────────────────────────────────

    def sign_bundle(self, bundle_path: pathlib.Path) -> str:
        """Sign bundle's manifest.yaml with node private key. Returns hex signature."""
        manifest = bundle_path / "manifest.yaml"
        if not manifest.exists():
            raise ValueError(f"manifest.yaml not found in {bundle_path}")

        manifest_hash = hashlib.sha256(manifest.read_bytes()).digest()
        private_key = self._load_private_key()
        raw_sig = private_key.sign(manifest_hash)

        # Write base64 signature to bundle/signatures/bundle.sig
        sig_dir = bundle_path / "signatures"
        sig_dir.mkdir(exist_ok=True)
        sig_b64 = base64.b64encode(raw_sig).decode()
        (sig_dir / "bundle.sig").write_text(sig_b64)

        print(f"[Crypto] Bundle signed: {bundle_path.name}")
        return raw_sig.hex()

    # ── Verification ───────────────────────────────────────────────────────────

    def verify_bundle(
        self,
        bundle_path: pathlib.Path,
        public_key_path: pathlib.Path | None = None,
    ) -> bool:
        """Verify bundle signature against public key. Returns True if valid."""
        sig_file = bundle_path / "signatures" / "bundle.sig"
        manifest = bundle_path / "manifest.yaml"

        if not sig_file.exists() or not manifest.exists():
            return False

        try:
            raw_sig = base64.b64decode(sig_file.read_text().strip())
            manifest_hash = hashlib.sha256(manifest.read_bytes()).digest()
            public_key = self._load_public_key(public_key_path)
            public_key.verify(raw_sig, manifest_hash)
            return True
        except Exception:
            return False

    def is_bundle_signed(self, bundle_path: pathlib.Path) -> bool:
        """Quick check: returns True if bundle has a signature file."""
        return (bundle_path / "signatures" / "bundle.sig").exists()

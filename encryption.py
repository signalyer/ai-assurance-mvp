"""Encryption utilities for HIPAA/SOC2 compliance."""

import os
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2
from cryptography.hazmat.backends import default_backend
import base64
from dotenv import load_dotenv

load_dotenv()


class EncryptionManager:
    """Manages encryption/decryption of sensitive data."""

    def __init__(self, master_key: str = None):
        """Initialize with master encryption key."""
        if master_key is None:
            master_key = os.getenv("ENCRYPTION_KEY")

        if not master_key:
            raise ValueError(
                "ENCRYPTION_KEY not found in environment. "
                "Generate with: python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\""
            )

        self.cipher = Fernet(master_key.encode())

    def encrypt(self, plaintext: str) -> str:
        """Encrypt sensitive data (returns base64 string)."""
        if not plaintext:
            return ""
        encrypted = self.cipher.encrypt(plaintext.encode())
        return base64.b64encode(encrypted).decode()

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt sensitive data."""
        if not ciphertext:
            return ""
        try:
            encrypted = base64.b64decode(ciphertext.encode())
            decrypted = self.cipher.decrypt(encrypted)
            return decrypted.decode()
        except Exception as e:
            raise ValueError(f"Decryption failed: {e}")

    @staticmethod
    def generate_key() -> str:
        """Generate a new encryption key for setup."""
        return Fernet.generate_key().decode()


class PII_Encryptor:
    """Encrypt specific PII fields for HIPAA compliance."""

    def __init__(self):
        self.manager = EncryptionManager()

    def encrypt_email(self, email: str) -> str:
        """Encrypt email address."""
        return self.manager.encrypt(email)

    def encrypt_ssn(self, ssn: str) -> str:
        """Encrypt SSN (###-##-####)."""
        return self.manager.encrypt(ssn)

    def encrypt_phone(self, phone: str) -> str:
        """Encrypt phone number."""
        return self.manager.encrypt(phone)

    def encrypt_account_number(self, account: str) -> str:
        """Encrypt account/card number."""
        return self.manager.encrypt(account)

    def encrypt_health_data(self, health_info: str) -> str:
        """Encrypt health-related information (diagnoses, medications, etc)."""
        return self.manager.encrypt(health_info)

    @staticmethod
    def mask_pii(text: str) -> str:
        """Mask PII in logs (doesn't encrypt, just hides)."""
        import re

        # Mask emails
        text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL]', text)

        # Mask SSNs
        text = re.sub(r'\b\d{3}-\d{2}-\d{4}\b', '[SSN]', text)

        # Mask phone numbers
        text = re.sub(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', '[PHONE]', text)

        # Mask account numbers
        text = re.sub(r'\b[A-Z]+-\d{6,}\b', '[ACCOUNT]', text)

        # Mask credit card numbers
        text = re.sub(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b', '[CARD]', text)

        return text


def encrypt_sensitive_fields(data: dict) -> dict:
    """Encrypt sensitive fields in a dictionary."""
    encryptor = PII_Encryptor()
    encrypted = data.copy()

    # Fields to encrypt
    sensitive_fields = {
        'email': encryptor.encrypt_email,
        'ssn': encryptor.encrypt_ssn,
        'phone': encryptor.encrypt_phone,
        'account_number': encryptor.encrypt_account_number,
        'health_data': encryptor.encrypt_health_data,
    }

    for field, encrypt_func in sensitive_fields.items():
        if field in encrypted and encrypted[field]:
            encrypted[field] = encrypt_func(encrypted[field])

    return encrypted


def mask_for_logging(text: str) -> str:
    """Remove PII from text before logging."""
    return PII_Encryptor.mask_pii(text)


if __name__ == "__main__":
    print("Encryption utilities test...")

    # Generate a test key if needed
    try:
        manager = EncryptionManager()
    except ValueError:
        print("No ENCRYPTION_KEY found. Generating...")
        key = EncryptionManager.generate_key()
        print(f"Add this to your .env file:")
        print(f"ENCRYPTION_KEY={key}")
        manager = EncryptionManager(key)

    # Test encryption/decryption
    plaintext = "john.doe@example.com"
    encrypted = manager.encrypt(plaintext)
    decrypted = manager.decrypt(encrypted)

    print(f"✓ Original:  {plaintext}")
    print(f"✓ Encrypted: {encrypted[:20]}...")
    print(f"✓ Decrypted: {decrypted}")
    assert plaintext == decrypted, "Encryption failed!"

    # Test PII encryption
    encryptor = PII_Encryptor()
    ssn = "123-45-6789"
    encrypted_ssn = encryptor.encrypt_ssn(ssn)
    print(f"✓ SSN encrypted: {ssn} → {encrypted_ssn[:20]}...")

    # Test masking
    text = "Call me at 555-123-4567 or email john@example.com"
    masked = mask_for_logging(text)
    print(f"✓ Original: {text}")
    print(f"✓ Masked:   {masked}")

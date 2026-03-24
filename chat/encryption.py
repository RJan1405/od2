import base64
from django.conf import settings
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from Crypto.Random import get_random_bytes

MAGIC_PREFIX = 'odnix_enc::'

def get_encryption_key():
    key = getattr(settings, 'DB_ENCRYPTION_KEY', settings.SECRET_KEY)[:32]
    if isinstance(key, str):
        key = key.encode('utf-8')
    return key.ljust(32, b'\0')[:32]

def encrypt_text(value):
    if not value:
        return value
    if isinstance(value, str) and value.startswith(MAGIC_PREFIX):
        return value
        
    try:
        iv = get_random_bytes(AES.block_size)
        cipher = AES.new(get_encryption_key(), AES.MODE_CBC, iv)
        ciphertext = cipher.encrypt(pad(str(value).encode('utf-8'), AES.block_size))
        return MAGIC_PREFIX + base64.b64encode(iv + ciphertext).decode('utf-8')
    except Exception:
        return value

def decrypt_text(value):
    if not value or not isinstance(value, str):
        return value
    if value.startswith(MAGIC_PREFIX):
        try:
            data = base64.b64decode(value[len(MAGIC_PREFIX):])
            iv = data[:AES.block_size]
            ciphertext = data[AES.block_size:]
            cipher = AES.new(get_encryption_key(), AES.MODE_CBC, iv)
            decrypted = unpad(cipher.decrypt(ciphertext), AES.block_size)
            return decrypted.decode('utf-8')
        except Exception:
            return "[Encrypted Message - Unable to decrypt]"
    return value

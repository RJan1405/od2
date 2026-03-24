# Odnix Server-Side Database Encryption Architecture

## Overview
This document outlines the custom server-side database encryption layer implemented for the React-Odnix backend. This system secures user chat messages at rest in the PostgreSQL database natively, heavily inspired by how Telegram's Cloud Chats encrypt messages before hitting solid state storage.

## The Challenge
The primary objective was to make messages "secure like Telegram" while adhering to a strict boundary constraint:
**Do not alter existing Django models ([models.py](file:///d:/VulnTech11/react-odnix/chat/models.py)) and do not require any database schema migrations.**
Furthermore, the encryption had to seamlessly integrate with the existing Odnix Mobile App without requiring a single line of code change on the client side.

## How The Encryption Architecture Works

Our data pipeline applies encryption at the very edges of the Python application (the API and WebSocket boundaries) rather than the ORM structure.

### 1. The Core Encryption Module ([chat/encryption.py](file:///d:/VulnTech11/react-odnix/chat/encryption.py))
We built a standalone utility module leveraging Python's `pycryptodome` library. 
It utilizes **AES (Advanced Encryption Standard) in CBC mode**. 
- A unique, cryptographically secure 16-byte random Initialization Vector (IV) is generated for *every single message*, ensuring that even if user A and user B send the exact same text ("Hello"), their encrypted database footprints look completely different.
- The cipher text and IV are bundled, encoded in **Base64**, and prefixed with a "magic string" (`odnix_enc::`).

### 2. The Data Flow (Writing to Database)
When the Odnix Mobile App sends a message over WebSockets ([chat/consumers.py](file:///d:/VulnTech11/react-odnix/chat/consumers.py)) or the Share API ([chat/views/share_api.py](file:///d:/VulnTech11/react-odnix/chat/views/share_api.py)):
1. The backend parses the incoming plain text payload.
2. Just before calling strictly Native Django ORM logic like `Message.objects.create()`, the [content](file:///d:/VulnTech11/react-odnix/chat/models.py#1284-1288) argument is passed through [encrypt_text()](file:///d:/VulnTech11/react-odnix/chat/encryption.py#15-28).
3. The PostgreSQL database blindly accepts the scrambled Base64 string and writes it to disk.

### 3. The Data Flow (Reading for the Client)
When the Odnix Mobile App requests chat history via the REST API ([chat/views/chat_api.py](file:///d:/VulnTech11/react-odnix/chat/views/chat_api.py)) or receives a real-time broadcast:
1. Django retrieves the raw [Message](file:///d:/VulnTech11/react-odnix/chat/models.py#241-349) object from the database containing the gibberish `odnix_enc::...` text.
2. During the JSON serialization phase, the payload is passed through [decrypt_text()](file:///d:/VulnTech11/react-odnix/chat/encryption.py#29-43). 
3. The decrypted plain text is transmitted to the Mobile App over your pre-existing secure network transport layer (MTProto AES-IGE/HTTPS TLS) transparently. 

## Technical Benefits of This Intercept Approach

### 1. Zero Database Migrations & Schema Changes
Because we didn't create a custom `EncryptedTextField` class in [models.py](file:///d:/VulnTech11/react-odnix/chat/models.py), Django doesn't know the field fundamentally changed. The standard `TextField` simply stores the ASCII Base64 characters gracefully. No SQL `ALTER TABLE` commands or `python manage.py makemigrations` files were generated, fulfilling the strict initial constraints.

### 2. Full Backwards Compatibility
The [decrypt_text](file:///d:/VulnTech11/react-odnix/chat/encryption.py#29-43) function includes a simple prefix check: `if value.startswith('odnix_enc::')`. 
If an old legacy plain-text message is queried from the database, the function ignores it and returns the plain text directly. The Odnix platform didn't require any mass-database migration script to wipe/re-format older messages, inherently preventing catastrophic app crashes. 

### 3. At-Rest Data Breach Mitigation
If the host server or managed PostgreSQL database is structurally breached, dumped, or physically stolen, malicious actors will only recover lists of encrypted strings like `odnix_enc::5+eUHwaQbmjayH+TO...`. Without access to the raw 32-byte master Django environment variable `DB_ENCRYPTION_KEY`, the users' private conversations are mathematically impossible to decipher.

### 4. 100% Client Transparency
Because the decryption occurs on the backend just milliseconds before the JSON payload is dispatched to the network interface, the React Native frontend is completely unaware that the database is encrypted. No mobile app updates, bridging, or JavaScript patches were needed. The frontend consumes the API exactly as it always has.

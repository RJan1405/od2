import os
import django

# Setup django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'odnix.settings')
django.setup()

from chat.models import CustomUser, Chat, Message
from chat.encryption import encrypt_text, decrypt_text

def run_test():
    print("--- REAL USER ENCRYPTION TEST START ---\n")
    
    # 1. Grab TWO REAL users from the database. 
    # If the database is empty, create fallback accounts.
    users = CustomUser.objects.filter(is_active=True)[:2]
    
    if len(users) < 2:
        print("Creating dummy users for the test because there aren't 2 active users in DB...")
        user1, _ = CustomUser.objects.get_or_create(username='tester_alpha', defaults={'name': 'Alpha', 'lastname': 'Test'})
        user2, _ = CustomUser.objects.get_or_create(username='tester_beta', defaults={'name': 'Beta', 'lastname': 'Test'})
    else:
        user1 = users[0]
        user2 = users[1]
        
    print(f"Testing with User 1: @{user1.username} and User 2: @{user2.username}")
        
    # 2. Get or create a private chat between them
    chat = Chat.objects.filter(chat_type='private', participants=user1).filter(participants=user2).first()
    if not chat:
        print("... Creating a new private chat bridging the two users...")
        chat = Chat.objects.create(chat_type='private')
        chat.participants.add(user1, user2)
    else:
        print(f"... Found existing chat (ID: {chat.id}) between them...")

    # 3. Simulate mobile app client sending a plain text message
    original_plain_text = "🔒 Hello! This is a real database test message for React-ODNix!"
    print(f"\n[MOBILE APP SENDS WS PAYLOAD] -> {original_plain_text}")
    
    # The consumers.py encrypts the text right before hitting the ORM
    encrypted_text_for_db = encrypt_text(original_plain_text)
    print(f"[BACKEND ENCRYPTS IT] -> {encrypted_text_for_db}")
    
    # Hit the DB
    msg = Message.objects.create(
        chat=chat,
        sender=user1,
        content=encrypted_text_for_db,
    )
    print(f"\n=> PostgreSQL Record written successfully! (Message ID: {msg.id})")
    
    # 4. Pull the raw row back out mimicking a hacker or the raw REST API query
    raw_db_record = Message.objects.get(id=msg.id)
    print(f"\n[RAW DATABASE QUERY] -> {raw_db_record.content}")
    
    if not raw_db_record.content.startswith('odnix_enc::'):
        print("ERROR: Oh no, it saved as plain text!")
        return
        
    # 5. Read back through the decrypt layer as chat_api.py does
    decrypted_text_for_api = decrypt_text(raw_db_record.content)
    print(f"[API DECRYPTS IT BEFORE SEND] -> {decrypted_text_for_api}")
    
    if decrypted_text_for_api == original_plain_text:
        print("\n🎉 SUCCESS! Messages are stored scrambled in the DB but displayed perfectly in the Mobile App!")
    else:
        print("\n❌ FAILURE! Decryption anomaly detected.")

if __name__ == "__main__":
    run_test()

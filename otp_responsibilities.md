# 🔑 Who Handles What? (Firebase vs. Django)

Since we have switched from Twilio to Firebase, the responsibilities for registration and OTP have been split into two distinct roles:

---

## 🛡 **Firebase (The Security Guard)**
**Role:** Verification & Identity
Firebase is the "Security Guard" that stands at the front door.

1.  **Generates the OTP**: Firebase creates the 6-digit code.
2.  **Sends the SMS**: Firebase sends the 6-digit code via SMS to your phone.
3.  **Verifies the Code**: When you type the 6th digit, Firebase checks if it is correct.
4.  **Issues the Badge (IdToken)**: Once the code is correct, Firebase gives your phone a secure "Success Badge" (an IdToken).

> **Django never sees the secret code.** This is more secure because the 6-digit OTP never travels across your server.

---

## 📘 **Django (The Librarian)**
**Role:** Database & User Records
Django is the "Librarian" who manages the books (users).

1.  **Availability Check**: Before you even get an OTP, Django checks the database to make sure your name, email, and number aren't already taken by someone else.
2.  **Verify the "Badge"**: When you finish the OTP, the app sends the "Success Badge" (IdToken) from Firebase to Django. Django then asks Firebase, *"Is this badge real?"*
3.  **Creates the User**: Once Firebase says *"Yes, the badge is real,"* Django finally creates your account in the official Postgres database.

---

## 🏁 Summary Table

| Action | Who Does it? |
| :--- | :--- |
| **Create 6-digit code** | 🟢 Firebase |
| **Send SMS** | 🟢 Firebase |
| **Check if code is correct** | 🟢 Firebase |
| **Give "Success Token" to App** | 🟢 Firebase |
| **Check if username is taken** | 🍎 Django |
| **Verify the "Success Token"** | 🍎 Django |
| **Save user in database** | 🍎 Django |

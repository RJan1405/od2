# Odnix - Firebase OTP Registration Flow

The registration process in Odnix is designed for security and reliability. It combines Firebase's robust phone authentication with a Django backend for secure user state management.

---

## 🏗 High-Level Workflow

### 1. User Input and Validation
The process begins on the **Signup Screen**, where the user provides their details:
- **Username**, **Email**, **Password**, **Full Name**, and **Phone Number**.
- The phone number is automatically formatted into **E.164 format** (e.g., `+1234567890`) for Firebase compatibility.

### 2. Pre-OTP Availability Check (NEW)
Before sending an SMS (saving costs and avoiding redundant steps), the app calls the Backend API:
- **API Endpoint**: `POST /api/check-availability/`
- **Logic**: The Django server checks if the username, email, or phone number already exists in the database.
- **Result**: If any field is taken, the user gets an immediate alert on the Signup Screen and stays on the page.

### 3. SMS OTP Generation
Once validated, the app triggers the **Firebase Auth SDK**:
- **Call**: `auth().signInWithPhoneNumber(phone)`
- **Behavior**: Firebase sends a 6-digit verification code to the user's mobile device.
- **State**: The app stores the `confirmationResult` and navigates the user to the **OTP Screen**.

### 4. OTP Verification (Client)
On the **OTP Screen**, the user enters the 6-digit code:
- **Race Condition Handling**: The app passes the 6-digit code directly to the verification function instead of relying on asynchronous state updates, ensuring zero failure on the "6th digit".
- **Verification**: The app calls `confirmation.confirm(otpCode)`. 
- **IdToken**: Upon successful verification, Firebase returns an **IdToken** (a secure, signed JWT) which proves the user owns that phone number.

### 5. Final Registration (Backend Handshake)
The app sends the final payload to the server:
- **API Endpoint**: `POST /api/firebase-register/`
- **Payload**: Includes the `idToken` and the previously gathered user data (`registrationData`).
- **Backend Verification**: Django uses the **Firebase Admin SDK** to verify the `idToken` directly with Google's servers. This returns the verified phone number.
- **User Creation**: Django creates the `CustomUser` using the verified phone number and saves the hashed password.
- **Session**: A Django DRF **Authentication Token** is generated and returned to the client to complete the login.

---

## 🛡 Security Benefits

1. **Identity Integrity**: The backend only trusts phone numbers verified by Google via the signed `idToken`, preventing spoofing.
2. **Cost Efficiency**: Pre-check prevents sending SMS codes for users who cannot register anyway (e.g., duplicate usernames).
3. **Decoupled Architecture**: Twilio has been removed to reduce complexity. Firebase handles the sensitive SMS delivery layer, while Django focuses on business logic and data persistence.

---

## 🛠 Relevant Files
- **Frontend**: [OTPScreen.tsx](file:///d:/VulnTech11/odnix-mobile/src/screens/Auth/OTPScreen.tsx), [SignupScreen.tsx](file:///d:/VulnTech11/odnix-mobile/src/screens/Auth/SignupScreen.tsx), [authStore.ts](file:///d:/VulnTech11/odnix-mobile/src/stores/authStore.ts)
- **Backend**: [api_auth.py](file:///d:/VulnTech11/react-odnix/chat/views/api_auth.py), [urls.py](file:///d:/VulnTech11/react-odnix/chat/urls.py), [settings.py](file:///d:/VulnTech11/react-odnix/odnix/settings.py)

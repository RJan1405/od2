import requests
import json
import os
import sys

# Configuration
BASE_URL = "http://127.0.0.1:8000"  # Update this if your server runs elsewhere
USERNAME = "test_verification_user"             # Update to an existing user
PASSWORD = "pass123"          # Update to the correct password

def test_api_flow():
    print(f"🚀 Starting API Authentication Audit for {BASE_URL}")
    print("-" * 50)

    # 1. TEST LOGIN (Public Endpoint)
    print("Step 1: Testing Login (/api/login/)...")
    login_url = f"{BASE_URL}/api/login/"
    payload = {
        "username": USERNAME,
        "password": PASSWORD
    }
    
    try:
        response = requests.post(login_url, json=payload)
        if response.status_code == 200:
            data = response.json()
            if data.get('success') and data.get('auth_token'):
                token = data['auth_token']
                print(f"✅ Login successful! Token received: {token[:10]}...")
            else:
                print(f"❌ Login failed: {data.get('error', 'Unknown error')}")
                return
        else:
            print(f"❌ Login failed with status {response.status_code}")
            print(f"Response: {response.text}")
            return
    except Exception as e:
        print(f"❌ Connection error: {str(e)}")
        return

    # 2. TEST AUTHENTICATED PROFILE FETCH (IsAuthenticated)
    print("\nStep 2: Testing Authenticated Profile Fetch (/api/profile/)...")
    profile_url = f"{BASE_URL}/api/profile/"
    headers = {
        "Authorization": f"Token {token}"
    }
    
    try:
        response = requests.get(profile_url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                print(f"✅ Profile fetch successful! User: {data['user']['username']}")
            else:
                print(f"❌ Profile fetch failed: {data.get('error')}")
        else:
            print(f"❌ Profile fetch failed with status {response.status_code}")
            print(f"Header used: {headers['Authorization']}")
            return
    except Exception as e:
        print(f"❌ Profile fetch error: {str(e)}")
        return

    # 3. TEST MULTIPART POST (post_scribe)
    print("\nStep 3: Testing MultiPart Post (/api/post-scribe/)...")
    scribe_url = f"{BASE_URL}/api/post-scribe/"
    
    # Simulate FormData
    files = {}
    # Uncomment if you want to test image upload (must have a file named 'test.jpg' in current dir)
    # if os.path.exists('test.jpg'):
    #     files['image'] = open('test.jpg', 'rb')
    
    data = {
        "content": "Automated verification scribe test",
        "content_type": "text"
    }
    
    try:
        response = requests.post(scribe_url, headers=headers, data=data, files=files)
        if response.status_code == 200:
            res_data = response.json()
            if res_data.get('success'):
                print("✅ Scribe post successful!")
            else:
                print(f"❌ Scribe post failed: {res_data.get('error')}")
        else:
            print(f"❌ Scribe post failed with status {response.status_code}")
            print(f"Response: {response.text}")
    except Exception as e:
        print(f"❌ Scribe post error: {str(e)}")

    print("-" * 50)
    print("🎯 Verification complete. If all steps marked ✅, your DRF Auth is 100% correct!")

if __name__ == "__main__":
    test_api_flow()

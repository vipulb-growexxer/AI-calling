import os
from twilio.rest import Client
from config.config_loader import ConfigLoader

# Load configuration
config_loader = ConfigLoader(config_file="config.ini")
twilio_account_sid = config_loader.get_value("TWILIO", "account_sid")
twilio_auth_token = config_loader.get_value("TWILIO", "auth_token")
twilio_phone_number = config_loader.get_value("TWILIO", "phone_number")

# Get the ngrok URL (convert from WebSocket to HTTP)
webhook_url = config_loader.get_value("TWILIO", "websocket_url")
webhook_url = webhook_url.replace("wss://", "https://").replace("/websocket", "/webhook")

# Initialize Twilio client
client = Client(twilio_account_sid, twilio_auth_token)

# Your phone number to call
your_phone_number = input("Enter your phone number to call (with country code, e.g., +1234567890): ")

# Make the call
call = client.calls.create(
    url=webhook_url,
    to=your_phone_number,
    from_=twilio_phone_number
)

print(f"Call initiated with SID: {call.sid}")
print(f"Using webhook URL: {webhook_url}")
print("The call should connect to your server via webhook once answered.")
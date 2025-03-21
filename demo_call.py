#!/usr/bin/env python3
"""
Demo Call Script for AI Call System
This script directly initiates a call using Twilio and connects to the WebSocket server,
bypassing the SQS queue mechanism for more reliable demos.
"""

import os
import sys
import logging
import argparse
from twilio.rest import Client
from config.config_loader import ConfigLoader
import requests

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s|%(name)s] %(message)s')
logger = logging.getLogger('demo_call')

def make_demo_call(phone_number=None):
    """
    Make a direct call to the specified phone number using Twilio
    and connect to the WebSocket server for the AI conversation.
    
    Args:
        phone_number (str): Phone number to call with country code (e.g., +1234567890)
    """
    # Load configuration
    config_loader = ConfigLoader(config_file="config.ini")
    
    # Get Twilio credentials
    account_sid = config_loader.get("twilio", "TWILIO_ACCOUNT_SID")
    auth_token = config_loader.get("twilio", "TWILIO_TOKEN")
    from_number = config_loader.get("twilio", "TWILIO_PHONE_NO")
    
    # Get WebSocket URL - use local URL if we're running locally
    # This helps ensure we connect to the correct port
    try:
        websocket_url = config_loader.get("twilio", "LOCAL_WEBSOCKET_URL")
        logger.info(f"Using local WebSocket URL: {websocket_url}")
        # Check if server is running on local port
        response = requests.get("http://localhost:8000/health", timeout=2)
        if response.status_code != 200:
            # Fall back to regular WebSocket URL
            websocket_url = config_loader.get("twilio", "WEBSOCKET_URL")
            logger.info(f"Local server not responding, using remote WebSocket URL: {websocket_url}")
    except Exception:
        # If local URL fails or doesn't exist, use regular WebSocket URL
        websocket_url = config_loader.get("twilio", "WEBSOCKET_URL")
        logger.info(f"Using WebSocket URL: {websocket_url}")
    
    # Log configuration (without secrets)
    logger.info(f"Using Twilio phone: {from_number}")
    logger.info(f"Using WebSocket URL: {websocket_url}")
    
    # Get phone number from command line if not provided
    if not phone_number:
        phone_number = input("Enter phone number to call (with country code, e.g., +1234567890): ")
    
    # Initialize Twilio client
    logger.info(f"Initializing Twilio client with SID: {account_sid[:5]}...")
    client = Client(account_sid, auth_token)
    
    try:
        # Check if server is running
        try:
            response = requests.get("http://localhost:8000/health", timeout=2)
            if response.status_code == 200:
                logger.info("Server is running on port 8000")
            else:
                logger.warning("Server returned non-200 status code")
        except requests.exceptions.ConnectionError:
            logger.error("Server is not running on port 8000. Please start the server first.")
            return
        
        # Create TwiML to connect to WebSocket
        twiml = f'''
        <Response>
            <Connect>
                <Stream url="{websocket_url}"/>
            </Connect>
        </Response>
        '''
        
        logger.info(f"Initiating call to {phone_number}...")
        
        # Make the call
        call = client.calls.create(
            twiml=twiml,
            to=phone_number,
            from_=from_number
        )
        
        logger.info(f"Call initiated with SID: {call.sid}")
        logger.info("When you answer the call, you'll be connected to the AI system.")
        logger.info("The call will proceed through all questions with the optimized audio streaming.")
        
        # Print demo instructions
        print("\n" + "="*50)
        print("DEMO INSTRUCTIONS:")
        print("1. Answer the call when your phone rings")
        print("2. Say 'start' after the greeting to begin the interview")
        print("3. Answer each question briefly (responses under 20 words work best)")
        print("4. The system will process your responses and ask follow-up questions if needed")
        print("5. Audio is streamed in real-time for greetings and follow-ups")
        print("="*50 + "\n")
        
        return call.sid
        
    except Exception as e:
        logger.error(f"Error initiating call: {str(e)}")
        return None

def is_server_running():
    """Check if the server is running on port 8000"""
    import socket
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', 8000))
    sock.close()
    
    if result == 0:
        logger.info("Server is running on port 8000")
        return True
    else:
        logger.error("Server is not running on port 8000")
        print("\nERROR: The AI Call server is not running!")
        print("Please start the server first with: python server.py")
        return False

if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Make a demo call with the AI Call System")
    parser.add_argument("--phone", help="Phone number to call (with country code, e.g., +1234567890)")
    args = parser.parse_args()
    
    # Check if server is running
    if not is_server_running():
        sys.exit(1)
    
    # Make the call
    call_sid = make_demo_call(args.phone)
    
    if call_sid:
        print(f"\nCall initiated successfully with SID: {call_sid}")
        print("Check your phone and answer the call to begin the demo.")
    else:
        print("\nFailed to initiate call. Check the logs for details.")
        sys.exit(1)

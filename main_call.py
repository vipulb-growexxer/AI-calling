#!/usr/bin/env python3
"""
Demo Call Script for AI Call System
This script directly initiates a call using Twilio and connects to the WebSocket server,
bypassing the SQS queue mechanism for more reliable demos.
"""

import os
import sys
import logging
from twilio.rest import Client
from config.config_loader import ConfigLoader
import requests
import asyncio
from aiobotocore.session import AioSession
import ast
from utils.validators import validate_phone_no
import concurrent.futures
import time

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s|%(name)s] %(message)s')
logger = logging.getLogger('demo_call')

config_loader = ConfigLoader(config_file="config.ini")
queue_url = config_loader.get('aws', 'queue_url')
websocket_url = config_loader.get('twilio', 'WEBSOCKET_URL')
aws_region = config_loader.get('aws', 'aws_region')
aws_access_key_id = config_loader.get('aws', 'aws_access_key_id')
aws_secret_access_key =  config_loader.get('aws', 'aws_secret_access_key')

def make_demo_call(phone_number=None):
    """
    Make a direct call to the specified phone number using Twilio
    and connect to the WebSocket server for the AI conversation.
    
    Args:
        phone_number (str): Phone number to call with country code (e.g., +1234567890)
    """
    # Load configuration
    config = ConfigLoader(config_file="config.ini")
    account_sid = config.get('twilio', 'TWILIO_ACCOUNT_SID')
    auth_token = config.get('twilio', 'TWILIO_TOKEN')
    from_number = config.get('twilio', 'TWILIO_PHONE_NO')
    
    # Use the ngrok URL from config for external calls
    websocket_url = config.get('twilio', 'WEBSOCKET_URL')
    
    # Log configuration (without secrets)
    logger.info(f"Using Twilio phone: {from_number}")
    logger.info(f"Using WebSocket URL: {websocket_url}")
    
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
                <Stream url="{websocket_url}" track="inbound_track">
                <Parameter name="From" value="{phone_number}" />

                    <Parameter name="greeting" value="Hello, this is an AI screening call. Please say something to start the call." />
                </Stream>
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
        time.sleep(10)
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

async def poll_queue(queue_messages,dup_set):
    session = AioSession()

    async with session.create_client('sqs',region_name=aws_region,aws_access_key_id=aws_access_key_id,aws_secret_access_key=aws_secret_access_key) as client:
        try:
                response = await client.receive_message(
                    QueueUrl=queue_url,
                    AttributeNames=['All'],
                    MaxNumberOfMessages=1,
                    WaitTimeSeconds=10
                )
                if len(response.get('Messages', [])) > 0:
                    messages = response.get("Messages", [])
                    message = messages[0]
                    if message['Body'] in dup_set:
                            return None
                    dup_set.add(message['Body'])
                    
                    whole_message_dict = ast.literal_eval(message['Body'])

                    # this is ongoing call and we wont delete it until call has ended
                    if whole_message_dict in queue_messages["message_list"]:
                        logger.info(f"the message is currently in call, Check for other message")
                        return None
                    
                    # we store new call details with ourselves.
                    logger.info(f"Received message: {whole_message_dict}")

                    queue_messages["message_list"].append(whole_message_dict)

                    message_id = whole_message_dict["MessageId"]
                    message_dict_rel = whole_message_dict['Message']
                    logger.info(f"Message dict is : {message_dict_rel}")
                    message_dict = ast.literal_eval(message_dict_rel)
                    message_dict["message_id"] = message_id
                    phone_no = message_dict["mobileNumber"]
                    receipt_handle = message['ReceiptHandle']
                    await client.delete_message(
                            QueueUrl=queue_url,
                            ReceiptHandle=receipt_handle
                        )
                    return phone_no

                else:
                    logger.info("No messages received in Queue for calling")
                    sys.exit(1)



        except Exception as e:
            logger.error(f"Error in Poll queue {e}")
        
        finally:
            await asyncio.sleep(10)

async def main():
    
    if not is_server_running():
        sys.exit(1)

    queue_messages = {"message_list": []}
    duplicate_message_set = set()
    logger.info("Starting application...")
    num_threads = 10
    with concurrent.futures.ThreadPoolExecutor(num_threads) as executor:
        futures = []
        while True:
            if len(futures) < num_threads:
                phone_no = await poll_queue(
                    queue_messages=queue_messages,
                    dup_set=duplicate_message_set
                )
                type(phone_no)
                if phone_no is not None:
                    if validate_phone_no(phone_no=phone_no):
                        future = executor.submit(make_demo_call, phone_no)
                        futures.append(future)
                    else:
                        print(f"Invalid Number:{phone_no}")
                        break

            else:
                done, futures = concurrent.futures.wait(futures, return_when=concurrent.futures.FIRST_COMPLETED)
                futures = list(futures)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.exception("Unhandled exception in main")
#!/usr/bin/env python3
import configparser
import logging
import sys
import json
import uuid
import time
from services.Twilio_service import TwilioService
from utils.validators import validate_phone_no
import boto3
from botocore.exceptions import ClientError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def send_message_to_sqs(config, phone_number):
    """Send a test message to SQS queue"""
    logger.info(f"Preparing to send test message for phone: {phone_number}")
    
    aws_region = config.get('aws', 'aws_region')
    aws_access_key_id = config.get('aws', 'aws_access_key_id')
    aws_secret_access_key = config.get('aws', 'aws_secret_access_key')
    queue_url = config.get('aws', 'queue_url')
    
    # Create SQS client
    sqs = boto3.client(
        'sqs',
        region_name=aws_region,
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key
    )
    
    # Generate a unique message ID
    message_id = str(uuid.uuid4())
    
    # Create the inner message
    inner_message = {
        "mobileNumber": phone_number,
        "name": "Test User",
        "email": "test@example.com"
    }
    
    # Create the outer message structure
    message_body = {
        "MessageId": message_id,
        "Message": json.dumps(inner_message)
    }
    
    logger.info(f"Message structure: {message_body}")
    
    try:
        # Send message to SQS queue
        response = sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(message_body)
        )
        logger.info(f"Message sent with ID: {response['MessageId']}")
        return response['MessageId']
    except ClientError as e:
        logger.error(f"Error sending message to SQS: {e}")
        return None

def initiate_direct_call(config, phone_number):
    """Directly initiate a call using Twilio"""
    logger.info(f"Testing direct call to: {phone_number}")
    
    # Initialize Twilio service
    twilio_service = TwilioService(configloader=config)
    
    # Get the websocket URL from config
    websocket_url = config.get('twilio', 'WEBSOCKET_URL')
    
    logger.info(f"Using WebSocket URL: {websocket_url}")
    
    try:
        # Initiate the call
        call = twilio_service.initiate_call(to_number=phone_number, websocket_url=websocket_url)
        logger.info(f"Call initiated successfully!")
        logger.info(f"Call SID: {call.sid}")
        logger.info(f"Call Status: {call.status}")
        return call.sid
    except Exception as e:
        logger.error(f"Error initiating call: {e}")
        return None

def main():
    # Parse configuration
    config = configparser.ConfigParser()
    config.read('config.ini')
    
    # Phone number to use
    phone_number = "+917038589244"  # Update with your test number
    
    # Validate phone number
    if not validate_phone_no(phone_number):
        logger.error(f"Invalid phone number format: {phone_number}")
        return
    
    # Ask user which test to run
    print("\nTest Options:")
    print("1. Send message to SQS queue")
    print("2. Initiate direct call with Twilio")
    print("3. Run both tests (end-to-end)")
    
    choice = input("\nEnter your choice (1, 2, or 3): ")
    
    if choice == '1' or choice == '3':
        # Send message to SQS
        logger.info("=" * 30)
        logger.info("SENDING MESSAGE TO SQS")
        logger.info("=" * 30)
        message_id = send_message_to_sqs(config, phone_number)
        logger.info(f"Test message sent to SQS for phone number: {phone_number}")
        
        if choice == '3':
            # Wait a bit for SQS processing
            logger.info("Waiting 5 seconds to allow for SQS processing...")
            time.sleep(5)
    
    if choice == '2' or choice == '3':
        # Initiate direct call
        logger.info("=" * 30)
        logger.info("INITIATING DIRECT CALL")
        logger.info("=" * 30)
        call_sid = initiate_direct_call(config, phone_number)
        if call_sid:
            logger.info(f"Call initiated to {phone_number} with SID: {call_sid}")
            
    logger.info("Test completed.")

if __name__ == "__main__":
    main()

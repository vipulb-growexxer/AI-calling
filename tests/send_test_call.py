import boto3
import json
import configparser
import uuid
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s|%(name)s] %(message)s')
logger = logging.getLogger('send_test_call')

class SqsPublisher:
    def __init__(self, configloader):
        self.queue_url = configloader.get('aws', 'queue_url')
        self.aws_access_key_id = configloader.get('aws', 'aws_access_key_id')
        self.aws_secret_access_key = configloader.get('aws', 'aws_secret_access_key')
        self.aws_region = configloader.get('aws', 'aws_region')
        try:
            self.sqs_client = boto3.client(
                'sqs',
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key,
                region_name=self.aws_region
            )
        except Exception as e:
            logger.error(f"SQS Client initialization failed: {e}")

    def publish(self, message_payload):
        try:
            # Format the message to mimic SNS notification structure
            # This is crucial for compatibility with poll_queue.py
            message_id = str(uuid.uuid4())
            sns_formatted_message = {
                "Type": "Notification",
                "MessageId": message_id,
                "TopicArn": "dummy-topic-arn",  # Not used but included for format compatibility
                "Message": json.dumps(message_payload),
                "Timestamp": "2023-01-01T00:00:00.000Z",  # Dummy timestamp
                "SignatureVersion": "1",
                "Signature": "dummy-signature",  # Not used but included for format compatibility
                "SigningCertURL": "dummy-cert-url",  # Not used but included for format compatibility
                "UnsubscribeURL": "dummy-unsubscribe-url"  # Not used but included for format compatibility
            }
            
            # Convert the entire SNS-formatted message to a JSON string
            message_json = json.dumps(sns_formatted_message)
            logger.info(f"Publishing to SQS: {message_json}")
            
            # Send message to SQS
            response = self.sqs_client.send_message(
                QueueUrl=self.queue_url,
                MessageBody=message_json
            )
            logger.info(f"Successfully published message to SQS queue with message ID: {response['MessageId']}")
            return response
        except Exception as e:
            logger.error(f"Unable to publish message to SQS queue due to: {e}")
            return None

def load_config():
    config = configparser.ConfigParser()
    config.read('config.ini')
    return config

def send_test_call():
    """Send a test call message directly to SQS in the format expected by poll_queue.py"""
    config = load_config()
    
    # Log AWS configuration (without secrets)
    logger.info(f"Using AWS region: {config.get('aws', 'aws_region')}")
    logger.info(f"Using SQS queue URL: {config.get('aws', 'queue_url')}")
    
    # Create SQS publisher
    sqs_publisher = SqsPublisher(configloader=config)
    
    # Test phone number
    test_phone_number = "+917038589244"
    
    # Create the message payload that will be sent to SQS
    # This should match the structure expected by poll_queue.py
    message_payload = {
        "metadata": {
            "applicationId": ""
        },
        "mobileNumber": test_phone_number,
        "name": "Test User",
        "email": "test@example.com"
    }
    
    logger.info(f"Sending message to SQS: {message_payload}")
    
    # Publish message to SQS
    response = sqs_publisher.publish(message_payload=message_payload)
    
    if response:
        logger.info(f"Message sent with ID: {response.get('MessageId')}")
        logger.info(f"Test call will be made to: {test_phone_number}")
    else:
        logger.error("Failed to send message to SQS")

if __name__ == "__main__":
    send_test_call()



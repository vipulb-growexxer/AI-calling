import boto3
import configparser
import time
import json
import ast

def load_config():
    config = configparser.ConfigParser()
    config.read('config.ini')
    return config

def test_sqs_connection_and_messages():
    """Test SQS connection and check for messages with multiple attempts"""
    config = load_config()
    
    # Get AWS configuration
    queue_url = config.get('aws', 'queue_url')  # Using the correct key from config.ini
    aws_region = config.get('aws', 'aws_region')
    aws_access_key_id = config.get('aws', 'aws_access_key_id')
    aws_secret_access_key = config.get('aws', 'aws_secret_access_key')
    
    print(f"Using AWS region: {aws_region}")
    print(f"Using SQS queue URL: {queue_url}")
    
    try:
        # Create SQS client
        sqs_client = boto3.client(
            'sqs',
            region_name=aws_region,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key
        )
        
        # Get queue attributes to check connection
        response = sqs_client.get_queue_attributes(
            QueueUrl=queue_url,
            AttributeNames=['All']
        )
        
        print("Successfully connected to SQS queue!")
        print(f"Queue attributes: {response['Attributes']}")
        
        # Try multiple times to receive messages
        print("\nAttempting to receive messages (will try 5 times with 5 second intervals)...")
        
        for attempt in range(1, 6):
            print(f"\nAttempt {attempt}/5:")
            
            # Check approximate number of messages
            queue_attrs = sqs_client.get_queue_attributes(
                QueueUrl=queue_url,
                AttributeNames=['ApproximateNumberOfMessages']
            )
            approx_messages = int(queue_attrs['Attributes'].get('ApproximateNumberOfMessages', '0'))
            print(f"Approximate number of messages in queue: {approx_messages}")
            
            # Try to receive messages
            receive_response = sqs_client.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=10,
                AttributeNames=['All'],
                MessageAttributeNames=['All']
            )
            
            messages = receive_response.get('Messages', [])
            if messages:
                print(f"Successfully received {len(messages)} message(s)!")
                
                for i, message in enumerate(messages):
                    print(f"\n--- MESSAGE {i+1} DETAILS ---")
                    print(f"Message ID: {message.get('MessageId')}")
                    
                    # Print raw message body
                    print("\nRaw Message Body:")
                    print(message['Body'])
                    
                    try:
                        # Try to parse as JSON first
                        try:
                            body_json = json.loads(message['Body'])
                            print("\nParsed as JSON:")
                            print(json.dumps(body_json, indent=2))
                            
                            # Check for Message field in JSON
                            if 'Message' in body_json:
                                inner_message = body_json['Message']
                                print("\nInner Message content:")
                                print(inner_message)
                                
                                # Try to parse inner message
                                try:
                                    # Try JSON first
                                    try:
                                        inner_json = json.loads(inner_message)
                                        print("\nInner message parsed as JSON:")
                                        print(json.dumps(inner_json, indent=2))
                                    except:
                                        # Try ast.literal_eval as fallback
                                        inner_dict = ast.literal_eval(inner_message)
                                        print("\nInner message parsed with ast.literal_eval:")
                                        print(inner_dict)
                                    
                                    print("\n SUCCESS: Message format appears correct!")
                                except Exception as e:
                                    print(f"\n ERROR: Could not parse inner message: {e}")
                            else:
                                print("\n ERROR: No 'Message' field found in the JSON body")
                        except json.JSONDecodeError:
                            # If not JSON, try ast.literal_eval
                            body_dict = ast.literal_eval(message['Body'])
                            print("\nParsed with ast.literal_eval:")
                            print(body_dict)
                            
                            # Check for Message field
                            if 'Message' in body_dict:
                                inner_message = body_dict['Message']
                                print("\nInner Message content:")
                                print(inner_message)
                                
                                # Try to parse inner message
                                try:
                                    inner_dict = ast.literal_eval(inner_message)
                                    print("\nInner message parsed:")
                                    print(inner_dict)
                                    print("\n SUCCESS: Message format appears correct!")
                                except Exception as e:
                                    print(f"\n ERROR: Could not parse inner message: {e}")
                            else:
                                print("\n ERROR: No 'Message' field found in the body")
                    except Exception as e:
                        print(f"\n ERROR: Could not parse message body: {e}")
                    
                    # Don't delete the message so we can see it in future tests
                    print("\nMessage left in queue for future tests.")
                
                return True
            else:
                print("No messages received in this attempt.")
            
            if attempt < 5:
                print(f"Waiting 5 seconds before next attempt...")
                time.sleep(5)
        
        print("\nNo messages found after 5 attempts.")
        return False
    except Exception as e:
        print(f"Error: {e}")
        return False

if __name__ == "__main__":
    success = test_sqs_connection_and_messages()
    print(f"\nTest {'succeeded' if success else 'failed'}")

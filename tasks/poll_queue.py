from logger.logger_config import logger
from services.Twilio_service import TwilioService
from aiobotocore.session import AioSession
import ast
import asyncio
from utils.validators import validate_phone_no


async def poll_queue(configloader,shared_data,queue_messages,dup_set):
    queue_url = configloader.get('aws', 'queue_url')
    websocket_url = configloader.get('twilio', 'WEBSOCKET_URL')
    aws_region = configloader.get('aws', 'aws_region')
    aws_access_key_id = configloader.get('aws', 'aws_access_key_id')
    aws_secret_access_key =  configloader.get('aws', 'aws_secret_access_key')
    queue_url = configloader.get('aws', 'queue_url')

    twilio_service = TwilioService(configloader=configloader)
    
    logger.info("Task for Poll queue for messages is started")

    session = AioSession()

    async with session.create_client('sqs',region_name=aws_region,aws_access_key_id=aws_access_key_id,aws_secret_access_key=aws_secret_access_key) as client:
        while True:
            try:
                
                response = await client.receive_message(
                    QueueUrl=queue_url,
                    AttributeNames=['All'],
                    MaxNumberOfMessages=1,  
                    WaitTimeSeconds=20,
                    VisibilityTimeout=1,
                )                
                messages = response.get('Messages', [])
                
                logger.info(f"SQS Poll response: {response}")
                logger.info(f"Messages found: {len(messages)}")
                
                if messages:

                    for message in messages:
                        #triger starting call status checking code every second and check for uniqe message . 
                        if message['Body'] in dup_set:
                            continue
                        dup_set.add(message['Body'])
                        
                        whole_message_dict = ast.literal_eval(message['Body'])

                        # this is ongoing call and we wont delete it until call has ended
                        if whole_message_dict in queue_messages["message_list"]:
                            logger.info(f"the message is currently in call, Check for other message")
                            continue
                        
                        # we store new call details with ourselves.
                        logger.info(f"Received message: {whole_message_dict}")

                        queue_messages["message_list"].append(whole_message_dict)

                        message_id = whole_message_dict["MessageId"]
                        message_dict_rel = whole_message_dict['Message']
                        logger.info(f"Message dict is : {message_dict_rel}")
                        message_dict = ast.literal_eval(message_dict_rel)
                        
                        phone_no = message_dict["mobileNumber"]
                        logger.info(f"Phone no is {phone_no}")

                        message_dict["message_id"] = message_id

                        if validate_phone_no(phone_no=phone_no):
                            # if validated , we make api  request for twilio to call interviwee
                            call = twilio_service.initiate_call(to_number=phone_no,websocket_url=websocket_url)
                            message_dict["call_sid"] = call.sid
                            logger.info(f"Call Sid  is {call.sid}")
                            logger.info(f"{message_dict} is the incoming dict and it seems valid")
                            shared_data["call_instance_list"].append(message_dict)
                        
                        else:
                            logger.info("invalid phone number , Call is rejected. ")
                            message_dict["call_sid"] = "call.sid"
                        
                        
                else:
                    logger.info("No messages received in Queue for calling")


            except Exception as e:
                logger.error(f"Error in Poll queue {e}")
            
            finally:
                await asyncio.sleep(10)

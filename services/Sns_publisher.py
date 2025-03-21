import json
import boto3
from logger.logger_config import logger

class SnsPublisher:
    def __init__(self,configloader):
        self.sns_topic_arn = configloader.get('aws', 'aws_sns_topic_arn')
        self.aws_access_key_id = configloader.get('aws','aws_access_key_id')
        self.aws_secret_access_key = configloader.get('aws','aws_secret_access_key')
        self.aws_region = configloader.get('aws',"aws_region")
        try:
            self.sns_client=boto3.client(
                'sns',
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key,
                region_name=self.aws_region
            )
        except Exception as e:
            logger.error("              --------------- SNS Client not made")
    async def publish(self,message_payload):
        try:
            message_json = json.dumps(message_payload)
            response = self.sns_client.publish(
                TopicArn=self.sns_topic_arn,
                Message=message_json
            )
            logger.info(f"Successfully published message on SNS topic with message Id :{response}")
            return response
        
        except Exception as e:
            logger.error(f"Unable to publish message on SNS topic due to {e}")

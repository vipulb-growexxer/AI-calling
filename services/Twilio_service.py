from twilio.rest import Client
from logger.logger_config import logger
from twilio.base.exceptions import TwilioRestException


class TwilioService:
    def __init__(self,configloader):
        self.account_sid = configloader.get('twilio', 'TWILIO_ACCOUNT_SID')
        self.auth_token = configloader.get('twilio', 'TWILIO_TOKEN')
        self.websocket_url = configloader.get('twilio', 'WEBSOCKET_URL')
        self.twilio_no = configloader.get('twilio', 'TWILIO_PHONE_NO')

        logger.info(f"Initializing Twilio service with SID: {self.account_sid[:5]}... and phone: {self.twilio_no}")
        self.client = Client(self.account_sid, self.auth_token)
 
    def initiate_call(self, to_number: str, websocket_url: str):
        try:
            logger.info(f"Initiating Twilio call to: {to_number}")
            logger.info(f"Using WebSocket URL: {websocket_url}")
            logger.info(f"From Twilio number: {self.twilio_no}")
            
            call = self.client.calls.create(
                twiml=f'<Response><Connect><Stream url="{websocket_url}"/></Connect></Response>',
                to=to_number,
                from_=self.twilio_no
            )
            
            logger.info(f"Call initiated successfully with SID: {call.sid}")
            return call
            
        except TwilioRestException as e:
            logger.error(f"Twilio API Error: {e.code} - {e.msg}")
            raise
        except Exception as e:
            logger.error(f"Error initiating call: {str(e)}")
            raise

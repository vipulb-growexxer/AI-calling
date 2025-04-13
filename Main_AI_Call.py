import asyncio
import websockets
from handlers.websocket_handler import websocket_handler

from tasks.poll_queue import poll_queue
from tasks.check_status_second import call_status_check
from logger.logger_config import logger
from config.config_loader import ConfigLoader


import websockets


# shared_data and queue_message are storing AWS sqs incoming messages ,
# Sending Twilio rest api request for call does not mean that use has picked up call. This creates ambiguity regarding call status.
# as we can only check call status of call that are picked up. 
# To solve this we store call requests from SQS in shared_data and queue_messages. and make a task whose sole purpose is to check call status every few seconds. 
# we ignore call status 5,6,7 and 0-4 indicate that the call has been completed.




shared_data = {
    "call_instance_list":[]
}
queue_messages = {
    "message_list":[]
}
call_status_mapping = {

    "canceled": 0,
    "completed": 1,
    "busy": 2,
    "no-answer": 3,
    "failed": 4,
    "queued":5,
    "ringing":6,
    "in-progress":7
}

# duplicate_message_set is a small fix up and advised to be removed . It is essentially checking for unique messages in sqs . We needed it as we could not control asyncrnous deleteion of message.
# It wont affect in small scale. But needs to be change for project,
duplicate_message_set = set()


async def main():
    config_loader = ConfigLoader(config_file="config.ini")
    logger.info("Starting application...")

    # Poll queue  will look in aws sqs for unique message for outbound call request and if it is not called ,it will make twilio request to make call and 
    # make connection to our websocket connection
    asyncio.create_task(poll_queue(configloader=config_loader,shared_data=shared_data,queue_messages = queue_messages,dup_set = duplicate_message_set))
    
    # Constantly checking status of call and if call status is ended, busy , not answering or completed. That is our queue to delete the call from AWS SQS. and we do the same.
    asyncio.create_task(call_status_check(shared_data=shared_data,call_status_mapping=call_status_mapping,configloader=config_loader,queue_messages=queue_messages,dup_set = duplicate_message_set))
    
    # This is a websocket function that is activate when a client(twilio) comes to us for connection. This is main function to handle Candidate Call
    ws_server = await websockets.serve(
        lambda websocket,
        path :websocket_handler(client_ws=websocket,configloader=config_loader,shared_data=shared_data,call_status_mapping=call_status_mapping,queue_messages=queue_messages),
        '0.0.0.0',
        5001
        )
    await ws_server.wait_closed()
    logger.info("WebSocket server closed.")

if __name__ == "__main__":
    asyncio.run(main())




[
    {
      "state": 1,
      "question": "How many years of professional experience do you have in total?",
      "expected_answer_type": "number_or_fresher_intern and relevant to current role",
      "max_followups": 2,
      "response_categories": {
        "years": "Candidate has professional experience measured in years",
        "fresher": "Candidate is a fresher or recent graduate with no full-time experience",
        "intern": "Candidate has internship or training experience but no full-time role"
      },
      "follow_up_instructions": {
        "years": "Out of {extracted_value} years, how many years are relevant to this role?",
        "fresher": "Do you have any internship experience related to this role?",
        "intern": "How many months of internship experience do you have related to this role?",
        "default": "Could you clarify how many years of professional experience you have?"
      }
    },
    {
      "state": 2,
      "question": "What is your current or last CTC?",
      "expected_answer_type": "amount_with_unit",
      "max_followups": 2,
      "response_categories": {
        "amount": "Candidate has provided a specific amount or range for their CTC",
        "not_comfortable": "Candidate has explicitly refused to share their CTC information",
        "irrelevant": "Candidate has provided an answer that doesn't address the CTC question"
      },
      "follow_up_instructions": {
        "amount": "Out of {extracted_value}, how much is fixed and how much is variable?",
        "not_comfortable": "I understand. Let's move to the next question.",
        "irrelevant": "Could you share your CTC figure or a range if you're comfortable?",
        "default": "Could you share your CTC figure or a range if you're comfortable?"
      }
    },
    {
      "state": 3,
      "question": "What is your expected CTC?",
      "expected_answer_type": "amount_or_hike_or_range",
      "max_followups": 2,
      "response_categories": {
        "amount": "Candidate has provided a specific amount for their expected CTC",
        "hike": "Candidate has provided a percentage hike expectation",
        "range": "Candidate has provided a range for their expected CTC",
        "not_comfortable": "Candidate has explicitly refused to share their expected CTC",
        "irrelevant": "Candidate has provided an answer that doesn't address the expected CTC question"
      },
      "follow_up_instructions": {
        "amount": "",
        "hike": "",
        "range": "",
        "not_comfortable": "",
        "irrelevant": "Could you share your expected CTC or a percentage hike you're looking for?",
        "default": "Could you share your expected CTC or a percentage hike you're looking for?"
      }
    },
    {
      "state": 4,
      "question": "Do you currently have any other offers from other companies?",
      "expected_answer_type": "yes_or_no_with_amount",
      "max_followups": 2,
      "response_categories": {
        "yes": "Candidate has confirmed they have other offers",
        "no": "Candidate has confirmed they don't have other offers",
        "irrelevant": "Candidate has provided an answer that doesn't clearly indicate yes or no"
      },
      "follow_up_instructions": {
        "yes": "What amount are they offering?",
        "no": "",
        "irrelevant": "I need to know if you have other offers currently. Could you please answer with a yes or no?",
        "default": "I need to know if you have other offers currently. Could you please answer with a yes or no?"
      }
    },
    {
      "state": 5,
      "question": "What is the duration of your notice period?",
      "expected_answer_type": "notice_period_duration",
      "max_followups": 2,
      "response_categories": {
        "short_notice": "Candidate has a notice period less than 60 days",
        "long_notice": "Candidate has a notice period of 60 days or more",
        "immediate": "Candidate can join immediately with no notice period",
        "irrelevant": "Candidate has provided an answer that doesn't clearly indicate their notice period"
      },
      "follow_up_instructions": {
        "long_notice": "Can you reduce your notice period?",
        "short_notice": "",
        "immediate": "",
        "irrelevant": "Could you please specify your notice period in days or months?",
        "default": "Could you please specify your notice period in days or months?"
      },
      "notice_period_threshold": 60
    }
  ]
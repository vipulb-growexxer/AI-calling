"""
Twilio webhook handler
Responsible for handling incoming webhook requests from Twilio
"""

from aiohttp import web
import json
import logging
import urllib.parse
from memory.memory_a import MemoryA
from memory.memory_b import MemoryB
from logger.logger_config import logger

async def handle_twilio_webhook(request_data, memory_a: MemoryA, memory_b: MemoryB, shared_data=None):
    """
    Handle incoming webhook requests from Twilio
    
    Parameters:
    - request_data: POST data from the Twilio webhook
    - memory_a: Reference to Memory A (Question Bank)
    - memory_b: Reference to Memory B (Conversation Buffer)
    - shared_data: Shared data for tracking outbound call instances
    
    Returns:
    - TwiML response string
    """
    try:
        # Extract information from the webhook
        call_sid = request_data.get('CallSid')
        call_status = request_data.get('CallStatus')
        
        logger.info(f"Received Twilio webhook for call {call_sid} with status {call_status}")
        
        # Handle different webhook types based on call status
        if call_status == 'initiated' or call_status == 'ringing':
            # Call is being initiated
            return await handle_call_initiated(call_sid, request_data, memory_a, memory_b, shared_data)
            
        elif call_status == 'in-progress':
            # Call is in progress
            return await handle_call_in_progress(call_sid, request_data, memory_a, memory_b, shared_data)
            
        elif call_status in ['completed', 'busy', 'failed', 'no-answer', 'canceled']:
            # Call has ended
            return await handle_call_ended(call_sid, request_data, memory_a, memory_b, shared_data)
            
        else:
            # Unknown call status
            logger.warning(f"Received unknown call status: {call_status}")
            return "<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response></Response>"
            
    except Exception as e:
        logger.error(f"Error handling Twilio webhook: {str(e)}")
        return "<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response><Say>An error occurred.</Say></Response>"

async def handle_call_initiated(call_sid, request_data, memory_a, memory_b, shared_data=None):
    """Handle webhook for call initiation"""
    try:
        # Initialize conversation state in Memory B
        await memory_b.initialize_conversation(call_sid, initial_state=0)
        
        # Generate TwiML response to connect to websocket for streaming
        from_number = request_data.get('From', 'unknown')
        logger.info(f"Call initiated from {from_number}, SID: {call_sid}")
        
        # Determine the WebSocket URL
        # In production, this would be your fully qualified domain name
        host = request_data.get('host', 'localhost:8000')
        
        # If we're behind a proxy, we need to use the X-Forwarded-Proto and X-Forwarded-Host headers
        proto = request_data.get('X-Forwarded-Proto', 'http')
        if 'localhost' in host or '127.0.0.1' in host:
            # Local development
            websocket_url = f"ws://{host}/websocket"
        else:
            # Production
            websocket_url = f"wss://{host}/websocket"
        
        logger.info(f"Using WebSocket URL: {websocket_url}")
        
        # Return TwiML that connects the call to our websocket endpoint
        twiml = f"""
        <?xml version="1.0" encoding="UTF-8"?>
        <Response>
            <Connect>
                <Stream url="{websocket_url}">
                    <Parameter name="callSid" value="{call_sid}"/>
                </Stream>
            </Connect>
            <Pause length="600"/>
        </Response>
        """
        
        return twiml
        
    except Exception as e:
        logger.error(f"Error handling call initiation: {str(e)}")
        return "<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response><Say>Sorry, we could not initialize the call.</Say></Response>"

async def handle_call_in_progress(call_sid, request_data, memory_a, memory_b, shared_data=None):
    """Handle webhook for in-progress call events"""
    try:
        # For most in-progress events, we just acknowledge receipt
        return "<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response></Response>"
        
    except Exception as e:
        logger.error(f"Error handling in-progress call: {str(e)}")
        return "<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response></Response>"

async def handle_call_ended(call_sid, request_data, memory_a, memory_b, shared_data=None):
    """Handle webhook for call completion"""
    try:
        # Clean up resources for this call
        await memory_b.end_conversation(call_sid)
        
        # Log call details for analytics
        call_duration = request_data.get('CallDuration', '0')
        call_status = request_data.get('CallStatus', 'unknown')
        
        logger.info(f"Call {call_sid} ended. Status: {call_status}, Duration: {call_duration}s")
        
        # Update shared_data for outbound call tracking
        if shared_data is not None:
            # Find and remove this call from the call_instance_list
            if "call_instance_list" in shared_data:
                shared_data["call_instance_list"] = [
                    call for call in shared_data["call_instance_list"] 
                    if call.get("call_sid") != call_sid
                ]
                logger.info(f"Removed call {call_sid} from outbound call tracking")
        
        # If desired, you could save call data to a database here
        # This could include all responses, transcript, etc. from Memory B
        
        return "<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response></Response>"
        
    except Exception as e:
        logger.error(f"Error handling call ended: {str(e)}")
        return "<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response></Response>"

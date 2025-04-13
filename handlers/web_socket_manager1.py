import logging
import json
import base64
import asyncio
import uuid
import time
from typing import Dict, Any, Optional
import random

from memory.memory_a import MemoryA
from memory.memory_b import MemoryB
from memory.memory_c import MemoryC
from handlers.conversation_manager import ConversationManager
from services.Deepgram_service import DeepgramService


class WebSocketManager:
    """
    Manages WebSocket connections for real-time audio streaming and processing.
    
    Responsibilities:
    1. Handle incoming WebSocket connections from Twilio
    2. Buffer audio and send to Deepgram for transcription
    3. Process transcribed text through the conversation flow
    4. Stream audio responses back to Twilio
    5. Manage marks and speech tracking
    6. Track outbound call status and management
    """
    
    def __init__(
        self,
        memory_a: MemoryA,
        memory_b: MemoryB,
        memory_c: MemoryC, # added
        conversation_manager: ConversationManager,
        deepgram_service: DeepgramService,
        config_loader,
        shared_data: Dict = None,
        call_status_mapping: Dict = None,
        queue_messages: Dict = None
    ):
        self.memory_a = memory_a
        self.memory_b = memory_b
        self.memory_c = memory_c #added
        self.conversation_manager = conversation_manager
        self.deepgram_service = deepgram_service
        self.config_loader = config_loader
        self.logger = logging.getLogger(__name__)
        
        # Outbound call tracking
        self.shared_data = shared_data or {"call_instance_list": []}
        self.call_status_mapping = call_status_mapping or {}
        self.queue_messages = queue_messages or {"message_list": []}
        
        # Client-specific data
        self.active_connections = {}
        self.stream_sids = {}
        self.call_sids = {}
        self.marks = {}
        self.speaking_flags = {}
        self.exit_events = {}
        
        # Audio buffering
        self.BUFFER_SIZE = 10 * 160  # Same as used in old implementation
        self.audio_buffers = {}
        self.outboxes = {}
        
        # Deepgram connections
        self.deepgram_connections = {}
        self.deepgram_ready_events = {}
        
        # Accumulated text from transcription
        self.accumulated_texts = {}
        
        self.logger.info("WebSocketManager initialized")
    
    async def handle_websocket(self, client_ws):
        """Main handler for WebSocket connections from Twilio"""
        # Generate a unique WebSocket ID
        ws_id = str(uuid.uuid4())
        
        try:
            self.logger.info(f"Starting WebSocket handler for {ws_id}")
            
            # Initialize connection tracking
            self.active_connections[ws_id] = client_ws
            self.exit_events[ws_id] = asyncio.Event()
            self.speaking_flags[ws_id] = asyncio.Event()
            self.accumulated_texts[ws_id] = ""
            self.audio_buffers[ws_id] = bytearray()
            self.outboxes[ws_id] = asyncio.Queue()
            self.marks[ws_id] = []
            
            # Initialize stream_sid and call_sid
            stream_sid = None
            call_sid = None
            
            # Initialize Deepgram connection
            self.deepgram_ready_events[ws_id] = asyncio.Event()
            await self.connect_to_deepgram(ws_id)
            
            # Start the Deepgram receiver task
            deepgram_task = asyncio.create_task(self._handle_deepgram_receiving(ws_id))
            
            # Start heartbeat task
            heartbeat_task = asyncio.create_task(self._heartbeat(ws_id))
            
            # Process incoming messages
            async for message in client_ws:
                if isinstance(message, str):
                    try:
                        data = json.loads(message)
                        event_type = data.get('event', 'unknown')
                        
                        # Only log non-media events or log media events occasionally
                        if event_type != 'media' or random.random() < 0.02:
                            self.logger.info(f"Received message: {event_type} for {ws_id}")
                        
                        # Handle different events from Twilio
                        if data.get('event') == 'connected':
                            # Store the stream SID for later use
                            stream_sid = data.get('streamSid')
                            self.logger.info(f"Connected event data: {data}")
                            self.stream_sids[ws_id] = stream_sid
                            self.logger.info(f"Connected to stream {stream_sid} for {ws_id}")
                            
                            # Get call SID from parameters
                            if 'start' in data and 'callSid' in data['start']:
                                call_sid = data['start']['callSid']
                                self.call_sids[ws_id] = call_sid
                                self.logger.info(f"Call SID: {call_sid} for {ws_id}")
                                
                                # Initialize conversation in Memory B
                                await self.memory_b.initialize_conversation(call_sid)
                            
                        elif data.get('event') == 'start':
                            # Extract call SID if not already set
                            if not call_sid and 'callSid' in data['start']:
                                call_sid = data['start']['callSid']
                                self.call_sids[ws_id] = call_sid
                                self.logger.info(f"Call SID from start event: {call_sid} for {ws_id}")
                                
                                # Initialize conversation in Memory B
                                await self.memory_b.initialize_conversation(call_sid)
                            
                            # Extract stream SID if present in the start event
                            if 'streamSid' in data['start']:
                                stream_sid = data['start']['streamSid']
                                self.stream_sids[ws_id] = stream_sid
                                self.logger.info(f"Stream SID from start event: {stream_sid} for {ws_id}")
                            
                            # Log the full start event data for debugging
                            self.logger.info(f"Start event data: {data}")
                            
                            # Play greeting message immediately when start event is received
                            # This is the correct place to play the greeting as we now have the stream SID
                            greeting_message = "Hello, this is an AI screening call. Please say something to start the call."
                            self.logger.info(f"Playing immediate greeting: {greeting_message} for {ws_id}")
                            try:
                                # Set speaking flag to prevent interruptions
                                self.speaking_flags[ws_id].set()
                                self.logger.info(f"Set speaking flag for immediate greeting playback: {ws_id}")
                                
                                # Warm up LLM asynchronously while playing greeting
                                asyncio.create_task(self.conversation_manager.warm_up_llm())
                                
                                # Stream the greeting audio
                                await self._stream_elevenlabs_audio(ws_id, greeting_message)
                                self.logger.info(f"Completed streaming immediate greeting audio for {ws_id}")
                                
                                # Send mark to indicate end of greeting
                                await self._send_mark(ws_id)
                                self.logger.info(f"Sent mark after immediate greeting for {ws_id}")
                                
                                # Clear speaking flag to allow for user response
                                self.speaking_flags[ws_id].clear()
                                self.logger.info(f"Cleared speaking flag after immediate greeting for {ws_id}")
                            except Exception as e:
                                self.logger.error(f"Error playing immediate greeting: {e}")
                                import traceback
                                self.logger.error(traceback.format_exc())
                        
                        elif data.get('event') == 'media':
                            # Only log media messages occasionally (1 in 50) to reduce noise
                            if random.random() < 0.02:  # ~2% chance to log
                                self.logger.debug(f"Received media message for {ws_id}")
                            
                            # Process incoming audio
                            if 'media' in data and 'payload' in data['media']:
                                # Decode base64 audio
                                audio_data = base64.b64decode(data['media']['payload'])
                                
                                # Add to buffer
                                self.audio_buffers[ws_id].extend(audio_data)
                                
                                # If buffer is full, send to Deepgram
                                if len(self.audio_buffers[ws_id]) >= self.BUFFER_SIZE:
                                    # Only send if Deepgram is ready
                                    if self.deepgram_ready_events[ws_id].is_set() and ws_id in self.deepgram_connections:
                                        try:
                                            # Send audio to Deepgram
                                            await self.deepgram_connections[ws_id].send(bytes(self.audio_buffers[ws_id]))
                                            # Clear buffer
                                            self.audio_buffers[ws_id] = bytearray()
                                        except Exception as e:
                                            self.logger.error(f"Error sending audio to Deepgram: {e}")
                        
                        elif data.get('event') == 'mark':
                            # Handle mark event (when AI finishes speaking)
                            if 'mark' in data and 'name' in data['mark']:
                                mark_name = data['mark']['name']
                                if mark_name in self.marks[ws_id]:
                                    self.logger.info(f"Mark received: {mark_name} for {ws_id}")
                                    # Clear speaking flag to allow processing user input
                                    self.speaking_flags[ws_id].clear()
                                    
                                    # Special handling for end call mark
                                    if mark_name == "end call":
                                        self.logger.info(f"End call mark received for {ws_id}")
                                        # Set exit event to clean up resources
                                        self.exit_events[ws_id].set()
                                        
                        elif data.get('event') == 'closed':
                            # Handle connection closed event
                            self.logger.info(f"Connection closed for {ws_id}")
                            self.exit_events[ws_id].set()
                            break
                            
                    except json.JSONDecodeError:
                        self.logger.warning(f"Invalid JSON message: {message[:100]}... for {ws_id}")
                    except Exception as e:
                        self.logger.error(f"Error processing message: {e} for {ws_id}")
                        import traceback
                        self.logger.error(traceback.format_exc())
                
                elif isinstance(message, bytes):
                    self.logger.info(f"Received binary message of {len(message)} bytes for {ws_id}")
                    
            self.logger.info(f"WebSocket connection closed for {ws_id}")
            
        except Exception as e:
            self.logger.error(f"Error in WebSocket handler: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            
        finally:
            # Clean up resources
            self._cleanup_connection(ws_id)
            self.logger.info(f"WebSocket handler for {ws_id} completed")
    
    async def _handle_client_messages(self, ws_id):
        """Process messages from Twilio WebSocket"""
        client_ws = self.active_connections.get(ws_id)
        if not client_ws:
            return
            
        empty_byte_received = False
        
        self.logger.info(f"Started handling client messages for {ws_id}")
        
        try:
            async for message in client_ws:
                if self.exit_events[ws_id].is_set():
                    self.logger.info(f"Exit signal received for {ws_id}")
                    break
                    
                self.logger.info(f"Received WebSocket message for {ws_id}: {message[:100]}...")
                
                data = json.loads(message)
                
                if data["event"] == "connected":
                    # Initialize Deepgram connection
                    self.logger.info(f"Connecting to Deepgram for {ws_id}")
                    self.deepgram_connections[ws_id] = await self.deepgram_service.connect()
                    self.deepgram_ready_events[ws_id] = asyncio.Event()
                    self.deepgram_ready_events[ws_id].set()
                    self.logger.info(f"Deepgram connected for {ws_id}")
                
                elif data["event"] == "start":
                    # Store stream and call IDs
                    self.stream_sids[ws_id] = data["streamSid"]
                    self.call_sids[ws_id] = data["start"]["callSid"]
                    self.logger.info(f"Call started with SID: {self.call_sids[ws_id]} for {ws_id}")
                    
                    # Initialize call in conversation manager
                    self.logger.info(f"Initializing call in conversation manager for {ws_id}")
                    success, greeting_text, error = await self.conversation_manager.initialize_call(
                        self.call_sids[ws_id]
                    )
                    
                    if success and greeting_text:
                        self.logger.info(f"Playing greeting: {greeting_text[:50]}... for {ws_id}")
                        # Stream greeting audio directly from ElevenLabs to Twilio
                        await self._stream_elevenlabs_audio(ws_id, greeting_text)
                        await self._send_mark(ws_id)
                        self.speaking_flags[ws_id].set()
                        self.logger.info(f"Greeting played, waiting for user response for {ws_id}")
                    else:
                        self.logger.error(f"Failed to initialize call: {error} for {ws_id}")
                    
                elif data["event"] == "media":
                    media = data["media"]
                    chunk = base64.b64decode(media["payload"])
                    
                    if chunk:
                        # Only log media messages occasionally (1 in 50) to reduce noise
                        if random.random() < 0.02:  # ~2% chance to log
                            self.logger.debug(f"Received media chunk: {len(chunk)} bytes for {ws_id}")
                        self.audio_buffers[ws_id].extend(chunk)
                        if chunk == b'':
                            empty_byte_received = True
                
                elif data["event"] == "mark":
                    label = data["mark"]["name"]
                    sequence_number = data["sequenceNumber"]
                    self.logger.info(f"Mark {label} (sequence: {sequence_number}) played for {ws_id}")
                    
                    # Remove the mark from our tracking list
                    if label in self.marks[ws_id]:
                        self.marks[ws_id].remove(label)
                    
                    # If all marks are processed and we're flagged as speaking, clear the flag
                    if not self.marks[ws_id] and self.speaking_flags[ws_id].is_set():
                        self.speaking_flags[ws_id].clear()
                        self.accumulated_texts[ws_id] = ""
                        self.logger.info(f"AI finished speaking for {ws_id}, ready to listen")
                    
                    # Handle end call mark
                    if label == "end call":
                        self.logger.info(f"Ending call for {ws_id}")
                        self.exit_events[ws_id].set()
                        # Close Deepgram connection
                        if ws_id in self.deepgram_connections and self.deepgram_connections[ws_id]:
                            self.deepgram_connections[ws_id].send(json.dumps({"type": "CloseStream"}))
                        break
                
                elif data["event"] == "stop":
                    self.logger.info(f"Received stop event for {ws_id}")
                    if not self.exit_events[ws_id].is_set():
                        self.exit_events[ws_id].set()
                    break
                
                else:
                    self.logger.info(f"Unhandled event type: {data['event']} for {ws_id}")
                
                # Check if we have enough audio to send to Deepgram
                if len(self.audio_buffers[ws_id]) >= self.BUFFER_SIZE or empty_byte_received:
                    self.logger.info(f"Sending audio buffer to Deepgram for {ws_id}")
                    await self.outboxes[ws_id].put(bytes(self.audio_buffers[ws_id]))
                    self.audio_buffers[ws_id] = bytearray()
        except Exception as e:
            self.logger.error(f"Error in _handle_client_messages for {ws_id}: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
        
        self.logger.info(f"Finished handling client messages for {ws_id}")
    
    async def _handle_deepgram_sending(self, ws_id):
        """Send buffered audio to Deepgram"""
        if ws_id not in self.deepgram_ready_events:
            return
            
        await self.deepgram_ready_events[ws_id].wait()
        self.logger.info(f"Deepgram sender started for {ws_id}")
        
        while not self.exit_events[ws_id].is_set():
            try:
                chunk = await self.outboxes[ws_id].get()
                if ws_id in self.deepgram_connections and self.deepgram_connections[ws_id]:
                    await self.deepgram_connections[ws_id].send(chunk)
            except Exception as e:
                self.logger.error(f"Error sending to Deepgram for {ws_id}: {e}")
                if self.exit_events[ws_id].is_set():
                    break
    
    async def _handle_deepgram_receiving(self, ws_id):
        """Process transcriptions from Deepgram"""
        if ws_id not in self.deepgram_ready_events:
            self.logger.warning(f"Deepgram not initialized for {ws_id}")
            return
            
        await self.deepgram_ready_events[ws_id].wait()
        self.logger.info(f"Deepgram receiver started for {ws_id}")
        
        interaction_time = time.time()
        last_log_time = time.time()
        
        while not self.exit_events[ws_id].is_set():
            try:
                # Log heartbeat every 10 seconds to show the method is still running
                current_time = time.time()
                if current_time - last_log_time > 10:
                    self.logger.info(f"Deepgram receiver heartbeat for {ws_id}")
                    last_log_time = current_time
                
                if not self.deepgram_ready_events[ws_id].is_set():
                    self.logger.warning(f"Deepgram connection not ready for {ws_id}")
                    await asyncio.sleep(0.1)
                    continue
                    
                message_json = await self._check_for_transcript(ws_id)
                
                # If we got a transcription
                if message_json:
                    if message_json.get("is_final"):
                        self.accumulated_texts[ws_id] += " " + message_json["channel"]["alternatives"][0]["transcript"].strip()
                        self.logger.info(f"Final transcript for {ws_id}: {self.accumulated_texts[ws_id]}")
                    else:
                        # Log interim results occasionally
                        if current_time - last_log_time > 5:
                            interim_text = message_json["channel"]["alternatives"][0]["transcript"].strip()
                            self.logger.info(f"Interim transcript for {ws_id}: {interim_text}")
                    
                    interaction_time = time.time()
                    continue
                
                # Skip processing if AI is speaking
                if self.speaking_flags[ws_id].is_set():
                    self.logger.debug(f"AI is speaking, skipping processing for {ws_id}")
                    interaction_time = time.time()
                    continue
                
                # Check for silence
                elapsed_time = time.time() - interaction_time
                silence_threshold = 1 if len(self.accumulated_texts[ws_id].split()) < 30 else 1.2
                
                # Process accumulated text after silence
                if elapsed_time > silence_threshold and self.accumulated_texts[ws_id].strip():
                    call_sid = self.call_sids.get(ws_id)
                    if not call_sid:
                        self.logger.warning(f"No call SID for {ws_id}, cannot process response")
                        continue
                        
                    self.logger.info(f"Processing after {elapsed_time}s silence: {self.accumulated_texts[ws_id]}")
                    
                    # Start timing - Deepgram processing complete
                    deepgram_end_time = time.time()
                    self.logger.info(f"LATENCY_DEEPGRAM: Processing completed at {deepgram_end_time}")
                    
                    # Play filler audio while processing
                    await self._play_filler_audio(ws_id)
                    
                    # Process the response through conversation manager
                    self.logger.info(f"Sending user response to conversation manager for {ws_id}")
                    
                    # Start timing - LLM processing
                    llm_start_time = time.time()
                    self.logger.info(f"LATENCY_LLM: Processing started at {llm_start_time}")
                    
                    state_change, followup_question, error = await self.conversation_manager.process_response(
                        call_sid, 
                        self.accumulated_texts[ws_id].strip()
                    )
                    
                    # End timing - LLM processing
                    llm_end_time = time.time()
                    llm_duration = llm_end_time - llm_start_time
                    self.logger.info(f"LATENCY_LLM: Processing completed at {llm_end_time}, duration: {llm_duration:.2f}s")
                    
                    if error:
                        self.logger.error(f"Error processing response for {ws_id}: {error}")
                    
                    # If we have a follow-up question to play
                    if followup_question:
                        # Start timing - ElevenLabs processing
                        elevenlabs_start_time = time.time()
                        self.logger.info(f"LATENCY_ELEVENLABS: Processing started at {elevenlabs_start_time}")
                        
                        self.logger.info(f"Playing follow-up: {followup_question[:50]}... for {ws_id}")
                        # Stream audio directly from ElevenLabs to Twilio
                        await self._stream_elevenlabs_audio(ws_id, followup_question)
                        
                        # End timing - ElevenLabs processing
                        elevenlabs_end_time = time.time()
                        elevenlabs_duration = elevenlabs_end_time - elevenlabs_start_time
                        self.logger.info(f"LATENCY_ELEVENLABS: Processing completed at {elevenlabs_end_time}, duration: {elevenlabs_duration:.2f}s")
                        
                        # Calculate total latency
                        total_latency = elevenlabs_end_time - deepgram_end_time
                        self.logger.info(f"LATENCY_TOTAL: From user silence to AI speaking: {total_latency:.2f}s")
                        
                        await self._send_mark(ws_id)
                        self.speaking_flags[ws_id].set()
                    
                    # If we need to change state
                    if state_change:
                        self.logger.info(f"State change detected for {ws_id}, advancing state")
                        
                        # Start timing - State advancement
                        state_change_start_time = time.time()
                        self.logger.info(f"LATENCY_STATE_CHANGE: Processing started at {state_change_start_time}")
                        
                        advance_success, next_audio_or_text, advance_error = await self.conversation_manager.advance_state(call_sid)
                        
                        # End timing - State advancement
                        state_change_end_time = time.time()
                        state_change_duration = state_change_end_time - state_change_start_time
                        self.logger.info(f"LATENCY_STATE_CHANGE: Processing completed at {state_change_end_time}, duration: {state_change_duration:.2f}s")
                        
                        if advance_error:
                            self.logger.error(f"Error advancing state for {ws_id}: {advance_error}")
                        
                        if advance_success and next_audio_or_text:
                            # Start timing - ElevenLabs processing for state change
                            elevenlabs_state_start_time = time.time()
                            self.logger.info(f"LATENCY_ELEVENLABS_STATE: Processing started at {elevenlabs_state_start_time}")
                            
                            if isinstance(next_audio_or_text, bytes):
                                # Play pre-generated audio
                                self.logger.info(f"Playing pre-generated audio for {ws_id}")
                                await self._stream_audio(ws_id, next_audio_or_text)
                            else:
                                # Generate and stream audio
                                self.logger.info(f"Playing generated audio for {ws_id}: {next_audio_or_text[:50]}...")
                                await self._stream_elevenlabs_audio(ws_id, next_audio_or_text)
                                
                            # End timing - ElevenLabs processing for state change
                            elevenlabs_state_end_time = time.time()
                            elevenlabs_state_duration = elevenlabs_state_end_time - elevenlabs_state_start_time
                            self.logger.info(f"LATENCY_ELEVENLABS_STATE: Processing completed at {elevenlabs_state_end_time}, duration: {elevenlabs_state_duration:.2f}s")
                            
                            # Calculate total latency for state change
                            total_state_latency = elevenlabs_state_end_time - deepgram_end_time
                            self.logger.info(f"LATENCY_TOTAL_STATE: From user silence to AI speaking next question: {total_state_latency:.2f}s")
                            
                            await self._send_mark(ws_id)
                            self.speaking_flags[ws_id].set()
                        else:
                            self.logger.warning(f"No audio to play after state advancement for {ws_id}")
                    
                    # Clear accumulated text
                    self.accumulated_texts[ws_id] = ""
                
                # Handle long silence with no input
                elif elapsed_time > 5 and not self.accumulated_texts[ws_id] and not self.speaking_flags[ws_id].is_set():
                    self.logger.info(f"Long silence detected for {ws_id}, sending prompt")
                    silence_message = "You are not audible. Could you please repeat that?"
                    
                    # Stream audio for silence message directly
                    await self._stream_elevenlabs_audio(ws_id, silence_message)
                    await self._send_mark(ws_id)
                    self.speaking_flags[ws_id].set()
                    interaction_time = time.time()
                    
            except Exception as e:
                self.logger.error(f"Error in Deepgram receiver for {ws_id}: {e}")
                import traceback
                self.logger.error(traceback.format_exc())
                if self.exit_events[ws_id].is_set():
                    break
                
                # Sleep a bit to avoid tight loops in case of persistent errors
                await asyncio.sleep(0.5)
        
        self.logger.info(f"Deepgram receiver for {ws_id} exiting")

        
    
    async def _check_for_transcript(self, ws_id, timeout=0.1):
        """Check for new transcription from Deepgram"""
        try:
            if ws_id not in self.deepgram_connections or not self.deepgram_connections[ws_id]:
                self.logger.warning(f"No Deepgram connection for {ws_id} in _check_for_transcript")
                return None
            
            # Set timeout to prevent blocking indefinitely
            select_task = asyncio.ensure_future(
                self.deepgram_connections[ws_id].recv()
            )
            
            # Wait for message with timeout
            done, pending = await asyncio.wait(
                [select_task], timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
            
            # Cancel pending tasks
            for task in pending:
                task.cancel()
            
            # Check if we got a message
            if select_task in done:
                message = await select_task
                
                # Try to parse the message
                try:
                    message_json = json.loads(message)
                    
                    # Check for transcript in the response
                    if "channel" in message_json and "alternatives" in message_json["channel"]:
                        # Only log occasionally to avoid too much output
                        if random.random() < 0.1:  # 10% chance to log
                            self.logger.debug(f"Deepgram transcript received for {ws_id}")
                        return message_json
                    
                    # If there's a closed message
                    if message_json.get("type") == "ClosedStream":
                        self.logger.info(f"Deepgram stream closed for {ws_id}")
                        return None
                    
                    # Anything else is likely a status message
                    return None
                except json.JSONDecodeError:
                    self.logger.warning(f"Invalid JSON from Deepgram for {ws_id}: {message[:100]}...")
                    return None
            
            return None
        
        except asyncio.TimeoutError:
            # This is expected and not an error, so not logging it
            return None
        except asyncio.CancelledError:
            self.logger.info(f"Deepgram transcript check cancelled for {ws_id}")
            raise  # Re-raise cancellation to allow proper cleanup
        except Exception as e:
            self.logger.error(f"Error checking for transcript for {ws_id}: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return None
    
    async def _stream_audio(self, ws_id, audio_data): 
        """Stream audio data to Twilio"""
        try:
            if ws_id not in self.active_connections or not self.stream_sids.get(ws_id):
                return
                
            payload = {
                "event": "media",
                "streamSid": self.stream_sids[ws_id],
                "media": {"payload": base64.b64encode(audio_data).decode('utf-8')},
            }
            
            await self.active_connections[ws_id].send(json.dumps(payload))
            
        except Exception as e:
            self.logger.error(f"Error streaming audio: {e}")
    
    async def _stream_elevenlabs_audio(self, ws_id, text): 
        """Stream audio directly from ElevenLabs to Twilio"""
        try:
            if ws_id not in self.active_connections:
                self.logger.warning(f"Cannot stream audio - connection not active for {ws_id}")
                return
            
            # Debug: Log the stream SID
            self.logger.info(f"Stream SID for {ws_id} is {self.stream_sids.get(ws_id)}")
            
            # Temporarily allow streaming even if stream SID is None for debugging
            if not self.stream_sids.get(ws_id):
                self.logger.warning(f"Stream SID is None for {ws_id}, but continuing for debugging")
            
            self.logger.info(f"Streaming audio for text: {text[:30]}...")
            
            # Get audio chunks from ElevenLabs and stream directly to Twilio
            chunk_count = 0
            total_bytes = 0
            
            self.logger.info(f"Starting to stream audio chunks for {ws_id}")
            async for chunk in self.conversation_manager.elevenlabs_service.text_to_speech(text):
                # Create payload for Twilio (chunk is already base64 encoded)
                payload = {
                    "event": "media",
                    "streamSid": self.stream_sids.get(ws_id),
                    "media": {"payload": chunk},
                }
                
                # Send chunk to Twilio
                await self.active_connections[ws_id].send(json.dumps(payload))
                
                chunk_count += 1
                total_bytes += len(chunk)
                
                # Log progress occasionally
                if chunk_count % 10 == 0:
                    self.logger.info(f"Streamed {chunk_count} chunks ({total_bytes} bytes) for {ws_id}")
            
            self.logger.info(f"Finished streaming audio: {chunk_count} chunks, {total_bytes} bytes for {ws_id}")
                
        except Exception as e:
            self.logger.error(f"Error streaming ElevenLabs audio: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
    
    async def _send_mark(self, ws_id, occasion="default"):
        """Send a mark message to Twilio"""
        try:
            if ws_id not in self.active_connections or not self.stream_sids.get(ws_id):
                return
                
            if occasion == "default":
                mark_label = str(uuid.uuid4())
            elif occasion == "end call":
                mark_label = "end call"
                
            message = {
                "streamSid": self.stream_sids[ws_id],
                "event": "mark",
                "mark": {"name": mark_label}
            }
            
            await self.active_connections[ws_id].send(json.dumps(message))
            self.marks[ws_id].append(mark_label)
            
        except Exception as e:
            self.logger.error(f"Error sending mark: {e}")
    
    async def _play_filler_audio(self, ws_id):
        """Play a random filler audio while processing"""
        try:
            filler_audio = self.memory_c.get_random_filler_audio()
            if not filler_audio:
                self.logger.warning(f"No filler audio available for {ws_id}")
                return
                
            # Convert to base64 and stream
            filler_base64 = base64.b64encode(filler_audio).decode('utf-8')
            
            # Create media message
            media_message = {
                "event": "media",
                "streamSid": self.stream_sids.get(ws_id),
                "media": {
                    "payload": filler_base64
                }
            }
            
            # Send to websocket
            client_ws = self.active_connections.get(ws_id)
            if client_ws:
                await client_ws.send(json.dumps(media_message))
                self.logger.info(f"Played filler audio for {ws_id}")
        except Exception as e:
            self.logger.error(f"Error playing filler audio: {e}")
    
    async def _heartbeat(self, ws_id):
        """Send periodic heartbeat to keep the connection alive"""
        try:
            while not self.exit_events[ws_id].is_set():
                # Log heartbeat every 10 seconds
                self.logger.info(f"Heartbeat for {ws_id}")
                # Wait for 10 seconds or until exit event is set
                try:
                    await asyncio.wait_for(self.exit_events[ws_id].wait(), timeout=10)
                except asyncio.TimeoutError:
                    # This is expected, just continue
                    pass
        except Exception as e:
            self.logger.error(f"Error in heartbeat for {ws_id}: {e}")

    async def connect_to_deepgram(self, ws_id):
        """Connect to Deepgram for speech recognition"""
        try:
            self.logger.info(f"Connecting to Deepgram for {ws_id}")
            
            # Create a new Deepgram connection using the connect method
            deepgram_ws = await self.deepgram_service.connect()
            
            if not deepgram_ws:
                self.logger.error(f"Failed to create Deepgram socket for {ws_id}")
                return False
                
            self.deepgram_connections[ws_id] = deepgram_ws
            self.deepgram_ready_events[ws_id].set()
            self.logger.info(f"Connected to Deepgram for {ws_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error connecting to Deepgram for {ws_id}: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False

    def _cleanup_connection(self, ws_id):
        """Clean up resources when a connection closes"""
        self.logger.info(f"Cleaning up connection {ws_id}")
        
        # Set exit event
        if ws_id in self.exit_events:
            self.exit_events[ws_id].set()
            
        # Close Deepgram connection
        if ws_id in self.deepgram_connections and self.deepgram_connections[ws_id]:
            try:
                self.deepgram_connections[ws_id].send(json.dumps({"type": "CloseStream"}))
                self.logger.info(f"Sent close stream to Deepgram for {ws_id}")
            except Exception as e:
                self.logger.error(f"Error closing Deepgram connection for {ws_id}: {e}")
                
        # End conversation in Memory B
        if ws_id in self.call_sids:
            call_sid = self.call_sids[ws_id]
            try:
                # Use asyncio.create_task to avoid blocking
                asyncio.create_task(self.memory_b.end_conversation(call_sid))
                self.logger.info(f"Ending conversation for call {call_sid}")
            except Exception as e:
                self.logger.error(f"Error ending conversation for call {call_sid}: {e}")
                
        # Remove from tracking dictionaries
        for tracking_dict in [
            self.active_connections, self.deepgram_connections, 
            self.stream_sids, self.call_sids, self.exit_events,
            self.speaking_flags, self.deepgram_ready_events
        ]:
            if ws_id in tracking_dict:
                tracking_dict.pop(ws_id, None)
                
        # Clear buffers
        if ws_id in self.audio_buffers:
            self.audio_buffers[ws_id] = bytearray()
            
        if ws_id in self.accumulated_texts:
            self.accumulated_texts[ws_id] = ""
            
        if ws_id in self.marks:
            self.marks[ws_id] = []
            
        self.logger.info(f"Connection cleanup completed for {ws_id}")
import logging
import json
import base64
import asyncio
import uuid
import time
import random
import difflib
import os
from datetime import datetime

from typing import Dict, Any, Optional
import random

from memory.memory_a import MemoryA
from memory.memory_b import MemoryB
from memory.memory_c import MemoryC
from handlers.conversation_manager import ConversationManager
from services.Deepgram_service import DeepgramService
from services.audio_streaming_service import AudioStreamingService
from utils.text_analysis import detect_callback_request
from utils.merge_text import add_text_with_overlap_check
from services.call_categorization_service import CallCategorizationService
from utils.conversation_history_manager import ConversationHistoryManager


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
        memory_c: MemoryC, 
        conversation_manager: ConversationManager,
        deepgram_service: DeepgramService,
        config_loader,
        call_categorization_service: CallCategorizationService,
        shared_data: Dict = None,
        call_status_mapping: Dict = None,
        queue_messages: Dict = None
    ):
        self.memory_a = memory_a
        self.memory_b = memory_b
        self.memory_c = memory_c 
        self.conversation_manager = conversation_manager
        self.deepgram_service = deepgram_service
        self.config_loader = config_loader
        self.logger = logging.getLogger(__name__)
        
        # Initialize audio streaming service
        self.audio_service = AudioStreamingService(memory_c=memory_c, logger=self.logger)
        
        # Initialize conversation history manager
        self.history_manager = ConversationHistoryManager(logger=self.logger)
        
        # Outbound call tracking
        self.ws_to_call_sid = {}
        self.call_sids = {}
        self.stream_sids = {}
        self.exit_events = {}
        self.shared_data = shared_data or {}
        self.call_status_mapping = call_status_mapping or {}
        self.queue_messages = queue_messages or {}
        self.call_start_times = {}  # Track when calls start
        
        # Client-specific data
        self.active_connections = {}
        self.marks = {}
        self.speaking_flags = {}
        self.exit_events = {}
        self.listening_flags = {}
        self.ws_to_call_sid = {}  # Mapping of WebSocket ID to call SID
        
        # Audio buffering
        self.BUFFER_SIZE = 10 * 160  # Same as used in old implementation
        self.audio_buffers = {}
        self.outboxes = {}
        
        # Audio replay for interruptions
        self.current_audio_buffer = {}
        self.current_audio_text = {}
        self.interruption_detected = {}
        self.replay_counts = {}  # Track number of replays per session
        
        # Track first followup questions
        self.first_followup_flags = {}  # Track if this is the first followup for a question
        
        # Deepgram connections
        self.deepgram_connections = {}
        self.deepgram_ready_events = {}
        
        # Accumulated text from transcription
        self.accumulated_texts = {}
        
        # Track interaction times for silence detection
        self.interaction_times = {}
        
        # Speech processing state tracking
        self.speech_states = {}  # COLLECTING, FALLBACK, SILENCE
        self.fallback_active = {}
        self.fallback_start_times = {}
        self.fallback_duration = 0.5  # 0.3 seconds fallback period
        self.silence_threshold = 1.2  # 1 second silence threshold
        
        # Store complete call transcript history (question-answer pairs)
        self.temporary_transcripts = {}
        
        self.call_categorization_service = call_categorization_service
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
            self.listening_flags[ws_id] = asyncio.Event()
            self.listening_flags[ws_id].clear()
            self.accumulated_texts[ws_id] = ""
            self.audio_buffers[ws_id] = bytearray()
            self.outboxes[ws_id] = asyncio.Queue()
            self.marks[ws_id] = []
            
            # Initialize interruption tracking
            self.interruption_detected[ws_id] = False
            self.replay_counts[ws_id] = 0
            self.current_audio_buffer[ws_id] = None
            self.current_audio_text[ws_id] = ""
            
            # Initialize interaction time
            self.interaction_times[ws_id] = time.time()  # Initialize interaction time
            
            # Initialize speech state tracking
            self.speech_states[ws_id] = "COLLECTING"  # Start in collecting state
            self.fallback_active[ws_id] = False
            self.fallback_start_times[ws_id] = 0
            
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
                if self.exit_events[ws_id].is_set():
                    self.logger.info(f"Exit signal received for {ws_id}")
                    break
                    
                data = json.loads(message)
                
                # Only log non-media messages at INFO level to reduce noise
                if data.get('event') != 'media':
                    self.logger.info(f"Received WebSocket message for {ws_id}: {message[:100]}...")
                elif random.random() < 0.02:  # ~2% chance to log media messages at DEBUG level
                    self.logger.debug(f"Received WebSocket message for {ws_id}: {message[:100]}...")
                
                if data["event"] == "connected":
                    # Store the stream SID for later use
                    stream_sid = data.get("streamSid")
                    self.logger.info(f"Connected event data: {data}")
                    self.stream_sids[ws_id] = stream_sid
                    self.logger.info(f"Connected to stream {stream_sid} for {ws_id}")
                    
                    # Get call SID from parameters
                    if 'start' in data and 'callSid' in data['start']:
                        call_sid = data['start']['callSid']
                        self.call_sids[ws_id] = call_sid
                        self.ws_to_call_sid[ws_id] = call_sid  # Ensure mapping exists
                        self.logger.info(f"Call SID: {call_sid} for {ws_id}")
                        
                        # Initialize conversation in Memory B
                        await self.memory_b.initialize_conversation(call_sid)
                        
                        # Initialize first followup flag for this call
                        self.first_followup_flags[call_sid] = True
                        self.logger.info(f"Initialized first followup flag for call {call_sid}")
                    
                elif data.get('event') == 'start':
                    # Extract call SID if not already set
                    if not call_sid and 'callSid' in data['start']:
                        call_sid = data['start']['callSid']
                        self.call_sids[ws_id] = call_sid
                        self.ws_to_call_sid[ws_id] = call_sid  # Ensure mapping exists
                        self.logger.info(f"Call SID from start event: {call_sid} for {ws_id}")

                        # Log the entire start event structure for debugging
                        self.logger.info(f"Full start event structure: {json.dumps(data['start'], indent=2)}")
                        
                        # Try to get phone number from different possible locations
                        phone_number = 'unknown'
                        
                        # Check in customParameters if available
                        if 'customParameters' in data['start'] and data['start']['customParameters']:
                            self.logger.info(f"Custom parameters found: {data['start']['customParameters']}")
                            if 'From' in data['start']['customParameters']:
                                phone_number = data['start']['customParameters']['From']
                            elif 'from' in data['start']['customParameters']:
                                phone_number = data['start']['customParameters']['from']
                            elif 'PhoneNumber' in data['start']['customParameters']:
                                phone_number = data['start']['customParameters']['PhoneNumber']
                        
                        # Check directly in start object
                        if phone_number == 'unknown':
                            if 'from' in data['start']:
                                phone_number = data['start']['from']
                            elif 'From' in data['start']:
                                phone_number = data['start']['From']
                            elif 'to' in data['start']:
                                phone_number = data['start']['to']
                            elif 'To' in data['start']:
                                phone_number = data['start']['To']
                        
                        # Log what we found
                        self.logger.info(f"Call {call_sid} is from phone number {phone_number}")
                        
                        # Add phone number to transcript
                        self.history_manager.add_phone_number(call_sid, phone_number)
                        
                        # Initialize conversation in Memory B
                        await self.memory_b.initialize_conversation(call_sid)
                        
                        # Initialize first followup flag for this call
                        self.first_followup_flags[call_sid] = True
                        self.logger.info(f"Initialized first followup flag for call {call_sid}")
                    
                    # Extract stream SID if present in the start event
                    if 'streamSid' in data['start']:
                        stream_sid = data['start']['streamSid']
                        self.stream_sids[ws_id] = stream_sid
                        self.logger.info(f"Stream SID from start event: {stream_sid} for {ws_id}")
                    
                    # Log the full start event data for debugging
                    self.logger.info(f"Start event data: {data}")
                    
                    # Play greeting message immediately when start event is received
                    
                    greeting_text = "Hello, this is an AI screening call. Please say something to start the call."
                    self.logger.info(f"Playing greeting for {ws_id}")
                    audio_buffer = await self.audio_service.stream_elevenlabs_audio(
                        ws_id=ws_id,
                        text=greeting_text,
                        active_connections=self.active_connections,
                        stream_sids=self.stream_sids,
                        elevenlabs_service=self.conversation_manager.elevenlabs_service,
                        collect_audio=True
                    )
                    # Store the audio buffer and text for potential replay
                    self.current_audio_buffer[ws_id] = audio_buffer
                    self.current_audio_text[ws_id] = greeting_text
                    # Reset replay counter for new audio
                    self.replay_counts[ws_id] = 0
                    await self._send_mark(ws_id)
                    self.speaking_flags[ws_id].set()
                    self.logger.info(f"Greeting played, waiting for user response for {ws_id}")
                
                elif data.get('event') == 'media':
                    # logging media messages occasionally (1 in 50) to reduce noise
                    if random.random() < 0.02:  
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
                            # Activate listening mode
                            self.listening_flags[ws_id].set()
                            self.logger.info(f"Listening mode activated for {ws_id}")
                            # Reset interruption flag if it was set
                            if ws_id in self.interruption_detected and self.interruption_detected[ws_id]:
                                self.logger.info(f"Resetting interruption flag for {ws_id}")
                                self.interruption_detected[ws_id] = False
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
                    
            self.logger.info(f"WebSocket connection closed for {ws_id}")
            
        except Exception as e:
            self.logger.error(f"Error in WebSocket handler: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            
        finally:
            # Clean up resources
            await self._cleanup_connection(ws_id)
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
                    
                data = json.loads(message)
                
                
                if data.get('event') != 'media':
                    self.logger.info(f"Received WebSocket message for {ws_id}: {message[:100]}...")
                elif random.random() < 0.02:  
                    self.logger.debug(f"Received WebSocket message for {ws_id}: {message[:100]}...")
                
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
                    call_sid = self.call_sids[ws_id]
                    self.ws_to_call_sid[ws_id] = call_sid  # Ensure mapping exists
                    self.logger.info(f"Call started with SID: {call_sid} for {ws_id}")
                    
                    # Initialize call in conversation manager
                    self.logger.info(f"Initializing call in conversation manager for {ws_id}")
                    success, greeting_text, error = await self.conversation_manager.initialize_call(
                        call_sid
                    )
                    
                    self.logger.info(f"Call initialized with call_sid: {call_sid}")
                    
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
                        # logging media messages occasionally (1 in 50) to reduce noise
                        if random.random() < 0.02: 
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
                        
                        # Reset interruption flag if it was set
                        if ws_id in self.interruption_detected and self.interruption_detected[ws_id]:
                            self.logger.info(f"Resetting interruption flag for {ws_id}")
                            self.interruption_detected[ws_id] = False
                            
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
                
                
                await asyncio.sleep(0.5)
        
        self.logger.info(f"Deepgram sender for {ws_id} exiting")
    
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
                # Logging heartbeat every 10 seconds to show the method is still running
                current_time = time.time()
                if current_time - last_log_time > 10:
                    self.logger.info(f"Deepgram receiver heartbeat for {ws_id}")
                    last_log_time = current_time
                
                if not self.deepgram_ready_events[ws_id].is_set():
                    self.logger.warning(f"Deepgram connection not ready for {ws_id}")
                    await asyncio.sleep(0.1)
                    continue
                    
                message_json = await self._check_for_transcript(ws_id)
                
                # Only reset interaction time if there's actual content
                if message_json is not None:
                    if "channel" in message_json and "alternatives" in message_json["channel"] and message_json["channel"]["alternatives"]:
                        transcript = message_json["channel"]["alternatives"][0]["transcript"].strip()
                        if transcript:
                            interaction_time = time.time()
                    
                # If we got a transcription
                if message_json:
                    # Only process transcriptions when in listening mode
                    if not self.listening_flags[ws_id].is_set():
                        # Logging transcriptions received when not listening (for debugging)
                        if random.random() < 0.1:  
                            if "channel" in message_json and "alternatives" in message_json["channel"] and message_json["channel"]["alternatives"]:
                                ignored_text = message_json["channel"]["alternatives"][0]["transcript"].strip()
                                if ignored_text:
                                    self.logger.info(f"Ignored transcription (not listening): {ignored_text[:30]}... for {ws_id}")
                        continue
                        
                    if message_json.get("speech_final"):
                        self.logger.info(f"SPEECH_STATE: Speech final flag detected for {ws_id}")
                        
                        # Set fallback active immediately to prevent silence detection from triggering
                        self.fallback_active[ws_id] = True
                        self.fallback_start_times[ws_id] = time.time()
                        self.logger.info(f"SPEECH_STATE: Fallback activated immediately on speech_final for {ws_id}")
                        
                        transcript = message_json["channel"]["alternatives"][0]["transcript"].strip()
                        confidence = message_json["channel"]["alternatives"][0].get("confidence", 0)
                        if transcript:
                            added_text = await add_text_with_overlap_check(self, ws_id, transcript)
                            if added_text:
                                self.logger.info(f"Final transcript for {ws_id}: {self.accumulated_texts[ws_id]} (confidence: {confidence:.2f})")
                            
                            # Implement a 0.2s delay within the fallback period to catch additional speech
                            self.logger.info(f"SPEECH_STATE: Speech final detected, implementing 0.3s delay for {ws_id}")
                            await asyncio.sleep(0.3)
                            
                            # Schedule fallback after the delay
                            self.logger.info(f"SPEECH_STATE: Delay complete, scheduling fallback for {ws_id}")
                            asyncio.create_task(self._delayed_fallback_start(ws_id, 0))
                    elif message_json.get("is_final"):
                       
                        transcript = message_json["channel"]["alternatives"][0]["transcript"].strip()
                        confidence = message_json["channel"]["alternatives"][0].get("confidence", 0)
                        if transcript:
                            added_text = await add_text_with_overlap_check(self, ws_id, transcript)
                            if added_text:
                                self.logger.info(f"Interim final transcript for {ws_id}: {self.accumulated_texts[ws_id]} (confidence: {confidence:.2f})")
                    else:
                        # Process interim transcripts based on confidence
                        if "channel" in message_json and "alternatives" in message_json["channel"] and message_json["channel"]["alternatives"]:
                            interim_text = message_json["channel"]["alternatives"][0]["transcript"].strip()
                            confidence = message_json["channel"]["alternatives"][0].get("confidence", 0)
                            
                            # Log interim results occasionally
                            if current_time - last_log_time > 5:
                                self.logger.info(f"Interim transcript for {ws_id}: {interim_text} (confidence: {confidence:.2f})")
                            
                            # Only add high-confidence interim transcripts
                            # Lower threshold during fallback period for better continuity
                            confidence_threshold = 0.80 if self.fallback_active.get(ws_id, False) else 0.88
                            if confidence > confidence_threshold and interim_text:
                                added_text = await add_text_with_overlap_check(self, ws_id, interim_text)
                                if added_text:
                                    self.logger.info(f"High-confidence interim transcript added for {ws_id}: {added_text} (confidence: {confidence:.2f})")
                                    
                                # Reset fallback if we're in fallback period
                                if self.fallback_active[ws_id]:
                                    self.fallback_start_times[ws_id] = time.time()
                                    self.logger.info(f"SPEECH_STATE: Fallback period reset due to new speech for {ws_id}")
                                # Return to fallback if we're in silence threshold period
                                elif self.speech_states[ws_id] == "SILENCE":
                                    self.speech_states[ws_id] = "FALLBACK"
                                    self.fallback_active[ws_id] = True
                                    self.fallback_start_times[ws_id] = time.time()
                                    interaction_time = time.time()  # Reset interaction time
                                    self.logger.info(f"SPEECH_STATE: Returning to fallback period due to new speech during silence for {ws_id}")
                    
                    # Only reset interaction time if there's actual content
                    if "channel" in message_json and "alternatives" in message_json["channel"] and len(message_json["channel"]["alternatives"]) > 0:
                        transcript = message_json["channel"]["alternatives"][0]["transcript"].strip()
                        if transcript:
                            interaction_time = time.time()
                    continue
                
                # Skip processing if AI is speaking
                if ws_id in self.speaking_flags and self.speaking_flags[ws_id].is_set():
                    # Check if there's actual speech (interruption)
                    if message_json is not None:
                        # AI speech interruption detected
                        
                        if "channel" in message_json and "alternatives" in message_json["channel"] and len(message_json["channel"]["alternatives"]) > 0:
                            interim_text = message_json["channel"]["alternatives"][0]["transcript"].strip()
                            if interim_text:
                                # User interrupted AI speech
                                # Set interruption flag
                                self.interruption_detected[ws_id] = True
                                # Clear accumulated text to prevent it from being sent to LLM
                                self.accumulated_texts[ws_id] = ""
                                # Replay the audio
                                replay_result = await self._replay_audio(ws_id)
                                # Replay completed
                            else:
                                pass  # Empty transcript during AI speech
                        else:
                            pass  # No valid transcript during AI speech
                    
                    interaction_time = time.time()
                    continue
                
                current_time = time.time()
                
                # Calculate elapsed time
                elapsed_time = current_time - interaction_time
                
                # Check if we're in fallback period
                if self.fallback_active[ws_id]:
                    fallback_elapsed = current_time - self.fallback_start_times[ws_id]
                    
                    # If fallback period is complete, move to silence threshold state
                    if fallback_elapsed > self.fallback_duration:
                        self.fallback_active[ws_id] = False
                        self.speech_states[ws_id] = "SILENCE"
                        interaction_time = current_time  # Reset interaction time for silence threshold
                        self.logger.info(f"SPEECH_STATE: Fallback period complete ({fallback_elapsed:.2f}s), starting silence threshold for {ws_id}")
                    continue
                
                # Get current text and check if it ends with punctuation
                current_text = self.accumulated_texts[ws_id].strip()
                has_ending_punctuation = current_text and (current_text.endswith('.') or current_text.endswith('?') or current_text.endswith('!'))
                
                # Use standard threshold for punctuated text, extended for unpunctuated
                effective_threshold = self.silence_threshold
                if current_text and not has_ending_punctuation:
                    effective_threshold = 1.4 # Extended threshold for unpunctuated text
                    if elapsed_time > self.silence_threshold and elapsed_time <= effective_threshold:
                        self.logger.info(f"SPEECH_STATE: Extended silence threshold (1.4s) for unpunctuated text for {ws_id}")
                
                # Process accumulated text after silence threshold is met
                if elapsed_time > effective_threshold and current_text:
                    call_sid = self.ws_to_call_sid.get(ws_id)
                    if not call_sid:
                        self.logger.warning(f"No call SID for {ws_id}, cannot process response")
                        continue
                    
                    self.logger.info(f"SPEECH_STATE: Silence threshold met ({elapsed_time:.2f}s), processing final text for {ws_id}")    
                    self.logger.info(f"SPEECH_FINAL_BUFFER: {self.accumulated_texts[ws_id]}")
                    
                    # Deactivate listening mode
                    self.listening_flags[ws_id].clear()
                    self.logger.info(f"Listening mode deactivated for {ws_id}")
                    
                    # End timing - Deepgram processing
                    deepgram_end_time = time.time()
                    self.logger.info(f"LATENCY_DEEPGRAM: Processing completed at {deepgram_end_time}")
                    
                    # Record user silence detection time (1s + any additional processing)
                    silence_detection_time = elapsed_time
                    
                    # Get the current text
                    user_text = self.accumulated_texts[ws_id].strip()
                    
                    # Check if this is the initial response after greeting
                    conversation_state = await self.memory_b.get_state(call_sid)
                    current_state = 0 if conversation_state is None else conversation_state.state_index
                    is_initial_response = conversation_state is None or current_state == 0
                    
                    # Log user answer in conversation history
                    self.history_manager.log_user_answer(call_sid, user_text, current_state)
                    
                    # Check for callback request in initial response
                    if is_initial_response and detect_callback_request(user_text):
                        self.logger.info(f"Callback request detected in initial response: '{user_text}' for {ws_id}")
                        
                        # Play callback message
                        callback_message = "Okay, we will connect with you at a more suitable time. Thank you for your response."
                        
                        # Stream audio for silence message directly
                        await self._stream_elevenlabs_audio(ws_id, callback_message)
                        
                        # Add delay to ensure message is fully played
                        self.logger.info(f"Adding delay to ensure message is fully played for {ws_id}")
                        await asyncio.sleep(4.0)
                        
                        # End the call
                        self.logger.info(f"Ending call due to callback request for {ws_id}")
                        self.exit_events[ws_id].set()
                        return
                    
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
                        # Check if this is the first followup for this question
                        is_first_followup = self.first_followup_flags.get(call_sid, False)
                        
                        # Start timing - ElevenLabs processing
                        elevenlabs_start_time = time.time()
                        self.logger.info(f"LATENCY_ELEVENLABS: Processing started at {elevenlabs_start_time}")
                        
                        # Log followup question in conversation history
                        current_state = conversation_state.state_index
                        self.history_manager.log_ai_question(call_sid, followup_question, current_state)
                        
                        # Stream audio for follow-up question
                        self.logger.info(f"Playing follow-up question for {ws_id}: {followup_question[:50]}...")
                        if is_first_followup:
                            filler_start_time = time.time()
                            filler_delay = filler_start_time - llm_end_time
                            self.logger.info(f"LATENCY_FILLER_START: Delay between LLM completion and filler start: {filler_delay:.4f}s")
                            
                            # Calculate time from user silence to filler audio
                            time_to_filler = filler_start_time - deepgram_end_time
                            self.logger.info(f"LATENCY_TO_FILLER: Time from silence detection to filler audio: {time_to_filler:.2f}s")
                            
                            # Calculate total time including silence detection
                            total_to_filler = time_to_filler + silence_detection_time
                            self.logger.info(f"LATENCY_TOTAL_TO_FILLER: Time from user stops speaking to filler audio: {total_to_filler:.2f}s")
                            
                            self.logger.info(f"Playing filler audio for first followup for call {call_sid}")
                            
                            # Start buffering ElevenLabs chunks in background
                            chunk_queue = asyncio.Queue()
                            buffer_task = asyncio.create_task(self._buffer_elevenlabs_chunks(followup_question, chunk_queue))
                            
                            # Get the current state from memory_b
                            conversation_state = await self.memory_b.get_state(call_sid)
                            current_state = conversation_state.state_index if conversation_state else None
                            
                            # Play appropriate filler audio
                            await self.audio_service.play_filler_audio(ws_id, self.active_connections, self.stream_sids, current_state)
                            
                            # Mark that we've used the first followup
                            self.first_followup_flags[call_sid] = False
                            self.logger.info(f"First followup flag set to False for call {call_sid}")
                            
                            # Start streaming chunks as they become available
                            self.logger.info(f"Filler complete, streaming ElevenLabs chunks for {ws_id}")
                            self.logger.info(f"Playing follow-up: {followup_question[:50]}... for {ws_id}")
                            await self._stream_from_queue(ws_id, chunk_queue, followup_question)
                        else:
                            self.logger.info(f"Playing follow-up: {followup_question[:50]}... for {ws_id}")
                            # Stream audio directly from ElevenLabs to Twilio
                            await self._stream_elevenlabs_audio(ws_id, followup_question)
                        
                        # End timing - ElevenLabs processing
                        elevenlabs_end_time = time.time()
                        elevenlabs_duration = elevenlabs_end_time - elevenlabs_start_time
                        self.logger.info(f"LATENCY_ELEVENLABS: Processing completed at {elevenlabs_end_time}, duration: {elevenlabs_duration:.2f}s")
                        
                        # Calculate latency from silence detection to audio playing
                        processing_latency = elevenlabs_end_time - deepgram_end_time
                        self.logger.info(f"LATENCY_PROCESSING: From silence detection to AI speaking: {processing_latency:.2f}s")
                        
                        # Calculate total latency including silence detection
                        total_latency = processing_latency + silence_detection_time
                        self.logger.info(f"LATENCY_TOTAL: From user stops speaking to AI speaking: {total_latency:.2f}s")
                        
                        await self._send_mark(ws_id)
                        self.speaking_flags[ws_id].set()
                        # Clear accumulated text after playing a follow-up question
                        self.accumulated_texts[ws_id] = ""
                        
                        # Check if this is the final goodbye message
                        if followup_question and "thank you for your time" in followup_question.lower() and "goodbye" in followup_question.lower():
                            self.logger.info(f"Final message detected for {ws_id}, will close connection after audio completes")
                            # Set a flag to close the connection after the final message
                            asyncio.create_task(self._close_after_final_message(ws_id))
                    # If we need to change state
                    if state_change:
                        self.logger.info(f"\nState change detected for {ws_id}, advancing state\n-------------------------------------------------\n")
                        
                        # Clear transcript buffer to prevent answers from bleeding into next question
                        self.accumulated_texts[ws_id] = ""
                        
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
                        
                        if advance_success:
                            # Clear accumulated text when advancing to a new state
                            self.accumulated_texts[ws_id] = ""
                            
                            # Reset first followup flag for new question
                            self.first_followup_flags[call_sid] = True
                            self.logger.info(f"Reset first followup flag for call {call_sid} - new question")
                            
                            if next_audio_or_text:
                                # Get the current state and question text from Memory B
                                updated_state = await self.memory_b.get_state(call_sid)
                                if updated_state:
                                    # Log the main question in conversation history
                                    self.history_manager.log_ai_question(call_sid, updated_state.original_question, updated_state.state_index)
                                
                                # Start timing - ElevenLabs processing for state change
                                elevenlabs_state_start_time = time.time()
                                self.logger.info(f"LATENCY_ELEVENLABS_STATE: Processing started at {elevenlabs_state_start_time}")
                                
                                if isinstance(next_audio_or_text, bytes):
                                    # Play pre-generated audio
                                    self.logger.info(f"Playing pre-generated audio for {ws_id}")
                                   
                                    streaming_state_start_time = time.time()
                                    await self._stream_audio(ws_id, next_audio_or_text)
                                else:
                                    # Generate and stream audio
                                    self.logger.info(f"Playing generated audio for {ws_id}: {next_audio_or_text[:50]}...")
                                    
                                    streaming_state_start_time = time.time()
                                    await self._stream_elevenlabs_audio(ws_id, next_audio_or_text)
                                    
                                # End timing - ElevenLabs processing for state change
                                elevenlabs_state_end_time = time.time()
                                elevenlabs_state_duration = elevenlabs_state_end_time - elevenlabs_state_start_time
                                streaming_state_duration = elevenlabs_state_end_time - streaming_state_start_time
                                self.logger.info(f"LATENCY_ELEVENLABS_STATE: Processing completed at {elevenlabs_state_end_time}, duration: {elevenlabs_state_duration:.2f}s (streaming: {streaming_state_duration:.2f}s)")
                                
                                # Calculate total latency for state change
                                total_state_latency = elevenlabs_state_end_time - deepgram_end_time
                                self.logger.info(f"LATENCY_TOTAL_STATE: From user silence to AI speaking next question: {total_state_latency:.2f}s")
                                
                                await self._send_mark(ws_id)
                                self.speaking_flags[ws_id].set()
                                
                                # Check if this is the final goodbye message
                                if isinstance(next_audio_or_text, str) and "thank you for your time" in next_audio_or_text.lower() and "goodbye" in next_audio_or_text.lower():
                                    self.logger.info(f"Final message detected for {ws_id}, will close connection after audio completes")
                                    # Set a flag to close the connection after the final message
                                    asyncio.create_task(self._close_after_final_message(ws_id))
                            else:
                                self.logger.warning(f"No audio to play after state advancement for {ws_id}")
                    
                    
                
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
                if ws_id in self.exit_events and self.exit_events[ws_id].is_set():
                    break
                
                
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
                    
                    # Debug log to see raw message structure
                    if random.random() < 0.1:  # Log only 10% of messages to avoid flooding
                        pass  # Deepgram message received
                    
                    # Check for transcript in the response
                    if "channel" in message_json and "alternatives" in message_json["channel"]:
                        # Debug log for speech_final flag
                        # if message_json.get("speech_final"):
                        #     self.logger.info(f"DEBUG: speech_final flag detected in Deepgram response for {ws_id}")
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
            
            return None
        except asyncio.CancelledError:
            self.logger.info(f"Deepgram transcript check cancelled for {ws_id}")
            raise  
        except Exception as e:
            self.logger.error(f"Error checking for transcript for {ws_id}: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return None
    

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

            
    
    async def _replay_audio(self, ws_id):
        """Replay the current audio when interrupted"""
        try:
            # Check if buffer exists
            if ws_id not in self.current_audio_buffer or not self.current_audio_buffer[ws_id]:
                self.logger.error(f"No audio buffer to replay for {ws_id}")
                return False
            
            # Validate buffer size
            min_buffer_size = 1000  # Minimum size in bytes for a valid audio buffer
            if len(self.current_audio_buffer[ws_id]) < min_buffer_size:
                self.logger.error(f"Audio buffer too small to replay for {ws_id}")
                return False
                
            # Check replay count
            if ws_id not in self.replay_counts:
                self.replay_counts[ws_id] = 0
            
            # Increase replay limit to 3 for testing
            if self.replay_counts[ws_id] >= 3:
                self.logger.error(f"Replay limit reached for {ws_id}, not replaying")
                return False
            
            self.replay_counts[ws_id] += 1
            
            self.logger.info(f"Replaying audio due to interruption for {ws_id}")
            
            # If we have text, log it
            if ws_id in self.current_audio_text and self.current_audio_text[ws_id]:
                pass  # Replaying text
            
            # Stream the buffered audio
            pass  # Streaming audio buffer
            await self.audio_service.stream_audio(
                ws_id=ws_id,
                audio_data=self.current_audio_buffer[ws_id],
                active_connections=self.active_connections,
                stream_sids=self.stream_sids
            )
            
            # Send mark and set speaking flag
            # Setting speaking flag
            await self._send_mark(ws_id)
            self.speaking_flags[ws_id].set()
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error replaying audio: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False

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
            

    async def _cleanup_connection(self, ws_id):
        """Clean up resources when a connection closes"""
        self.logger.info(f"Cleaning up connection {ws_id}")
        
        # Set exit event
        if ws_id in self.exit_events:
            self.exit_events[ws_id].set()
            
        # Close Deepgram connection
        if ws_id in self.deepgram_connections and self.deepgram_connections[ws_id]:
            try:
                await self.deepgram_connections[ws_id].send(json.dumps({"type": "CloseStream"}))
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
            self.speaking_flags, self.deepgram_ready_events,
            self.current_audio_buffer, self.current_audio_text, self.interruption_detected, self.replay_counts,
            self.audio_buffers, self.accumulated_texts, self.marks, self.interaction_times,
            self.first_followup_flags, self.speech_states, self.fallback_active, self.fallback_start_times
        ]:
            if ws_id in tracking_dict:
                tracking_dict.pop(ws_id, None)
                
        self.logger.info(f"Connection cleanup completed for {ws_id}")
        
        # Process transcript and categorize call
        try:
            # Use asyncio.create_task to avoid blocking
            asyncio.create_task(self.transcript_cleanup(ws_id))
            self.logger.info(f"Started transcript cleanup for {ws_id}")
        except Exception as e:
            self.logger.error(f"Error starting transcript cleanup for {ws_id}: {e}")

    async def _stream_audio(self, ws_id, audio_data):
        """Stream pre-generated audio data to Twilio"""
        return await self.audio_service.stream_audio(
            ws_id=ws_id,
            audio_data=audio_data,
            active_connections=self.active_connections,
            stream_sids=self.stream_sids
        )
        
    async def _stream_elevenlabs_audio(self, ws_id, text, is_final_message=False):
        """Stream audio generated by ElevenLabs to Twilio"""
        audio_buffer = await self.audio_service.stream_elevenlabs_audio(
            ws_id=ws_id,
            text=text,
            active_connections=self.active_connections,
            stream_sids=self.stream_sids,
            elevenlabs_service=self.conversation_manager.elevenlabs_service,
            collect_audio=True
        )
        
        # Store the audio buffer and text for potential replay
        self.current_audio_buffer[ws_id] = audio_buffer
        self.current_audio_text[ws_id] = text
        # Reset replay counter for new audio
        self.replay_counts[ws_id] = 0
        
        # Detect if this is a final message
        if is_final_message or text.startswith("Thank you for your time"):
            self.logger.info(f"Final message detected for {ws_id}, will close connection after audio completes")
            
            # Schedule connection close after audio completes
            asyncio.create_task(self._close_after_final_message(ws_id))
        
        return audio_buffer

    async def _buffer_elevenlabs_chunks(self, text, chunk_queue):
        """Buffer chunks from ElevenLabs async generator and put them in queue"""
        buffer_start_time = time.time()
        chunk_count = 0
        async for chunk in self.conversation_manager.elevenlabs_service.text_to_speech(text):
            await chunk_queue.put(chunk)
            chunk_count += 1
            if chunk_count % 5 == 0:  # Logging every 5 chunks
                current_time = time.time()
                self.logger.info(f"BUFFER_PROGRESS: Collected {chunk_count} chunks in {current_time - buffer_start_time:.2f}s")
        
        # Signal end of chunks
        await chunk_queue.put(None)
        buffer_end_time = time.time()
        buffer_duration = buffer_end_time - buffer_start_time
        self.logger.info(f"BUFFER_COMPLETE: Collected all {chunk_count} chunks in {buffer_duration:.2f}s")
        return chunk_count

    async def _stream_from_queue(self, ws_id, chunk_queue, text):
        """Stream chunks from queue as they become available"""
        stream_start_time = time.time()
        chunks = []
        chunk_count = 0
        
        while True:
            chunk = await chunk_queue.get()
            if chunk is None:  # End of chunks
                break
                
            # Stream the chunk
            media_message = {
                "event": "media",
                "streamSid": self.stream_sids.get(ws_id),
                "media": {"payload": chunk}
            }
            await self.active_connections[ws_id].send(json.dumps(media_message))
            chunks.append(chunk)
            chunk_count += 1
            
            if chunk_count % 5 == 0:
                current_time = time.time()
                self.logger.info(f"STREAM_PROGRESS: Streamed {chunk_count} chunks in {current_time - stream_start_time:.2f}s")
        
        stream_end_time = time.time()
        stream_duration = stream_end_time - stream_start_time
        self.logger.info(f"STREAM_COMPLETE: Streamed all {chunk_count} chunks in {stream_duration:.2f}s")
        
        # Store audio for potential replay
        audio_data = b''.join([base64.b64decode(chunk) for chunk in chunks])
        self.current_audio_buffer[ws_id] = audio_data
        self.current_audio_text[ws_id] = text
        self.replay_counts[ws_id] = 0

    async def _close_after_final_message(self, ws_id):
        """Close the connection after the final message"""
        try:
            self.logger.info(f"Waiting for final message to complete for {ws_id}")
            # Wait a few seconds for the audio to finish playing
            await asyncio.sleep(5)

            self.logger.info(f"Final message completed, closing connection for {ws_id}")
            
            # Print the final transcript
            call_sid = self.ws_to_call_sid.get(ws_id)
            if call_sid:
                self.logger.info(f"Final transcript for call {call_sid} processed")
                
                # Generate cleaned transcript
                self.logger.info(f"Generating cleaned transcript for call {call_sid}")
                cleaned_transcript = self.history_manager.get_cleaned_transcript(call_sid, self.config_loader)
                if cleaned_transcript:
                    self.logger.info(f"Cleaned transcript generated successfully for {call_sid}")
            
            self.exit_events[ws_id].set()
            
            # Close Deepgram connection before cleanup
            try:
                if ws_id in self.deepgram_connections and self.deepgram_connections[ws_id]:
                    await self.deepgram_connections[ws_id].send(json.dumps({"type": "CloseStream"}))
                    self.logger.info(f"Closed Deepgram stream for {ws_id} in final message handler")
            except Exception as dg_error:
                self.logger.error(f"Error closing Deepgram connection for {ws_id}: {dg_error}")
                
        except Exception as e:
            self.logger.error(f"Error closing connection after final message for {ws_id}: {e}")
            # Still try to set exit event even if there was an error
            try:
                self.exit_events[ws_id].set()
            except Exception:
                pass

    async def transcript_cleanup(self, ws_id):
        """Process transcript and categorize call after connection closes"""
        try:
            self.logger.info(f"Processing transcript for {ws_id}")
            
            
            # Get call_sid and generate cleaned transcript if not already done
            call_sid = self.ws_to_call_sid.get(ws_id)
            if call_sid:
                self.logger.info(f"Generating cleaned transcript for call {call_sid} during cleanup")
                try:
                    # Check if transcript exists
                    raw_transcript = self.history_manager.get_transcript(call_sid)
                    if raw_transcript:
                        # Generate cleaned transcript if not already done
                        cleaned_transcript = self.history_manager.get_cleaned_transcript(call_sid, self.config_loader)
                        if cleaned_transcript:
                            self.logger.info(f"Cleaned transcript generated during cleanup for {call_sid}")
                        
                        # Get phone number for this call
                        phone_number = self.history_manager.phone_numbers.get(call_sid, "unknown")
                        
                        # Categorize the call based on the transcript
                        try:
                            category = self.call_categorization_service.categorize_from_transcript(
                                call_sid=call_sid,
                                transcript=raw_transcript
                            )
                            self.logger.info(f"Call {call_sid} categorized as {category.name}")
                            # Add call status to cleaned transcript
                            if cleaned_transcript:
                                # Create JSON data from cleaned transcript
                                call_data = {
                                    "call_sid": call_sid,
                                    "phone_number": phone_number,
                                    "call_status": category.name,
                                    "timestamp": datetime.now().isoformat(),
                                    "transcript": cleaned_transcript
                                }
                                
                                # Print the call data directly
                                self.logger.info("===== CALL DISCONNECTED: FRONTEND DATA GENERATED =====")
                                print("\n===== FRONTEND JSON DATA =====")
                                print(json.dumps(call_data, indent=2))
                                print("===== END FRONTEND JSON DATA =====")
                        except Exception as categorization_error:
                            self.logger.error(f"Error categorizing call {call_sid}: {categorization_error}")
                    else:
                        self.logger.info(f"No transcript found for {call_sid} during cleanup")
                except Exception as transcript_error:
                    self.logger.error(f"Error generating cleaned transcript during cleanup: {transcript_error}")
        except Exception as e:
            self.logger.error(f"Error cleaning up connection for {ws_id}: {e}")
    

    async def _delayed_fallback_start(self, ws_id, delay_seconds):
        """"""
        try:
            # Log when the delayed fallback is scheduled
            self.logger.info(f"SPEECH_STATE: Scheduled fallback after {delay_seconds}s delay for {ws_id}")
            
            # Wait for the specified delay
            await asyncio.sleep(delay_seconds)
            
            # Check if we should still enter fallback (might have been reset by new speech)
            if ws_id in self.listening_flags and self.listening_flags[ws_id].is_set():
                self.logger.info(f"SPEECH_STATE: Fallback state entered after delay for {ws_id}")
                self.speech_states[ws_id] = "FALLBACK"
                # No need to set fallback_active and fallback_start_times again as they're already set
            else:
                self.logger.info(f"SPEECH_STATE: Fallback state not entered (listening mode inactive) for {ws_id}")
                # Reset fallback if listening mode was deactivated
                self.fallback_active[ws_id] = False
        except Exception as e:
            self.logger.error(f"Error in delayed fallback start for {ws_id}: {e}")

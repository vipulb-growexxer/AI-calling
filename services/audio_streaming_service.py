#!/usr/bin/env python3
"""
Audio Streaming Service for AI Call System
Handles streaming audio to Twilio WebSockets
"""

import base64
import json
import logging
import asyncio
from typing import Dict, Optional, Any

from memory.memory_c import MemoryC

class AudioStreamingService:
    """Service for streaming audio to Twilio WebSockets"""
    
    def __init__(self, memory_c: MemoryC, logger=None):
        """Initialize the audio streaming service"""
        self.memory_c = memory_c
        self.logger = logger or logging.getLogger(__name__)
        
    async def play_filler_audio(self, ws_id: str, active_connections: Dict, stream_sids: Dict, state: int = None):
        """Play a filler audio while processing, using state-specific filler if available"""
        try:
            # Get appropriate filler audio based on state
            if state is not None:
                filler_audio = self.memory_c.get_state_filler_audio(state)
            else:
                filler_audio = self.memory_c.get_random_filler_audio()
                
            if not filler_audio:
                self.logger.warning(f"No filler audio available for {ws_id}")
                return
                
            # Convert to base64 and stream
            filler_base64 = base64.b64encode(filler_audio).decode('utf-8')
            
            # Create media message
            media_message = {
                "event": "media",
                "streamSid": stream_sids.get(ws_id),
                "media": {
                    "payload": filler_base64
                }
            }
            
            # Send to websocket
            client_ws = active_connections.get(ws_id)
            if client_ws:
                await client_ws.send(json.dumps(media_message))
                self.logger.info(f"Played filler audio for {ws_id}" + (f" (state {state})" if state else ""))
        except Exception as e:
            self.logger.error(f"Error playing filler audio: {e}")

    async def stream_audio(self, ws_id: str, audio_data: bytes, active_connections: Dict, stream_sids: Dict):
        """Stream pre-generated audio to Twilio"""
        try:
            if ws_id not in active_connections:
                self.logger.error(f"INTERRUPTION_DEBUG: Cannot stream audio - connection not active for {ws_id}")
                return
                
            if ws_id not in stream_sids:
                self.logger.error(f"INTERRUPTION_DEBUG: Cannot stream audio - stream SID not found for {ws_id}")
                return
                
            # Convert to base64
            audio_base64 = base64.b64encode(audio_data).decode('utf-8')
            
            # Create media message
            media_message = {
                "event": "media",
                "streamSid": stream_sids.get(ws_id),
                "media": {
                    "payload": audio_base64
                }
            }
            
            # Send to websocket
            self.logger.info(f"INTERRUPTION_DEBUG: Sending {len(audio_data)} bytes of audio to WebSocket for {ws_id}")
            await active_connections[ws_id].send(json.dumps(media_message))
            self.logger.info(f"INTERRUPTION_DEBUG: Successfully streamed {len(audio_data)} bytes of audio for {ws_id}")
            
        except Exception as e:
            self.logger.error(f"INTERRUPTION_DEBUG: Error streaming audio: {e}")
            import traceback
            self.logger.error(traceback.format_exc())

    async def stream_elevenlabs_audio(self, ws_id: str, text: str, active_connections: Dict, 
                                     stream_sids: Dict, elevenlabs_service: Any, collect_audio: bool = False):
        """Stream audio directly from ElevenLabs to Twilio"""
        try:
            if ws_id not in active_connections:
                self.logger.warning(f"Cannot stream audio - connection not active for {ws_id}")
                return None if collect_audio else False
            
            # Debug: Log the stream SID
            self.logger.info(f"Stream SID for {ws_id} is {stream_sids.get(ws_id)}")
            
            # Temporarily allow streaming even if stream SID is None for debugging
            if not stream_sids.get(ws_id):
                self.logger.warning(f"Stream SID is None for {ws_id}, but continuing for debugging")
            
            self.logger.info(f"Streaming audio for text: {text[:30]}...")
            
            # Initialize audio buffer if collecting
            audio_buffer = bytearray() if collect_audio else None
            
            # Get audio chunks from ElevenLabs and stream directly to Twilio
            chunk_count = 0
            async for chunk in elevenlabs_service.text_to_speech(text):
                # Store chunk in buffer if collecting
                if collect_audio:
                    # Need to decode from base64 first since chunks are base64 encoded
                    audio_buffer.extend(base64.b64decode(chunk))
                
                # Convert chunk to base64
                chunk_base64 = chunk  # Already base64 encoded by ElevenLabs service
                
                # Create media message
                media_message = {
                    "event": "media",
                    "streamSid": stream_sids.get(ws_id),
                    "media": {
                        "payload": chunk_base64
                    }
                }
                
                # Send to websocket
                await active_connections[ws_id].send(json.dumps(media_message))
                chunk_count += 1
                
            self.logger.info(f"Streamed {chunk_count} chunks of audio for {ws_id}")
            
            # Return the collected audio if requested, otherwise return success flag
            return audio_buffer if collect_audio else True
            
        except Exception as e:
            self.logger.error(f"Error streaming ElevenLabs audio: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return None if collect_audio else False
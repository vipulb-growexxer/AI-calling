"""
Memory A (Question Bank)
- Stores pre-generated audio for all questions indexed by state (1,2,3,...)
- Audio is generated asynchronously during initial greeting
- Questions are converted to audio via ElevenLabs and stored before actual conversation
"""

import json
import asyncio
from typing import Dict, Optional, List, Any
import logging

class MemoryA:
    """
    Memory A (Question Bank) - Stores pre-generated audio for questions indexed by state
    """
    def __init__(self):
        self.question_audio_bank: Dict[int, bytes] = {}  # state_index -> audio_bytes
        self.questions_data: List[Dict[str, Any]] = []
        self.is_initialized = False
        self.logger = logging.getLogger(__name__)

    async def initialize_with_questions(self, questions_file_path: str):
        """Load questions from JSON file"""
        try:
            with open(questions_file_path, 'r') as f:
                self.questions_data = json.load(f)
            self.logger.info(f"Loaded {len(self.questions_data)} questions into Memory A")
            self.is_initialized = True
            return True
        except Exception as e:
            self.logger.error(f"Failed to initialize Memory A with questions: {str(e)}")
            return False

    async def pre_generate_audio(self, tts_service, questions_data=None):
        """
        Pre-generate audio for all questions and store in memory
        This is called asynchronously during initial greeting
        """
        if questions_data:
            self.questions_data = questions_data
            
        if not self.questions_data:
            self.logger.error("No questions data available for audio pre-generation")
            return False
            
        try:
            for question_data in self.questions_data:
                state = question_data.get('state')
                question_text = question_data.get('question')
                
                if not state or not question_text:
                    self.logger.warning(f"Skipping invalid question data: {question_data}")
                    continue
                
                # Skip check for skip_llm_processing - we still need audio for all questions
                
                # Generate audio using TTS service
                audio_data = await tts_service.text_to_speech_full(question_text)
                
                # Store in memory bank
                await self.store_question_audio(state, audio_data)
                self.logger.info(f"Pre-generated audio for state {state}")
                
            return True
        except Exception as e:
            self.logger.error(f"Error pre-generating audio: {str(e)}")
            return False

    async def store_question_audio(self, state: int, audio_data: bytes) -> None:
        """Store audio data for a specific state"""
        self.question_audio_bank[state] = audio_data
        
    async def get_question_audio(self, state: int) -> Optional[bytes]:
        """Retrieve audio data for a specific state"""
        return self.question_audio_bank.get(state)
        
    def get_question_data(self, state: int) -> Optional[Dict[str, Any]]:
        """Get question data for a specific state"""
        for question in self.questions_data:
            if question.get('state') == state:
                return question
        return None

    def is_audio_ready(self, state: int) -> bool:
        """Check if audio for a specific state is ready"""
        return state in self.question_audio_bank

    async def clear(self):
        """Clear all stored audio data"""
        self.question_audio_bank.clear()
        self.logger.info("Memory A cleared")


# server.py (new implementation)
# memory/memory_a.py
# memory/memory_b.py
# memory/init.py
# handlers/twilio_webhook.py
# handlers/websocket_manager.py (new implementation instead of websocket_handler.py)
# config/config_loader.py
# services/twilio_service.py


# Memory A will reside in the server process's memory when a call gets connected. The implementation flow would be:

# When the server starts up, it will create an instance of Memory A
# This instance will be maintained for the lifetime of the server process
# When a call connects:
# The server will use this Memory A instance to load questions
# Then it will pre-generate audio for those questions
# All this data stays in server memory (RAM)
# Specifically, in our architecture:

# The Memory A instance would be created when the server starts
# It would be passed to the appropriate handlers (like Twilio webhook and websocket manager)
# These handlers would use the same Memory A instance for all calls
# The audio data stored in Memory A remains available as long as the server is running
# If the server restarts, the Memory A instance would be recreated, and audio would need to be generated again. 
# If you need persistence across server restarts, we would need to add disk storage capabilities.
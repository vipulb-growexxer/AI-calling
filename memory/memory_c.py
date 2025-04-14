"""
Memory C (Filler Phrases)
- Stores pre-generated audio for filler phrases
- Used to fill silence gaps during processing
- Provides natural transitions between user responses and AI questions
"""

import json
import random
import logging
from typing import Dict, List, Optional, Any

class MemoryC:
    """
    Memory C (Filler Phrases) - Stores pre-generated audio for filler phrases
    """
    def __init__(self):
        self.filler_audio_bank: Dict[str, bytes] = {}  # filler_key -> audio_bytes
        self.filler_data: Dict[str, str] = {}  # filler_key -> filler_text
        self.is_initialized = False
        self.logger = logging.getLogger(__name__)

    async def initialize_with_fillers(self, fillers_dict: Dict[str, str] = None):
        """
        Initialize Memory C with filler phrases
        
        Args:
            fillers_dict: Dictionary of filler_key -> filler_text
        """
        if fillers_dict:
            self.filler_data = fillers_dict
            self.logger.info(f"Loaded {len(self.filler_data)} fillers into Memory C")
            self.is_initialized = True
            return True
        else:
            # Default fillers if none provided - organized by state for followup questions
            # Using hesitation markers and elongated vowels to sound more natural
            self.filler_data = {
                # State 1 followup
                "state_1_followup": "Okay... tell me",
                
                # State 2 followup
                "state_2_followup": "Mmhmm... and",
                
                # State 4 followup
                "state_4_followup": "Got it. Can you please share",
                
                # State 5 followup
                "state_5_followup": "Okay and",
                
                # Generic fillers for fallback
                "generic_1": "I see...",
                "generic_2": "Hmm...",
                "generic_3": "Interesting..."
            }
            self.logger.info(f"Loaded {len(self.filler_data)} default fillers into Memory C")
            self.is_initialized = True
            return True

    async def pre_generate_audio(self, tts_service):
        """
        Pre-generate audio for all filler phrases and store in memory
        """
        if not self.filler_data:
            self.logger.error("No filler data available for audio pre-generation")
            return False
            
        try:
            for filler_key, filler_text in self.filler_data.items():
                self.logger.info(f"Generating audio for filler: {filler_key}")
                
                # Generate audio using the TTS service
                audio_data = await tts_service.text_to_speech_full(filler_text)
                
                # Store in memory
                self.filler_audio_bank[filler_key] = audio_data
                
                self.logger.info(f"Audio generated for filler: {filler_key}")
                
            self.logger.info(f"Pre-generated audio for {len(self.filler_audio_bank)} fillers")
            return True
            
        except Exception as e:
            self.logger.error(f"Error pre-generating audio for fillers: {str(e)}")
            return False

    def get_filler_audio(self, filler_key: str) -> Optional[bytes]:
        """
        Get the audio for a specific filler by key
        """
        return self.filler_audio_bank.get(filler_key)

    def get_state_filler_audio(self, state: int) -> Optional[bytes]:
        """
        Get filler audio for a specific state's followup question
        
        Args:
            state: The conversation state number
        """
        filler_key = f"state_{state}_followup"
        
        # Check if we have a filler for this state
        if filler_key in self.filler_audio_bank:
            return self.filler_audio_bank.get(filler_key)
            
        # Fall back to generic filler if no state-specific one exists
        return self.get_random_filler_audio()

    def get_random_filler_audio(self) -> Optional[bytes]:
        """
        Get a random filler audio from the bank (generic fillers only)
        """
        if not self.filler_audio_bank:
            self.logger.warning("No filler audio available")
            return None
            
        # Filter for generic fillers
        generic_keys = [k for k in self.filler_audio_bank.keys() if k.startswith("generic_")]
        
        if not generic_keys:
            # If no generic fillers, use any available filler
            filler_key = random.choice(list(self.filler_audio_bank.keys()))
        else:
            filler_key = random.choice(generic_keys)
            
        return self.filler_audio_bank.get(filler_key)
    
    def get_random_filler_text(self) -> Optional[str]:
        """
        Get a random filler text
        """
        if not self.filler_data:
            self.logger.warning("No filler text available")
            return None
            
        filler_key = random.choice(list(self.filler_data.keys()))
        return self.filler_data.get(filler_key)

    def is_audio_ready(self, filler_key: str) -> bool:
        """
        Check if audio for a specific filler is ready
        """
        return filler_key in self.filler_audio_bank
    
    def get_all_filler_keys(self) -> List[str]:
        """
        Get all available filler keys
        """
        return list(self.filler_data.keys())

import logging
import json
import time
import os
import re
from enum import Enum, auto
from datetime import datetime
from typing import Dict, Any, Optional, List, Set


class CallCategory(Enum):
    """
    Enum representing different call categories for classification.
    """
    NO_PICKUP = auto()      # Call not picked up
    BUSY_DISCONNECT = auto() # Disconnects right after greeting or immediate disconnect
    DISCONNECTED = auto()   # Call started but disconnected before completing all questions
    COMPLETED = auto()      # Call completed successfully with all questions answered


class CallCategorizationService:
    """
    Service to categorize calls based on user behavior and responses.
    
    This service tracks call categories and can upload this data to cloud storage.
    It's designed to work with the existing WebSocketManager without modifying it.
    """
    
    def __init__(self, logger=None, questions_path="questions.json"):
        """
        Initialize the CallCategorizationService.
        
        Args:
            logger: Logger instance for logging
            questions_path: Path to the questions.json file
        """
        self.logger = logger or logging.getLogger(__name__)
        
        
        # Load questions from questions.json
        self.questions = self._load_questions(questions_path)
        self.question_texts = self._extract_question_texts()
        
        self.logger.info("CallCategorizationService initialized")
    
    def _load_questions(self, questions_path: str) -> Dict:
        """
        Load questions from the questions.json file.
        
        Args:
            questions_path: Path to the questions.json file
            
        Returns:
            Dict: Questions data
        """
        try:
            if os.path.exists(questions_path):
                with open(questions_path, 'r') as f:
                    return json.load(f)
            else:
                self.logger.warning(f"Questions file not found at {questions_path}")
                return {}
        except Exception as e:
            self.logger.error(f"Error loading questions: {e}")
            return {}
    
    def _extract_question_texts(self) -> Set[str]:
        """
        Extract question texts from the loaded questions data.
        
        Returns:
            Set[str]: Set of question texts
        """
        question_texts = set()
        
        try:
            if self.questions and 'questions' in self.questions:
                for question in self.questions['questions']:
                    if 'text' in question:
                        # Add the question text to the set
                        question_texts.add(question['text'].lower())
            
            self.logger.info(f"Extracted {len(question_texts)} questions")
        except Exception as e:
            self.logger.error(f"Error extracting question texts: {e}")
        
        return question_texts
    
    def categorize_call(self, call_sid: str, category: CallCategory = None, transcript: str = "", duration: float = 0) -> None:
        """
        Categorize a call (for backward compatibility).
        
        Args:
            call_sid: The unique identifier for the call
            category: The category to assign to the call (optional)
            transcript: Transcript from the call (optional)
            duration: Duration of the call in seconds (optional)
        """
        # If category is not provided but transcript is, determine category
        if category is None and transcript:
            category = self._determine_category_from_transcript(transcript)
        
        # If still no category, default to DISCONNECTED
        if category is None:
            category = CallCategory.DISCONNECTED
        
        self.logger.info(f"Call {call_sid} categorized as {category.name}")
        
        # Note: We no longer store data in memory dictionaries
        # Data is now stored in JSON files in the call_data directory


    
    def _determine_category_from_transcript(self, transcript: str) -> CallCategory:
        """
        Determine call category based on transcript content.
        
        Args:
            transcript: The call transcript
            
        Returns:
            CallCategory: The determined category
        """
        if not transcript:
            return CallCategory.DISCONNECTED  # Default to DISCONNECTED if no transcript
        
        # Directly check for state patterns in the transcript
        import re
        state_pattern = r"--- State (\d+) ---"
        states_found = set(re.findall(state_pattern, transcript))
        
        # Get total states from questions.json
        total_states = 0
        if isinstance(self.questions, list):
            total_states = len(self.questions)
        elif isinstance(self.questions, dict) and 'questions' in self.questions:
            total_states = len(self.questions['questions'])
        
        self.logger.info(f"States found in transcript: {states_found}, Total states: {total_states}")
        
        # If all states are found, it's a completed call
        if len(states_found) == total_states and total_states > 0:
            return CallCategory.COMPLETED
        # Otherwise, it's a disconnected call
        else:
            return CallCategory.DISCONNECTED
    

    
    def categorize_from_transcript(self, call_sid: str, transcript: str, duration: float = 0) -> CallCategory:
        """
        Categorize a call based on its transcript.
        
        Args:
            call_sid: The unique identifier for the call
            transcript: The call transcript
            duration: Duration of the call in seconds (optional)
            
        Returns:
            CallCategory: The determined category
        """
        self.logger.info(f"Categorizing call {call_sid} from transcript")
        
        # Determine category from transcript
        category = self._determine_category_from_transcript(transcript)
        self.logger.info(f"Determined category for call {call_sid}: {category.name}")
        
        # Categorize the call (for backward compatibility)
        self.categorize_call(call_sid, category, transcript, duration)
        
        # Return the category for use in transcript processing
        return category

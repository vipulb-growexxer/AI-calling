import os
import time
import logging
from typing import Optional
from services.LLM_agent import LanguageModelProcessor
from services.call_categorization_service import CallCategorizationService

class ConversationHistoryManager:
    """
    Manages conversation history for calls, tracking questions, answers, and followups by state.
    Uses a simple text file approach for storing transcripts.
    """
    
    def __init__(self, logger=None, transcript_dir="transcripts"):
        self.logger = logger or logging.getLogger(__name__)
        self.transcript_dir = transcript_dir
        self.raw_transcript_dir = os.path.join(transcript_dir, "raw")
        self.cleaned_transcript_dir = os.path.join(transcript_dir, "cleaned")
        self.create_transcript_directory()
        self.phone_numbers = {}  # Map call_sid to phone_number
        self.call_timestamps = {}  # Map call_sid to timestamp
    
    def create_transcript_directory(self):
        """Create the directories for storing transcripts if they don't exist."""
        os.makedirs(self.raw_transcript_dir, exist_ok=True)
        os.makedirs(self.cleaned_transcript_dir, exist_ok=True)
        self.logger.info(f"Transcript directories created/verified: {self.raw_transcript_dir}, {self.cleaned_transcript_dir}")
    
    def _get_transcript_path(self, call_sid: str) -> str:
        """Get the path to the raw transcript file for a call."""
        # Generate timestamp if not already created for this call_sid
        if call_sid not in self.call_timestamps:
            import time
            self.call_timestamps[call_sid] = int(time.time())
        
        timestamp = self.call_timestamps[call_sid]
        
        # Use phone number in filename if available
        if call_sid in self.phone_numbers:
            phone = self.phone_numbers[call_sid].replace("+", "").replace(" ", "")
            return os.path.join(self.raw_transcript_dir, f"{phone}_{timestamp}.txt")
        else:
            return os.path.join(self.raw_transcript_dir, f"{call_sid}_{timestamp}.txt")
    
    def add_phone_number(self, call_sid: str, phone_number: str) -> None:
        """
        Add phone number information to the transcript.
        
        Args:
            call_sid: The call SID to associate with this history
            phone_number: The phone number to add
        """
        # Store the phone number for this call_sid
        self.phone_numbers[call_sid] = phone_number
        
        # Now get the transcript path (which will use the phone number)
        transcript_path = self._get_transcript_path(call_sid)
        
        # Create the file if it doesn't exist
        if not os.path.exists(transcript_path):
            with open(transcript_path, "w") as f:
                f.write(f"Call SID: {call_sid}\nPhone Number: {phone_number}\n\n")
            self.logger.info(f"Added phone number {phone_number} to transcript for {call_sid}")
        else:
            # If file exists, read content and check if phone number is already there
            with open(transcript_path, "r") as f:
                content = f.read()
            
            if f"Phone Number:" not in content:
                # Add phone number at the beginning of the file
                with open(transcript_path, "w") as f:
                    f.write(f"Call SID: {call_sid}\nPhone Number: {phone_number}\n\n{content}")
                self.logger.info(f"Added phone number {phone_number} to existing transcript for {call_sid}")
    
    def log_ai_question(self, call_sid: str, text: str, state: int) -> None:
        """
        Log an AI question to the conversation history.
        
        Args:
            call_sid: The call SID to associate with this history
            text: The question text
            state: The current conversation state
        """
        transcript_path = self._get_transcript_path(call_sid)
        
        # Check if this is a new state
        new_state = False
        if not os.path.exists(transcript_path):
            new_state = True
        else:
            with open(transcript_path, "r") as f:
                content = f.read()
                new_state = f"--- State {state} ---" not in content
        
        with open(transcript_path, "a") as f:
            # Add state header if this is a new state
            if new_state:
                f.write(f"\n--- State {state} ---\n")
            
            # Add the AI question
            f.write(f"AI: {text}\n")
            self.logger.info(f"[CONVERSATION_LOG] {call_sid} - AI question: {text[:50]}...")
            
            # Save transcript but don't print it to console
            # if new_state:
            #     self.print_transcript(call_sid)
    
    def log_user_answer(self, call_sid: str, text: str, state: int) -> None:
        """
        Log a user answer to the conversation history.
        
        Args:
            call_sid: The call SID to associate with this history
            text: The answer text
            state: The current conversation state
        """
        transcript_path = self._get_transcript_path(call_sid)
        
        if not os.path.exists(transcript_path):
            self.logger.warning(f"No transcript file found for call_sid: {call_sid}")
            return
        
        with open(transcript_path, "a") as f:
            f.write(f"User: {text}\n\n")
            
        self.logger.info(f"[CONVERSATION_LOG] {call_sid} - User answer: {text[:50]}...")
    
    def print_transcript(self, call_sid: str) -> None:
        """
        Print the full transcript for a call.
        
        Args:
            call_sid: The call SID to print the transcript for
        """
        transcript_path = self._get_transcript_path(call_sid)
        
        if not os.path.exists(transcript_path):
            self.logger.info(f"No transcript available for {call_sid}")
            return
        
        with open(transcript_path, "r") as f:
            transcript = f.read()
            
        self.logger.info(f"CONVERSATION TRANSCRIPT for {call_sid}:\n{transcript}")
    
    def get_transcript(self, call_sid: str) -> Optional[str]:
        """
        Get the full transcript for a call.
        
        Args:
            call_sid: The call SID to get the transcript for
            
        Returns:
            The transcript as a string, or None if not found
        """
        transcript_path = self._get_transcript_path(call_sid)
        
        if not os.path.exists(transcript_path):
            return None
        
        with open(transcript_path, "r") as f:
            return f.read()
    
    def clear_transcript(self, call_sid: str) -> None:
        """
        Clear the transcript for a call.
        
        Args:
            call_sid: The call SID to clear the transcript for
        """
        transcript_path = self._get_transcript_path(call_sid)
        
        if os.path.exists(transcript_path):
            os.remove(transcript_path)
            self.logger.info(f"Cleared transcript for {call_sid}")
            
    def get_cleaned_transcript(self, call_sid: str, config_loader) -> Optional[str]:
        """
        Get a cleaned version of the transcript with overlapping text removed and grammar fixed.
        
        Args:
            call_sid: The call SID to get the transcript for
            config_loader: Configuration loader for LLM initialization
            
        Returns:
            The cleaned transcript as a string, or None if not found
        """
        # Get the raw transcript
        raw_transcript = self.get_transcript(call_sid)
        if not raw_transcript:
            self.logger.warning(f"No transcript found for call_sid: {call_sid}")
            return None
            
        try:
            # Initialize the LLM
            llm_processor = LanguageModelProcessor(config_loader)
            
            # Create the prompt for cleaning the transcript
            prompt = f"""Clean up this conversation transcript by:
1. Removing any overlapping or repeated text
2. Fixing grammatical errors
3. Preserving the original meaning and content
4. Maintaining the conversation structure with AI and User labels
5. Keeping the state sections intact
6. There are state mentioned in the transcript, replace state with 'Question' so state 1 would become Question 1.  

Do NOT add any new information or change the meaning of any responses.

Here's the transcript to clean:

{raw_transcript}

Please provide only the cleaned transcript with no additional commentary."""
            
            # Process with LLM
            self.logger.info(f"Sending transcript for call {call_sid} to LLM for cleaning")
            cleaned_transcript = llm_processor.process(prompt)
            
            # Save the cleaned transcript to a separate file
            timestamp = self.call_timestamps.get(call_sid, int(time.time()))
            
            if call_sid in self.phone_numbers:
                phone = self.phone_numbers[call_sid].replace("+", "").replace(" ", "")
                cleaned_path = os.path.join(self.cleaned_transcript_dir, f"{phone}_{timestamp}.txt")
            else:
                cleaned_path = os.path.join(self.cleaned_transcript_dir, f"{call_sid}_{timestamp}.txt")
                
            with open(cleaned_path, "w") as f:
                f.write(cleaned_transcript)
                
            self.logger.info(f"Saved cleaned transcript for {call_sid} to {cleaned_path}")
            return cleaned_transcript
            
        except Exception as e:
            self.logger.error(f"Error cleaning transcript for {call_sid}: {e}")
            return raw_transcript  # Return the raw transcript if cleaning fails

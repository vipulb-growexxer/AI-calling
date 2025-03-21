"""
Memory B (Conversation Buffer)
- Handles active conversation state
- Stores user responses temporarily
- Used for LLM processing and follow-up questions
- Manages the conversation flow for each state until completion/max tries
"""

import asyncio
from typing import Dict, Optional, Any, List
import logging
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class ConversationState:
    """Class for tracking conversation state"""
    state_index: int = 0
    attempts: int = 0
    expected_output_type: str = ""
    last_response: str = ""
    follow_up_instructions: str = ""
    last_update_time: datetime = field(default_factory=datetime.now)
    max_attempts: int = 2
    original_question: str = ""
    expected_output: str = ""
    followup_attempts: int = 0
    followup_qa_pairs: list = field(default_factory=list)
    max_followup_attempts: int = 2
    extracted_values: Dict[str, Any] = field(default_factory=dict)
    response_type: str = ""
    response_categories: Dict[str, str] = field(default_factory=dict)

class MemoryB:
    """
    Memory B (Conversation Buffer) - Handles active conversation state and user responses
    """
    def __init__(self):
        self.conversation_states: Dict[str, ConversationState] = {}  # call_sid -> ConversationState
        self.response_buffers: Dict[str, str] = {}  # call_sid -> current_response_text
        self.logger = logging.getLogger(__name__)
        
    async def initialize_conversation(self, call_sid: str, initial_state: int = 0) -> None:
        """Initialize a new conversation state for a call"""
        self.conversation_states[call_sid] = ConversationState(state_index=initial_state)
        self.response_buffers[call_sid] = ""
        self.logger.info(f"Initialized conversation state for call {call_sid}")
        
    async def update_state(
        self, 
        call_sid: str, 
        state_index: Optional[int] = None,
        attempts: Optional[int] = None,
        expected_output_type: Optional[str] = None,
        last_response: Optional[str] = None,
        follow_up_instructions: Optional[str] = None,
        max_attempts: Optional[int] = None,
        original_question: Optional[str] = None,
        expected_output: Optional[str] = None,
        followup_attempts: Optional[int] = None,
        followup_qa_pairs: Optional[list] = None,
        max_followup_attempts: Optional[int] = None,
        extracted_values: Optional[Dict[str, Any]] = None,
        response_type: Optional[str] = None,
        response_categories: Optional[Dict[str, str]] = None
    ) -> None:
        """Update conversation state parameters"""
        if call_sid not in self.conversation_states:
            await self.initialize_conversation(call_sid)
            
        state = self.conversation_states[call_sid]
        
        if state_index is not None:
            state.state_index = state_index
        if attempts is not None:
            state.attempts = attempts
        if expected_output_type is not None:
            state.expected_output_type = expected_output_type
        if last_response is not None:
            state.last_response = last_response
        if follow_up_instructions is not None:
            state.follow_up_instructions = follow_up_instructions
        if max_attempts is not None:
            state.max_attempts = max_attempts
        if original_question is not None:
            state.original_question = original_question
        if expected_output is not None:
            state.expected_output = expected_output
        if followup_attempts is not None:
            state.followup_attempts = followup_attempts
        if followup_qa_pairs is not None:
            state.followup_qa_pairs = followup_qa_pairs
        if max_followup_attempts is not None:
            state.max_followup_attempts = max_followup_attempts
        if extracted_values is not None:
            state.extracted_values = extracted_values
        if response_type is not None:
            state.response_type = response_type
        if response_categories is not None:
            state.response_categories = response_categories
            
        state.last_update_time = datetime.now()
        
    async def get_state(self, call_sid: str) -> Optional[ConversationState]:
        """Get current conversation state"""
        return self.conversation_states.get(call_sid)
        
    async def buffer_response(self, call_sid: str, response_text: str) -> None:
        """Store user response text in buffer"""
        if call_sid not in self.response_buffers:
            self.response_buffers[call_sid] = ""
            
        self.response_buffers[call_sid] = response_text
        self.logger.info(f"Buffered response for call {call_sid}: {response_text[:30]}...")
        
    async def get_buffered_response(self, call_sid: str) -> str:
        """Get the current buffered response"""
        return self.response_buffers.get(call_sid, "")
        
    async def clear_buffer(self, call_sid: str) -> None:
        """Clear the response buffer for a call"""
        if call_sid in self.response_buffers:
            self.response_buffers[call_sid] = ""
            
    async def increment_attempts(self, call_sid: str) -> int:
        """Increment the number of attempts for the current state"""
        if call_sid in self.conversation_states:
            self.conversation_states[call_sid].attempts += 1
            return self.conversation_states[call_sid].attempts
        return 0
        
    async def advance_state(self, call_sid: str) -> int:
        """
        Advance to the next state and reset attempts
        Returns the new state index
        """
        if call_sid in self.conversation_states:
            state = self.conversation_states[call_sid]
            state.state_index += 1
            state.attempts = 0
            state.last_response = ""
            state.followup_attempts = 0
            state.followup_qa_pairs = []
            state.extracted_values = {}
            state.response_type = ""
            state.last_update_time = datetime.now()
            self.logger.info(f"Advanced to state {state.state_index} for call {call_sid}")
            return state.state_index
        return 0
        
    async def should_advance_state(self, call_sid: str) -> bool:
        """
        Determine if we should advance to the next state based on:
        1. Expected output achieved, or
        2. Maximum attempts reached, or
        3. Special response types that indicate progression (e.g. "not_comfortable")
        """
        if call_sid not in self.conversation_states:
            return False
            
        state = self.conversation_states[call_sid]
        
        # If we have a valid response type that's not "irrelevant" or "default", advance state
        if state.response_type and state.response_type not in ["irrelevant", "default"]:
            return True
            
        # Check notice period threshold (if relevant)
        if state.state_index == 5 and "notice_period_threshold" in state.extracted_values:
            if state.response_type == "immediate" or state.response_type == "short_notice":
                return True
                
        # Advance if max followup attempts reached
        return state.followup_attempts >= state.max_followup_attempts
        
    async def clear_conversation(self, call_sid: str) -> None:
        """Clear all conversation data for a call"""
        self.conversation_states.pop(call_sid, None)
        self.response_buffers.pop(call_sid, None)
        self.logger.info(f"Cleared conversation data for call {call_sid}")
        
    def is_conversation_active(self, call_sid: str) -> bool:
        """Check if a conversation is currently active"""
        return call_sid in self.conversation_states

    async def set_question_data(self, call_sid: str, question: str, expected_output: str, 
                               response_categories: Optional[Dict[str, str]] = None,
                               max_followups: Optional[int] = None) -> None:
        """Set the original question and expected output for a conversation state."""
        if call_sid not in self.conversation_states:
            self.logger.warning(f"No conversation found for call_sid: {call_sid}")
            return
        
        self.conversation_states[call_sid].original_question = question
        self.conversation_states[call_sid].expected_output = expected_output
        
        if response_categories:
            self.conversation_states[call_sid].response_categories = response_categories
            
        if max_followups:
            self.conversation_states[call_sid].max_followup_attempts = max_followups
            
        self.logger.info(f"Set question data for call_sid: {call_sid}")
    
    async def add_followup_qa(self, call_sid: str, question: str, answer: str) -> bool:
        """Add a follow-up question and answer pair to the conversation."""
        if call_sid not in self.conversation_states:
            self.logger.warning(f"No conversation found for call_sid: {call_sid}")
            return False
        
        self.conversation_states[call_sid].followup_qa_pairs.append((question, answer))
        self.conversation_states[call_sid].followup_attempts += 1
        self.conversation_states[call_sid].last_update_time = datetime.now()
        
        self.logger.info(f"Added followup Q&A for call_sid: {call_sid}, attempt: {self.conversation_states[call_sid].followup_attempts}")
        return True
    
    async def can_ask_followup(self, call_sid: str) -> bool:
        """Check if we can ask another follow-up question."""
        if call_sid not in self.conversation_states:
            self.logger.warning(f"No conversation found for call_sid: {call_sid}")
            return False
        
        return self.conversation_states[call_sid].followup_attempts < self.conversation_states[call_sid].max_followup_attempts
    
    async def get_followup_attempts(self, call_sid: str) -> int:
        """Get the number of follow-up attempts made for a conversation."""
        if call_sid not in self.conversation_states:
            self.logger.warning(f"No conversation found for call_sid: {call_sid}")
            return 0
        
        return self.conversation_states[call_sid].followup_attempts
    
    async def set_extracted_value(self, call_sid: str, key: str, value: Any) -> None:
        """Store an extracted value from the user response."""
        if call_sid not in self.conversation_states:
            self.logger.warning(f"No conversation found for call_sid: {call_sid}")
            return
            
        self.conversation_states[call_sid].extracted_values[key] = value
        self.logger.info(f"Set extracted value for call_sid: {call_sid}, key: {key}, value: {value}")
    
    async def set_response_type(self, call_sid: str, response_type: str) -> None:
        """Set the detected response type."""
        if call_sid not in self.conversation_states:
            self.logger.warning(f"No conversation found for call_sid: {call_sid}")
            return
            
        self.conversation_states[call_sid].response_type = response_type
        self.logger.info(f"Set response type for call_sid: {call_sid}, type: {response_type}")
    
    async def get_follow_up_template(self, call_sid: str) -> str:
        """Get the appropriate follow-up template based on response type."""
        if call_sid not in self.conversation_states:
            self.logger.warning(f"No conversation found for call_sid: {call_sid}")
            return ""
            
        state = self.conversation_states[call_sid]
        response_type = state.response_type
        
        # Special case for notice period
        if state.state_index == 5:
            duration_value = state.extracted_values.get("duration", 0)
            threshold = state.extracted_values.get("notice_period_threshold", 90)
            
            if duration_value > threshold:
                return "long_notice"
            elif duration_value > 0:
                return "short_notice"
            elif response_type == "immediate_pattern":
                return "immediate"
        
        return response_type if response_type else "default"
    
    async def format_follow_up_question(self, call_sid: str, template: str) -> str:
        """Format a follow-up question template with extracted values."""
        if call_sid not in self.conversation_states:
            self.logger.warning(f"No conversation found for call_sid: {call_sid}")
            return template
            
        state = self.conversation_states[call_sid]
        
        # Replace any placeholders with extracted values
        formatted_template = template
        for key, value in state.extracted_values.items():
            placeholder = "{" + key + "}"
            if placeholder in formatted_template:
                formatted_template = formatted_template.replace(placeholder, str(value))
                
        return formatted_template
        
    async def get_conversation_data(self, call_sid: str) -> Dict[str, Any]:
        """Get all data for a conversation that would be needed by LLM."""
        if call_sid not in self.conversation_states:
            self.logger.warning(f"No conversation found for call_sid: {call_sid}")
            return {}
        
        conv = self.conversation_states[call_sid]
        
        # Compile all user responses into a single string
        user_responses = " ".join([self.response_buffers[call_sid]])
        
        # Format followup QA pairs
        followup_qa = []
        for q, a in conv.followup_qa_pairs:
            followup_qa.append({"question": q, "answer": a})
        
        return {
            "state": conv.state_index,
            "original_question": conv.original_question,
            "expected_output": conv.expected_output,
            "user_responses": user_responses,
            "followup_attempts": conv.followup_attempts,
            "followup_qa": followup_qa,
            "response_type": conv.response_type,
            "extracted_values": conv.extracted_values
        }

    async def end_conversation(self, call_sid: str) -> None:
        """End a conversation and clean up resources"""
        if call_sid in self.conversation_states:
            self.logger.info(f"Ending conversation for call {call_sid}")
            # Get the final state for logging
            state = self.conversation_states[call_sid]
            self.logger.info(f"Final state for call {call_sid}: state_index={state.state_index}, attempts={state.attempts}")
            
            # Clean up
            self.conversation_states.pop(call_sid, None)
            self.response_buffers.pop(call_sid, None)
            self.logger.info(f"Conversation ended and resources cleaned up for call {call_sid}")
        else:
            self.logger.warning(f"Attempted to end non-existent conversation for call {call_sid}")

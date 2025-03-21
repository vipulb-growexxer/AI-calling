"""
Conversation Manager
Responsible for managing the conversation flow and state transitions
"""

import asyncio
import json
import logging
import re
from typing import Dict, Any, Optional, List, Tuple
from memory.memory_a import MemoryA
from memory.memory_b import MemoryB
from services.Elevenlabs import ElevenLabsService
from services.LLM_agent import LanguageModelProcessor
from logger.logger_config import logger

class ConversationManager:
    """
    Manages the conversation flow, state transitions, and processing of user responses.
    
    This class is responsible for:
    1. Determining when to advance to the next state
    2. Processing user responses with LLM
    3. Coordinating between Memory A and Memory B
    4. Generating follow-up questions when needed
    """
    
    def __init__(self, memory_a: MemoryA, memory_b: MemoryB, llm_service: LanguageModelProcessor, elevenlabs_service: ElevenLabsService):
        self.memory_a = memory_a
        self.memory_b = memory_b
        self.llm_service = llm_service
        self.elevenlabs_service = elevenlabs_service
        self.logger = logging.getLogger(__name__)
        self.logger.info("ConversationManager initialized")
    
    async def initialize_call(self, call_sid: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Initialize a new call with greeting and preparation.
        
        Returns:
        - success: Whether initialization was successful
        - greeting_text: Greeting message text to convert to audio
        - error: Error message if any
        """
        try:
            # Initialize conversation state in Memory B
            await self.memory_b.initialize_conversation(call_sid, initial_state=0)
            
            # Get greeting message from Memory A
            greeting_msg = "Hello, this is an AI screening call. Please say something to start the call."
            
            # Begin pre-generating all question audio in Memory A asynchronously
            # This won't block the current operation
            self.memory_a.pre_generate_audio(self.elevenlabs_service)
            
            return True, greeting_msg, None
            
        except Exception as e:
            self.logger.error(f"Error initializing call: {e}")
            return False, None, str(e)
    
    async def advance_state(self, call_sid: str) -> Tuple[bool, Optional[bytes], Optional[str]]:
        """
        Advance to the next state and retrieve the next question audio.
        
        Returns:
        - success: Whether state advancement was successful
        - audio_data: Next question audio to play
        - error: Error message if any
        """
        try:
            # Get current state
            current_state = await self.memory_b.get_state(call_sid)
            if current_state is None:
                return False, None, "No active conversation found"
                
            # Calculate next state
            next_state = current_state.state_index + 1
            
            # Check if next state exists in Memory A
            question_data = self.memory_a.get_question_data(next_state)
            if not question_data:
                # No more questions, end the call
                await self.memory_b.clear_conversation(call_sid)
                end_message = "Thank you for your time. The interview is now complete. Goodbye."
                
                # For the end message, we'll return the text instead of generating audio
                # This allows the WebSocketManager to stream it directly
                return True, end_message, None
            
            # Update state in Memory B
            await self.memory_b.update_state(call_sid, state_index=next_state)
            
            # Store question data in Memory B
            question_text = question_data.get("question", "")
            expected_output_type = question_data.get("expected_answer_type", "")
            max_followups = question_data.get("max_followups", 2)
            response_categories = question_data.get("response_categories", {})
            
            # Store additional question metadata in Memory B
            await self.memory_b.set_question_data(
                call_sid, 
                question_text, 
                expected_output_type,
                response_categories=response_categories,
                max_followups=max_followups
            )
            
            # Get audio for the next question from Memory A
            # Wait until audio is ready
            audio_ready = self.memory_a.is_audio_ready(next_state)
            while not audio_ready:
                self.logger.info(f"Waiting for audio to be ready for state {next_state}")
                await asyncio.sleep(0.5)
                audio_ready = self.memory_a.is_audio_ready(next_state)
                
            question_audio = await self.memory_a.get_question_audio(next_state)
            
            if not question_audio:
                return False, None, f"No audio found for state {next_state}"
            
            return True, question_audio, None
            
        except Exception as e:
            self.logger.error(f"Error advancing state: {e}")
            return False, None, str(e)
    
    async def process_response(self, call_sid: str, response_text: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Process a user response for a given call and determine next action.
        Returns: (success, followup_question_text, error_message)
        """
        try:
            # Buffer the response in Memory B
            await self.memory_b.buffer_response(call_sid, response_text)
            
            # Get conversation state
            conv_state = await self.memory_b.get_state(call_sid)
            if not conv_state:
                return False, None, "No active conversation found"
            
            # If this is a response to a follow-up question, update the answer in the followup_qa_pairs
            if conv_state.followup_qa_pairs and len(conv_state.followup_qa_pairs) > 0:
                # Get the most recent follow-up question
                last_qa_idx = len(conv_state.followup_qa_pairs) - 1
                last_question, _ = conv_state.followup_qa_pairs[last_qa_idx]
                
                # Update the answer for this follow-up
                conv_state.followup_qa_pairs[last_qa_idx] = (last_question, response_text)
            
            # Get question data
            question_data = self.memory_a.get_question_data(conv_state.state_index)
            if not question_data:
                return False, None, f"No question data found for state {conv_state.state_index}"
            
            # Process response using LLM
            response_categories = question_data.get("response_categories", {})
            
            if not response_categories:
                self.logger.warning(f"No response categories found for state {conv_state.state_index}")
                return False, None, "No response categories defined"
                
            # Format the input for LLM
            prompt = f"""State: {conv_state.state_index}
Question: {conv_state.original_question}
User response: {response_text}
"""
            # Add previous follow-up context if available
            if conv_state.followup_qa_pairs and len(conv_state.followup_qa_pairs) > 0:
                prompt += "\nPrevious follow-ups:\n"
                for idx, qa_pair in enumerate(conv_state.followup_qa_pairs):
                    # In Memory B, followup_qa_pairs is a list of tuples (question, answer)
                    question, answer = qa_pair
                    prompt += f"Follow-up {idx+1}: {question}\n"
                    prompt += f"Response {idx+1}: {answer}\n"
            
            prompt += f"""
Analyze the user's response and determine which category it falls into. Categories:
"""
            for category, description in response_categories.items():
                prompt += f"- {category}: {description}\n"

            # Create category list as a string
            category_list = ', '.join([f'"{c}"' for c in response_categories.keys()])
            
            prompt += f"""Provide your analysis in JSON format:
{{
  "response_type": [one of: {category_list}, or "default"],
  "extracted_value": [extracted value if applicable],
  "needs_followup": [true/false]
}}

IMPORTANT: Return ONLY valid JSON. Do not include any explanations, notes, or text outside the JSON structure."""
            
            # Process with LLM
            llm_response = self.llm_service.process(prompt)
            
            # Extract JSON from response
            json_start = llm_response.find('{')
            json_end = llm_response.rfind('}') + 1
            
            if json_start == -1 or json_end == 0:
                self.logger.error(f"Invalid LLM response format: {llm_response}")
                analysis = {"response_type": "default", "needs_followup": False}
            else:
                try:
                    json_str = llm_response[json_start:json_end]
                    analysis = json.loads(json_str)
                except json.JSONDecodeError as e:
                    self.logger.error(f"Error parsing LLM response: {e}")
                    analysis = {"response_type": "default", "needs_followup": False}
            
            # Extract analysis results
            response_type = analysis.get("response_type", "default")
            extracted_value = analysis.get("extracted_value")
            needs_followup = analysis.get("needs_followup", False)
            
            # Store response type and extracted values in Memory B
            await self.memory_b.set_response_type(call_sid, response_type)
            
            # Store extracted value if present
            if extracted_value is not None:
                await self.memory_b.set_extracted_value(call_sid, "extracted_value", str(extracted_value))
            
            # Check if we should advance to next state based on response type
            if await self.memory_b.should_advance_state(call_sid):
                self.logger.info(f"Advancing state based on response type: {response_type}")
                return True, None, None
            
            # Check if we can ask a follow-up question
            if not await self.memory_b.can_ask_followup(call_sid) or not needs_followup:
                # Max follow-up attempts reached or no follow-up needed, advance to next state
                self.logger.info(f"No follow-up needed or max attempts reached for call_sid: {call_sid}. Advancing state.")
                return True, None, None
            
            # Get the follow-up instruction template from question data
            follow_up_instructions = question_data.get("follow_up_instructions", {})
            template = follow_up_instructions.get(response_type, follow_up_instructions.get("default", ""))
            
            if not template:
                # No follow-up needed, advance to next state
                self.logger.info(f"No follow-up template for response type: {response_type}. Advancing state.")
                return True, None, None
            
            # Format the template with extracted values
            followup_question = template
            
            # Replace placeholders if any
            if "{extracted_value}" in followup_question and extracted_value is not None:
                followup_question = followup_question.replace("{extracted_value}", str(extracted_value))
            
            # If template still has placeholders, use LLM
            if "{" in followup_question and "}" in followup_question:
                followup_question = await self._generate_followup_question_with_llm(call_sid)
            
            # Store the follow-up question (answer will be added later when user responds)
            await self.memory_b.add_followup_qa(call_sid, followup_question, "")
            
            # Return the follow-up question text instead of audio
            return False, followup_question, None
            
        except Exception as e:
            self.logger.error(f"Error processing response: {e}")
            return False, None, str(e)
    
    async def _generate_followup_question_with_llm(self, call_sid: str) -> str:
        """
        Generate a follow-up question based on conversation data using LLM.
        """
        try:
            # Get all conversation data needed for LLM
            conversation_data = await self.memory_b.get_conversation_data(call_sid)
            
            # Prepare prompt for LLM
            original_question = conversation_data.get("original_question", "")
            user_responses = conversation_data.get("user_responses", "")
            expected_output = conversation_data.get("expected_output", "")
            followup_attempts = conversation_data.get("followup_attempts", 0)
            followup_qa = conversation_data.get("followup_qa", [])
            response_type = conversation_data.get("response_type", "")
            extracted_values = conversation_data.get("extracted_values", {})
            
            # Construct previous conversation context
            previous_context = ""
            for qa in followup_qa:
                previous_context += f"Follow-up: {qa.get('question', '')}\nUser: {qa.get('answer', '')}\n"
            
            # Build prompt
            prompt = f"""
            Original question: {original_question}
            User's response: {user_responses}
            Expected information: {expected_output}
            Response type detected: {response_type}
            Extracted values: {extracted_values}
            
            Previous follow-ups:
            {previous_context}
            
            This is follow-up attempt #{followup_attempts + 1}.
            
            Generate a natural, conversational follow-up question to help the user provide the expected information.
            The question should be friendly but direct, focusing on obtaining the missing information.
            """
            
            # Call LLM service
            followup_question = self.llm_service.process(prompt)
            
            # Clean up the response if needed
            followup_question = followup_question.strip()
            
            return followup_question
            
        except Exception as e:
            self.logger.error(f"Error generating follow-up question: {e}")
            return "Could you please elaborate on that a bit more?"
            
    async def start_conversation(self, call_sid: str) -> bytes:
        """
        Start the conversation by transitioning to state 1
        Returns the audio for the first question
        """
        # Advance to state 1
        await self.memory_b.update_state(call_sid, state_index=1, attempts=0)
        
        # Get question data for state 1
        question_data = self.memory_a.get_question_data(1)
        
        if question_data:
            # Update conversation state with expected output type and patterns
            await self.memory_b.update_state(
                call_sid,
                expected_output_type=question_data.get('expected_answer_type', ''),
                max_followup_attempts=question_data.get('max_followups', 2)
            )
            
            # Store question data in Memory B
            question_text = question_data.get("question", "")
            expected_output_type = question_data.get("expected_answer_type", "")
            response_categories = question_data.get("response_categories", {})
            
            await self.memory_b.set_question_data(
                call_sid, 
                question_text, 
                expected_output_type,
                response_categories=response_categories,
                max_followups=question_data.get('max_followups', 2)
            )
            
        # Retrieve pre-generated audio for state 1
        audio_data = await self.memory_a.get_question_audio(1)
        
        if not audio_data and question_data:
            # If audio isn't pre-generated yet, generate it now
            question_text = question_data.get('question', '')
            audio_data = await self.elevenlabs_service.text_to_speech_full(question_text)
            await self.memory_a.store_question_audio(1, audio_data)
            
        self.logger.info(f"Started conversation for call {call_sid}, transitioned to state 1")
        return audio_data
        
    async def end_conversation(self, call_sid: str) -> None:
        """End the conversation and clean up resources"""
        await self.memory_b.clear_conversation(call_sid)
        self.logger.info(f"Ended conversation for call {call_sid}")

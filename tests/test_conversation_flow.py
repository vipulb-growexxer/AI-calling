#!/usr/bin/env python3
import asyncio
import json
import logging
import sys
import os
import uuid
from typing import Dict, Any, List, Optional, Tuple

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Import necessary modules
from handlers.conversation_manager import ConversationManager
from memory.memory_a import MemoryA
from memory.memory_b import MemoryB
from services.LLM_agent import LanguageModelProcessor

class MockConfigLoader:
    """Mock config loader for testing"""
    
    def __init__(self):
        # Check if we have real AWS credentials in environment variables
        aws_access_key = os.environ.get('AWS_ACCESS_KEY_ID', '')
        aws_secret_key = os.environ.get('AWS_SECRET_ACCESS_KEY', '')
        aws_region = os.environ.get('AWS_REGION', 'us-east-1')
        model_id = os.environ.get('MODEL_ID', 'anthropic.claude-3-sonnet-20240229-v1:0')
        
        # If no real credentials, use mock ones for testing
        if not aws_access_key or not aws_secret_key:
            print("⚠️ No AWS credentials found in environment. Using mock LLM service.")
            self.use_mock_llm = True
        else:
            self.use_mock_llm = False
        
        self.config = {
            'aws': {
                'aws_access_key_id': aws_access_key,
                'aws_secret_access_key': aws_secret_key,
                'aws_region': aws_region
            },
            'llm': {
                'model_id': model_id
            }
        }
    
    def get(self, section, key):
        """Get a config value"""
        return self.config.get(section, {}).get(key, '')


class MockElevenLabsService:
    """Mock service for ElevenLabs to avoid actual audio generation"""
    
    async def text_to_speech(self, text: str):
        """Return fake audio chunks"""
        # Just simulate a chunk of audio data for testing
        yield b'MOCK_AUDIO_DATA'
    
    async def text_to_speech_full(self, text: str):
        """Return fake audio data as a single chunk"""
        return b'MOCK_AUDIO_DATA_FULL'
    
    async def get_voices(self):
        """Return mock voices"""
        return [{"voice_id": "mock_voice_id", "name": "Mock Voice"}]


class MockLLMService:
    """Mock LLM service for testing"""
    
    async def generate_text(self, prompt: str) -> str:
        """Generate text based on prompt"""
        # For testing, just return a simple response based on the prompt
        if "years of professional experience" in prompt:
            return "Thank you for sharing your experience. Could you tell me how many of those years are relevant to this role?"
        elif "current or last CTC" in prompt:
            return "Thank you for sharing your CTC. Could you tell me how much of that is fixed and how much is variable?"
        elif "expected CTC" in prompt:
            return "Thank you for sharing your expected CTC."
        else:
            return "Could you please provide more details?"
    
    def process(self, text: str) -> str:
        """Process text and return a response"""
        # This is the actual method in the real LLM service
        # For testing, we'll just return a simple response
        return "This is a mock response from the LLM service"


async def test_conversation_flow(questions_file: str = 'questions.json'):
    """Test the conversation flow from start to finish with interactive user input"""
    
    print("\n" + "="*50)
    print("INTERACTIVE CONVERSATION FLOW TEST")
    print("="*50)
    
    # Create a unique test call SID
    call_sid = f"test_{uuid.uuid4().hex[:8]}"
    
    # Initialize services
    elevenlabs_service = MockElevenLabsService()
    config_loader = MockConfigLoader()
    if config_loader.use_mock_llm:
        llm_service = MockLLMService()
    else:
        llm_service = LanguageModelProcessor(config_loader)  # Using the actual LLM service
    
    # Initialize Memory A with questions from file
    memory_a = MemoryA()
    
    # Load questions from file if it exists, otherwise use test questions
    if os.path.exists(questions_file):
        try:
            await memory_a.initialize_with_questions(questions_file)
        except Exception as e:
            print(f"Error loading questions from file: {e}")
            print("Using test questions instead")
            # Use test questions instead
            memory_a.questions_data = [
                {
                    "state": 1,
                    "question": "How many years of professional experience do you have?",
                    "expected_answer_type": "number_or_fresher_intern",
                    "max_followups": 2,
                    "response_categories": {
                        "years": "Candidate has professional experience measured in years",
                        "fresher": "Candidate is a fresher or recent graduate",
                        "incomplete": "Answer is incomplete or vague"
                    },
                    "follow_up_instructions": {
                        "years": "Great, out of {extracted_value}, how many years are relevant to this role?",
                        "fresher": "Do you have any internship experience?",
                        "incomplete": "Could you tell me more specifically about your experience?",
                        "default": "Could you clarify your professional experience?"
                    }
                },
                {
                    "state": 2,
                    "question": "What is your current or last CTC?",
                    "expected_answer_type": "amount_with_unit",
                    "max_followups": 2,
                    "response_categories": {
                        "amount": "Candidate has provided a specific amount",
                        "not_comfortable": "Candidate has explicitly refused to share",
                        "irrelevant": "Answer doesn't address the CTC question"
                    },
                    "follow_up_instructions": {
                        "amount": "Thank you. Out of {extracted_value}, how much is fixed?",
                        "not_comfortable": "I understand. Let's move on.",
                        "irrelevant": "Could you share your CTC figure if you're comfortable?",
                        "default": "Could you share your CTC figure if you're comfortable?"
                    }
                },
                {
                    "state": 3,
                    "question": "What is your expected CTC?",
                    "expected_answer_type": "amount_or_hike_or_range",
                    "max_followups": 2,
                    "response_categories": {
                        "amount": "Candidate has provided a specific amount",
                        "hike": "Candidate has provided a percentage hike",
                        "range": "Candidate has provided a range",
                        "irrelevant": "Answer doesn't address the expected CTC"
                    },
                    "follow_up_instructions": {
                        "amount": "",
                        "hike": "",
                        "range": "",
                        "irrelevant": "Could you share your expected CTC?",
                        "default": "Could you share your expected CTC?"
                    }
                }
            ]
    else:
        print(f"Questions file '{questions_file}' not found. Using test questions.")
        # Use test questions
        memory_a.questions_data = [
            {
                "state": 1,
                "question": "How many years of professional experience do you have?",
                "expected_answer_type": "number_or_fresher_intern",
                "max_followups": 2,
                "response_categories": {
                    "years": "Candidate has professional experience measured in years",
                    "fresher": "Candidate is a fresher or recent graduate",
                    "incomplete": "Answer is incomplete or vague"
                },
                "follow_up_instructions": {
                    "years": "Great, out of {extracted_value}, how many years are relevant to this role?",
                    "fresher": "Do you have any internship experience?",
                    "incomplete": "Could you tell me more specifically about your experience?",
                    "default": "Could you clarify your professional experience?"
                }
            },
            {
                "state": 2,
                "question": "What is your current or last CTC?",
                "expected_answer_type": "amount_with_unit",
                "max_followups": 2,
                "response_categories": {
                    "amount": "Candidate has provided a specific amount",
                    "not_comfortable": "Candidate has explicitly refused to share",
                    "irrelevant": "Answer doesn't address the CTC question"
                },
                "follow_up_instructions": {
                    "amount": "Thank you. Out of {extracted_value}, how much is fixed?",
                    "not_comfortable": "I understand. Let's move on.",
                    "irrelevant": "Could you share your CTC figure if you're comfortable?",
                    "default": "Could you share your CTC figure if you're comfortable?"
                }
            },
            {
                "state": 3,
                "question": "What is your expected CTC?",
                "expected_answer_type": "amount_or_hike_or_range",
                "max_followups": 2,
                "response_categories": {
                    "amount": "Candidate has provided a specific amount",
                    "hike": "Candidate has provided a percentage hike",
                    "range": "Candidate has provided a range",
                    "irrelevant": "Answer doesn't address the expected CTC"
                },
                "follow_up_instructions": {
                    "amount": "",
                    "hike": "",
                    "range": "",
                    "irrelevant": "Could you share your expected CTC?",
                    "default": "Could you share your expected CTC?"
                }
            }
        ]
    
    # Initialize Memory B
    memory_b = MemoryB()
    
    # Create ConversationManager with services
    conversation_manager = ConversationManager(
        memory_a=memory_a,
        memory_b=memory_b,
        elevenlabs_service=elevenlabs_service,
        llm_service=llm_service
    )
    
    # Manually pre-generate audio for questions instead of relying on the ConversationManager's async call
    await memory_a.pre_generate_audio(elevenlabs_service)
    
    # Function to get user input
    def get_user_input(prompt: str) -> str:
        return input(prompt)
    
    # ==== Begin Testing Conversation Flow ====
    
    # Step 1: Initialize call
    print("\nSTEP 1: Initialize call")
    success, audio, error = await conversation_manager.initialize_call(call_sid)
    if not success:
        print(f"❌ Initialize call failed: {error}")
        return
    print("✅ Call initialized successfully")
    print(f"   Audio data length: {len(audio)} bytes")
    print("   System: This is an AI generated call, say something to start the call")
    
    # Step 2: First response - User says something to start the call
    print("\nSTEP 2: User says something to start the call")
    user_response = get_user_input("Enter your response to start the call: ")
    
    # Buffer the response in Memory B
    await memory_b.buffer_response(call_sid, user_response)
    
    # Skip processing for state 0 and directly advance to state 1
    print("Skipping processing for state 0 and advancing directly to state 1...")
    success, audio, error = await conversation_manager.advance_state(call_sid)
    if not success:
        print(f"❌ Failed to advance state: {error}")
        return
    print("✅ Advanced to first question state")
    
    # Get current state
    state = await memory_b.get_state(call_sid)
    print(f"   Current state: {state.state_index}")
    
    # Main testing loop
    while state.state_index > 0 and state.state_index < 4:  # Continue until we reach the end state
        # Get the current question based on state
        current_question = memory_a.get_question_data(state.state_index)
        if current_question:
            print(f"\nCurrent Question: {current_question['question']}")
            print(f"Expected Answer Type: {current_question['expected_answer_type']}")
            print(f"Response Categories: {', '.join(current_question['response_categories'].keys())}")
            print(f"Max Follow-ups: {current_question.get('max_followups', 2)}")
        
        # Get user response
        user_response = get_user_input("\nEnter your response: ")
        
        # Process the response
        success, audio, error = await conversation_manager.process_response(call_sid, user_response)
        if not success:
            print(f"❌ Processing response failed: {error}")
            return
        print("✅ Response processed successfully")
        
        # Check if a follow-up question was generated
        if audio:
            # Get and display the follow-up question from memory_b
            updated_state = await memory_b.get_state(call_sid)
            if updated_state.followup_qa_pairs and len(updated_state.followup_qa_pairs) > 0:
                follow_up_question = updated_state.followup_qa_pairs[-1][0]
                print(f"\nFollow-up Question: {follow_up_question}")
                
                # Get user response to follow-up
                user_response = get_user_input("Enter your response to the follow-up: ")
                
                # Process the follow-up response
                success, audio, error = await conversation_manager.process_response(call_sid, user_response)
                if not success:
                    print(f"❌ Processing follow-up response failed: {error}")
                    return
                print("✅ Follow-up response processed successfully")
        
        # Get updated state
        new_state = await memory_b.get_state(call_sid)
        
        # Display state transition information
        if new_state.state_index > state.state_index:
            print(f"\n✅ State advanced from {state.state_index} to {new_state.state_index}")
            state = new_state
        else:
            # Check for follow-up attempts
            print(f"\nState remained at {state.state_index}")
            print(f"Follow-up attempts: {new_state.followup_attempts}")
            state = new_state
    
    # Print final summary
    print("\n" + "="*50)
    print("TEST COMPLETED")
    print("="*50)
    print("✅ Conversation flow test completed successfully")
    print("✅ Reached end state")
    
    # Print the conversation history
    print("\n" + "="*50)
    print("CONVERSATION HISTORY")
    print("="*50)
    
    history = await memory_b.get_conversation_history(call_sid)
    if history:
        for i, (state_idx, question, response) in enumerate(history, 1):
            print(f"\nInteraction {i}:")
            print(f"State: {state_idx}")
            print(f"Question: {question}")
            print(f"Response: {response}")
            
            # Get any follow-up Q&A for this state
            state_data = await memory_b.get_state_data(call_sid, state_idx)
            if state_data and "followup_qa" in state_data and state_data["followup_qa"]:
                for j, (followup_q, followup_a) in enumerate(state_data["followup_qa"], 1):
                    print(f"  Follow-up {j}:")
                    print(f"  Question: {followup_q}")
                    print(f"  Answer: {followup_a}")
    else:
        print("No conversation history found")
    
    print("\nEnd of conversation test")
    

if __name__ == "__main__":
    asyncio.run(test_conversation_flow())

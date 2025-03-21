#!/usr/bin/env python3
import asyncio
import json
import logging
import sys
import uuid
import time
from typing import Dict, Any, Tuple, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

from memory.memory_b import MemoryB
from services.LLM_agent import LanguageModelProcessor
import configparser

MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds

async def warm_up_llm(llm):
    """Pre-warm the LLM to reduce first-request latency"""
    logger.info("Warming up LLM...")
    warm_up_prompt = "Respond with a simple JSON: {\"status\": \"ready\"}"
    start_time = time.time()
    
    try:
        llm_response = llm.process(warm_up_prompt)
        elapsed_time = time.time() - start_time
        logger.info(f"LLM warm-up complete in {elapsed_time:.2f} seconds")
        return True
    except Exception as e:
        logger.warning(f"LLM warm-up failed: {str(e)}")
        return False

async def process_with_llm(llm, prompt: str, max_retries: int = MAX_RETRIES) -> Tuple[bool, Optional[Dict[str, Any]], float]:
    """Process text with LLM with retry logic and timing"""
    retries = 0
    start_time = time.time()
    
    while retries < max_retries:
        try:
            llm_response = llm.process(prompt)
            elapsed_time = time.time() - start_time
            
            # Extract JSON from response
            json_start = llm_response.find('{')
            json_end = llm_response.rfind('}') + 1
            
            if json_start >= 0 and json_end > json_start:
                try:
                    json_str = llm_response[json_start:json_end]
                    analysis = json.loads(json_str)
                    return True, analysis, elapsed_time
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse LLM response as JSON: {llm_response}")
                    retries += 1
            else:
                logger.warning(f"No JSON found in LLM response: {llm_response}")
                retries += 1
                
        except Exception as e:
            logger.warning(f"LLM error (attempt {retries+1}/{max_retries}): {str(e)}")
            retries += 1
            if retries < max_retries:
                logger.info(f"Retrying in {RETRY_DELAY} seconds...")
                await asyncio.sleep(RETRY_DELAY)
    
    elapsed_time = time.time() - start_time
    return False, None, elapsed_time

async def test_memory_b_flow():
    # Load configuration
    config = configparser.ConfigParser()
    config.read('config.ini')
    
    # Initialize LLM processor
    llm = LanguageModelProcessor(config)

    await warm_up_llm(llm)
    
    # Initialize Memory B
    memory_b = MemoryB()
    
    # Load questions from JSON
    with open('questions.json', 'r') as f:
        questions = json.load(f)
    
    # Generate a test call SID
    call_sid = f"test_{uuid.uuid4().hex[:8]}"
    
    # Initialize conversation
    await memory_b.initialize_conversation(call_sid, initial_state=0)
    logger.info(f"Initialized conversation with call_sid: {call_sid}")
    
    # Greeting
    print("\n" + "="*80)
    print("AI: Hello, this is an AI screening call. Please say something to start the call.")
    print("="*80)
    
    # Get initial response
    user_input = input("You: ")
    await memory_b.buffer_response(call_sid, user_input)
    
    # Process each question
    current_state = 1
    while current_state <= len(questions):
        # Get question data
        question_data = next((q for q in questions if q["state"] == current_state), None)
        if not question_data:
            logger.error(f"No question found for state {current_state}")
            break
            
        # Update state in Memory B
        await memory_b.update_state(
            call_sid=call_sid,
            state_index=current_state,
            expected_output_type=question_data["expected_answer_type"],
            original_question=question_data["question"],
            max_followup_attempts=question_data["max_followups"],
            response_categories=question_data.get("response_categories", {})
        )
        
        # Display question
        print("\n" + "-"*80)
        print(f"AI: {question_data['question']}")
        print("-"*80)
        
        # Get user response
        user_response = input("You: ")
        await memory_b.buffer_response(call_sid, user_response)
        
        # Process response with LLM
        response_categories = question_data.get("response_categories", {})

        prompt = f"""State: {question_data['state']}
Question: {question_data['question']}
User response: {user_response}

Analyze the user's response and determine which category it falls into. Categories:
"""
        for category, description in response_categories.items():
            prompt += f"- {category}: {description}\n"

        # Create category list as a string first
        category_list = ', '.join([f'"{c}"' for c in response_categories.keys()])
        
        prompt += f"""Provide your analysis in JSON format:
{{
  "response_type": [one of: {category_list}, or "default"],
  "extracted_value": [extracted value if applicable],
  "needs_followup": [true/false]
}}

IMPORTANT: Return ONLY valid JSON. Do not include any explanations, notes, or text outside the JSON structure."""
        
        # Process with LLM (with retry logic)
        success, analysis, elapsed_time = await process_with_llm(llm, prompt)
        
        if success and analysis:
            response_type = analysis.get("response_type", "default")
            extracted_value = analysis.get("extracted_value")
            
            logger.info(f"LLM processing time: {elapsed_time:.2f} seconds")
            
            # Update memory with response type
            await memory_b.update_state(
                call_sid=call_sid,
                response_type=response_type
            )
            
            # Store extracted value if present
            if extracted_value is not None:
                await memory_b.set_extracted_value(call_sid, "value", str(extracted_value))
                logger.info(f"Extracted value: {extracted_value}")
            
            # Check if follow-up is needed
            follow_up_instructions = question_data.get("follow_up_instructions", {})
            followup_text = follow_up_instructions.get(response_type, follow_up_instructions.get("default", ""))
            
            if followup_text:
                # Replace placeholders if any
                if "{extracted_value}" in followup_text and extracted_value is not None:
                    followup_text = followup_text.replace("{extracted_value}", str(extracted_value))
                
                # Display follow-up
                print("\n" + "-"*80)
                print(f"AI: {followup_text}")
                print("-"*80)
                
                # Get follow-up response
                followup_response = input("You: ")
                
                # Add follow-up to memory
                await memory_b.buffer_response(call_sid, followup_response)
                await memory_b.add_followup_qa(call_sid, followup_text, followup_response)
                
                # Process follow-up response with LLM if needed
                if question_data.get("process_followup", False):
                    followup_prompt = f"""Follow-up Question: {followup_text}
User response: {followup_response}

Analyze the user's response and provide your analysis in JSON format:
{{
  "response_type": "followup",
  "extracted_value": [extracted value if applicable]
}}"""
                    
                    followup_success, followup_analysis, followup_elapsed_time = await process_with_llm(llm, followup_prompt)
                    logger.info(f"Follow-up LLM processing time for state {current_state}: {followup_elapsed_time:.2f} seconds")
            
            # Debug info
            state = await memory_b.get_state(call_sid)
            logger.info(f"State {current_state} - Response type: {response_type}")
        else:
            logger.error("Failed to process response with LLM after multiple retries")
            logger.info(f"Moving to next state despite LLM failure")
        
        # Move to next state
        current_state += 1
    
    # End of conversation
    print("\n" + "="*80)
    print("AI: Thank you for your time. The interview is now complete. Goodbye.")
    print("="*80)
    
    # Clean up
    await memory_b.clear_conversation(call_sid)
    logger.info("Conversation completed")

if __name__ == "__main__":
    asyncio.run(test_memory_b_flow())

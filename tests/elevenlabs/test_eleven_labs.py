#!/usr/bin/env python3
import os
import asyncio
import time
import configparser
import logging
import json
from typing import List, Dict, Optional, AsyncGenerator

# Add root directory to path to import from parent directories
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Import ElevenLabs service
from services.Elevenlabs import ElevenLabsService
import boto3

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Test prompts to generate questions
TEST_PROMPTS = [
    "Generate a simple, direct question asking for someone's name. Max 10 words.",
    "Generate a question asking about years of experience. Max 15 words.",
    "Generate a question about someone's recent project. Max 15 words.",
]

class StreamingLLM:
    """LLM with token streaming support using AWS Bedrock"""
    
    def __init__(self, config):
        self.aws_region = config.get('aws', 'aws_region')
        self.aws_access_key_id = config.get('aws', 'aws_access_key_id') 
        self.aws_secret_access_key = config.get('aws', 'aws_secret_access_key')
        self.model_id = config.get('llm', 'model_id')
        
        self.client = boto3.client(
            "bedrock-runtime",
            region_name=self.aws_region,
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key
        )
        
        # Load system prompt
        try:
            with open('system_prompt.txt', 'r') as file:
                self.system_prompt = file.read().strip()
        except Exception as e:
            logger.warning(f"Could not load system prompt: {e}")
            self.system_prompt = "You are a helpful assistant."
    
    async def generate_tokens(self, prompt: str) -> AsyncGenerator[str, None]:
        """Generate tokens from AWS Bedrock LLM with streaming"""
        # Prepare payload for Llama model
        payload = {
            "prompt": f"{self.system_prompt}\n\nUser: {prompt}\nAssistant:",
            "max_gen_len": 100,
            "temperature": 0.7,
            "top_p": 0.9
        }
        
        logger.info(f"Sending prompt to LLM: {prompt[:50]}...")
        
        try:
            # Stream response from Bedrock
            response_stream = self.client.invoke_model_with_response_stream(
                modelId=self.model_id,
                body=json.dumps(payload)
            )
            
            # Process the streaming response
            stream = response_stream.get('body')
            token_counter = 0
            
            if not stream:
                logger.error("No stream found in response")
                yield "Could not generate response."
                return
                
            for event in stream:
                if 'chunk' in event:
                    chunk = event['chunk']
                    if 'bytes' in chunk:
                        try:
                            chunk_data = json.loads(chunk['bytes'].decode())
                            
                            if 'generation' in chunk_data:
                                token = chunk_data['generation']
                                logger.info(f"Received token chunk: {token}")
                                token_counter += 1
                                yield token
                                
                                # Small delay between tokens to simulate real-time streaming
                                await asyncio.sleep(0.05)
                        except Exception as e:
                            logger.error(f"Error parsing chunk: {e}")
            
            logger.info(f"Total tokens generated: {token_counter}")
            if token_counter == 0:
                yield "No response generated."
                
        except Exception as e:
            logger.error(f"Error streaming from LLM: {str(e)}")
            yield "Could not generate response."

async def test_llm_token_streaming():
    """Test LLM token streaming to ElevenLabs"""
    # Load configuration
    config = configparser.ConfigParser()
    config.read(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'config.ini'))
    
    # Initialize ElevenLabs service
    eleven_labs = ElevenLabsService(config)
    
    # Initialize streaming LLM
    llm = StreamingLLM(config)
    
    # Result summary
    results = []
    
    for prompt_idx, prompt in enumerate(TEST_PROMPTS):
        logger.info(f"\n\nTest #{prompt_idx+1}: Generating response for prompt: {prompt}")
        
        # Timing data
        start_time = time.time()
        first_token_time = None
        first_audio_time = None
        tokens_processed = 0
        
        # Token buffer for streaming
        token_buffer = ""
        
        # Process tokens as they arrive from LLM
        async for token in llm.generate_tokens(prompt):
            # Record first token timing
            if tokens_processed == 0:
                first_token_time = time.time()
                logger.info(f"First token received after {first_token_time - start_time:.3f}s")
            
            tokens_processed += 1
            token_buffer += token
            
            # Get streaming audio for accumulated tokens
            logger.info(f"Sending to ElevenLabs: '{token_buffer.strip()}'")
            
            # Get timing for audio generation
            token_send_time = time.time()
            
            # Process audio response
            audio_chunks = []
            async for audio_chunk in eleven_labs.text_to_speech(token_buffer.strip()):
                # Store first audio chunk time if not already set
                if not first_audio_time and len(audio_chunks) == 0:
                    first_audio_time = time.time()
                    logger.info(f"First audio chunk received after {first_audio_time - start_time:.3f}s")
                    if first_token_time:
                        logger.info(f"Time from first token to first audio: {first_audio_time - first_token_time:.3f}s")
                
                audio_chunks.append(audio_chunk)
            
            # Log timing for this batch
            audio_complete_time = time.time()
            logger.info(f"Audio for batch received in {audio_complete_time - token_send_time:.3f}s")
        
        # Log overall timings
        end_time = time.time()
        logger.info(f"Generated response: '{token_buffer.strip()}'")
        logger.info(f"Total tokens: {tokens_processed}")
        
        if first_token_time:
            logger.info(f"Time to first token: {first_token_time - start_time:.3f}s")
        else:
            logger.info("No tokens were generated")
            
        if first_audio_time:
            logger.info(f"Time to first audio: {first_audio_time - start_time:.3f}s")
        else:
            logger.info("No audio was generated")
            
        logger.info(f"Total processing time: {end_time - start_time:.3f}s")
        
        # Store results
        if first_token_time and first_audio_time:
            results.append({
                "prompt": prompt,
                "response": token_buffer.strip(),
                "tokens": tokens_processed,
                "time_to_first_token": first_token_time - start_time,
                "time_to_first_audio": first_audio_time - start_time,
                "first_token_to_audio": first_audio_time - first_token_time,
                "total_time": end_time - start_time
            })
    
    # Print summary of results
    if results:
        logger.info("\n\n=== TEST SUMMARY ===")
        logger.info(f"Average time from first token to first audio: {sum([r['first_token_to_audio'] for r in results])/len(results):.3f}s")
        logger.info(f"Average time to first audio: {sum([r['time_to_first_audio'] for r in results])/len(results):.3f}s")
        logger.info("Individual results:")
        for r in results:
            logger.info(f"Prompt: {r['prompt']}")
            logger.info(f"  Response: {r['response']}")
            logger.info(f"  Tokens: {r['tokens']}")
            logger.info(f"  First token to audio: {r['first_token_to_audio']:.3f}s")
            logger.info(f"  Time to first audio: {r['time_to_first_audio']:.3f}s")

if __name__ == "__main__":
    asyncio.run(test_llm_token_streaming())

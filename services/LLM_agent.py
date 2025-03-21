import boto3


class LanguageModelProcessor:
    def __init__(self,config_loader):
        self.aws_access_key_id = config_loader.get('aws', 'aws_access_key_id')
        self.aws_secret_access_key = config_loader.get('aws', 'aws_secret_access_key')
        self.aws_region = config_loader.get('aws', 'aws_region')

        self.llm = boto3.client(
            "bedrock-runtime",
            region_name=self.aws_region,
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key
        )
        self.model_id = config_loader.get("llm",'model_id')

        with open('system_prompt.txt', 'r') as file:
            system_prompt = file.read().strip()
        
        self.messages = [{"role":"user","content":[{"text":system_prompt}]}]

    def process(self, text: str) -> str:
        self.messages[0]["content"][0]["text"]+=f"role :user ,content:{text}\n"
        response = self.llm.converse(
            modelId=self.model_id,
            messages=self.messages,
        )
        response_text = response["output"]["message"]["content"][0]["text"]
        self.messages[0]["content"][0]["text"]+=f"role :agent ,content:{response_text}\n"
        return response_text













































# import os
# import boto3
# import json
# import time
# import logging
# from typing import Dict, List, Union, Any, Optional, AsyncGenerator
# import asyncio
# import configparser

# # Configure logging
# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
#     handlers=[logging.StreamHandler()]
# )
# logger = logging.getLogger(__name__)

# class LanguageModelProcessor:
#     def __init__(self, config):
#         """
#         Initialize the LanguageModelProcessor.

#         Args:
#             config: ConfigParser object containing necessary configuration parameters
#         """
#         # Load configuration values
#         self.model_id = config.get('llm', 'model_id')
#         self.aws_region = config.get('aws', 'aws_region')
#         self.aws_access_key_id = config.get('aws', 'aws_access_key_id')
#         self.aws_secret_access_key = config.get('aws', 'aws_secret_access_key')
        
#         # Initialize AWS Bedrock client
#         self.llm = boto3.client(
#             "bedrock-runtime",
#             region_name=self.aws_region,
#             aws_access_key_id=self.aws_access_key_id,
#             aws_secret_access_key=self.aws_secret_access_key
#         )
        
#         # Default system prompt - will be included with each request
#         self.system_prompt = "You are a helpful, harmless, and honest AI assistant. You help a human with answering questions."
#         # Initialize conversation history
#         self.conversation_history = ""

#     def process(self, text: str) -> str:
#         """
#         Process text with the language model (non-streaming).
        
#         Args:
#             text: Input text to be processed
            
#         Returns:
#             str: Generated response
#         """
#         start_time = time.time()
#         logger.info(f"Processing input with LLM: {text[:50]}...")
        
#         # Add user message to history
#         self.conversation_history += f"\nUser: {text}\n"
        
#         # Format message for Bedrock (using only supported roles)
#         messages = [
#             {
#                 "role": "user", 
#                 "content": [
#                     {
#                         "text": f"{self.system_prompt}\n\n{self.conversation_history}\nAssistant:"
#                     }
#                 ]
#             }
#         ]
        
#         try:
#             # Send request to model
#             response = self.llm.converse(
#                 modelId=self.model_id,
#                 messages=messages
#             )
            
#             # Extract and return response content
#             if response and 'messages' in response and len(response['messages']) > 0:
#                 message = response['messages'][0]
#                 if 'content' in message and len(message['content']) > 0:
#                     content = message['content'][0]
#                     if 'text' in content:
#                         result = content['text']
#                         logger.info(f"LLM response received in {time.time() - start_time:.2f}s")
#                         return result
            
#             # Return empty string if response structure is unexpected
#             logger.warning("Unexpected response format from LLM")
#             return ""
            
#         except Exception as e:
#             logger.error(f"Error processing text with LLM: {str(e)}")
#             return f"Error: {str(e)}"

#     async def process_stream(self, text: str) -> AsyncGenerator[str, None]:
#         """
#         Process text with the language model with streaming.
        
#         Args:
#             text: Input text to be processed
            
#         Yields:
#             str: Generated token chunks
#         """
#         start_time = time.time()
#         logger.info(f"Processing input with LLM streaming: {text[:50]}...")
        
#         # Determine if it's a Llama-family model (Meta)
#         is_llama_model = "llama" in self.model_id.lower() or "meta" in self.model_id.lower()
        
#         try:
#             if is_llama_model:
#                 # Llama models use a different payload format
#                 system_prompt = self.system_prompt
#                 payload = {
#                     "prompt": f"{system_prompt}\n\n{self.conversation_history}\nAssistant: {text}",
#                     "max_gen_len": 512,
#                     "temperature": 0.7,
#                     "top_p": 0.9
#                 }
                
#                 # Stream response from Bedrock
#                 response_stream = self.llm.invoke_model_with_response_stream(
#                     modelId=self.model_id,
#                     body=json.dumps(payload)
#                 )
                
#                 # Process the streaming response
#                 stream = response_stream.get('body')
#                 if not stream:
#                     logger.error("No stream found in response")
#                     yield "Error: No response stream available"
#                     return
                    
#                 for event in stream:
#                     if 'chunk' in event:
#                         chunk = event['chunk']
#                         if 'bytes' in chunk:
#                             try:
#                                 chunk_data = json.loads(chunk['bytes'].decode())
                                
#                                 if 'generation' in chunk_data:
#                                     token = chunk_data['generation']
#                                     logger.debug(f"Received token: {token}")
#                                     yield token
#                             except Exception as e:
#                                 logger.error(f"Error parsing chunk: {e}")
#             else:
#                 # For Claude and other models
#                 response_stream = self.llm.converse_stream(
#                     modelId=self.model_id,
#                     messages=[{"role": "user", "content": [{"text": text}]}]
#                 )
                
#                 for event in response_stream:
#                     if 'chunk' in event:
#                         chunk = event['chunk']
#                         if 'message' in chunk:
#                             message = chunk['message']
#                             if message and 'content' in message and message['content']:
#                                 for content_item in message['content']:
#                                     if 'text' in content_item:
#                                         text = content_item['text']
#                                         if text:
#                                             logger.debug(f"Received token: {text}")
#                                             yield text
            
#             logger.info(f"LLM streaming completed in {time.time() - start_time:.2f}s")
            
#         except Exception as e:
#             logger.error(f"Error processing text stream with LLM: {str(e)}")
#             yield f"Error: {str(e)}"

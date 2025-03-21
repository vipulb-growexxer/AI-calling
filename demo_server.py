#!/usr/bin/env python3
"""
Demo Server for AI Call System
This is a simplified version of the server.py script that doesn't use SQS polling,
making it more reliable for demos.
"""

import asyncio
import logging
from aiohttp import web
import json
import uuid

from memory.memory_a import MemoryA
from memory.memory_b import MemoryB
from handlers.websocket_manager import WebSocketManager
from handlers.conversation_manager import ConversationManager
from handlers.twilio_webhook import handle_twilio_webhook
from services.Deepgram_service import DeepgramService
from services.Elevenlabs import ElevenLabsService
from services.LLM_agent import LanguageModelProcessor
from config.config_loader import ConfigLoader
from logger.logger_config import logger

class DemoServer:
    """Simplified server for demos that doesn't use SQS polling"""
    
    def __init__(self):
        """Initialize the demo server"""
        self.logger = logger
        self.logger.info("Initializing Demo AI Call Server")
        
        # Load configuration
        self.config_loader = ConfigLoader(config_file="config.ini")
        
        # Initialize shared data (without SQS polling)
        self.shared_data = {"call_instance_list": []}
        self.call_status_mapping = {
            "canceled": 0,
            "completed": 1,
            "busy": 2,
            "no-answer": 3,
            "failed": 4,
            "queued": 5,
            "ringing": 6,
            "in-progress": 7
        }
        self.queue_messages = {"message_list": []}
        
        # Initialize services
        self.elevenlabs_service = ElevenLabsService(self.config_loader)
        self.deepgram_service = DeepgramService(self.config_loader)
        self.llm_agent = LanguageModelProcessor(self.config_loader)
        
        # Initialize memory
        self.memory_a = MemoryA()
        self.memory_b = MemoryB()
        
        # Initialize conversation manager
        self.conversation_manager = ConversationManager(
            memory_a=self.memory_a,
            memory_b=self.memory_b,
            llm_service=self.llm_agent,
            elevenlabs_service=self.elevenlabs_service
        )
        
        # Initialize WebSocket manager
        self.websocket_manager = WebSocketManager(
            memory_a=self.memory_a,
            memory_b=self.memory_b,
            conversation_manager=self.conversation_manager,
            deepgram_service=self.deepgram_service,
            config_loader=self.config_loader,
            shared_data=self.shared_data,
            call_status_mapping=self.call_status_mapping,
            queue_messages=self.queue_messages
        )
        
        # Initialize web app
        self.app = web.Application()
        self.setup_routes()
        
        self.logger.info("Demo AI Call Server initialized")
        
    def setup_routes(self):
        """Set up HTTP and WebSocket routes"""
        # HTTP routes
        self.app.router.add_post('/webhook', self.handle_webhook)
        
        # WebSocket route
        self.app.router.add_get('/websocket', self.handle_websocket)
        
        # Health check
        self.app.router.add_get('/health', self.health_check)
        
    async def handle_webhook(self, request):
        """Handle Twilio webhook requests"""
        try:
            request_data = await request.post()
            response = await handle_twilio_webhook(
                request_data, 
                self.memory_a, 
                self.memory_b,
                self.shared_data
            )
            return web.Response(text=response, content_type='text/xml')
            
        except Exception as e:
            self.logger.error(f"Error handling webhook: {e}")
            return web.Response(status=500, text=str(e))
            
    async def handle_websocket(self, request):
        """Handle WebSocket connections"""
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        
        try:
            self.logger.info("New WebSocket connection established")
            
            # Send greeting message
            greeting = "This is an AI generated call, say 'start' to begin the interview."
            self.logger.info(f"Sending greeting: {greeting}")
            
            # Generate greeting audio
            try:
                greeting_audio = await self.elevenlabs_service.text_to_speech_full(greeting)
            except Exception as e:
                self.logger.error(f"Error generating greeting audio: {e}")
                greeting_audio = None
            
            # Send greeting audio
            if greeting_audio:
                self.logger.info(f"Generated greeting audio: {len(greeting_audio)} bytes")
                
                # Manually start the conversation with a unique ID for each connection
                demo_call_id = f"demo-call-{uuid.uuid4()}"
                try:
                    await self.memory_b.initialize_conversation(demo_call_id)
                except Exception as e:
                    self.logger.error(f"Error starting conversation in Memory B: {e}")
                
                self.logger.info(f"Started conversation in Memory B with ID: {demo_call_id}")
                
                # Connect to WebSocket with more robust error handling
                try:
                    await self.websocket_manager.handle_websocket(ws)
                except Exception as ws_error:
                    self.logger.error(f"WebSocket handling error: {ws_error}")
                    import traceback
                    self.logger.error(traceback.format_exc())
            else:
                self.logger.error("Failed to generate greeting audio")
            
            return ws
            
        except Exception as e:
            self.logger.error(f"Error handling WebSocket connection: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return ws
        finally:
            # Ensure logging continues even if an error occurs
            self.logger.info("WebSocket connection handling completed")
            
    async def health_check(self, request):
        """Simple health check endpoint"""
        return web.Response(text="OK")
        
    async def start(self):
        """Start the demo server"""
        try:
            # Initialize Memory A with questions
            await self.memory_a.initialize_with_questions("questions.json")
            
            # Pre-generate audio for all questions
            await self.memory_a.pre_generate_audio(self.elevenlabs_service)
            
            # Create application
            self.app = web.Application()
            
            # Add routes
            self.app.router.add_get('/health', self.health_check)
            self.app.router.add_post('/webhook', self.handle_webhook)
            self.app.router.add_get('/websocket', self.handle_websocket)
            
            # Create runner and site
            runner = web.AppRunner(self.app)
            await runner.setup()
            
            # Try multiple ports if 8000 is in use
            ports_to_try = [8000, 8001, 8002, 8003, 8004, 8005]
            for port in ports_to_try:
                try:
                    site = web.TCPSite(runner, '0.0.0.0', port)
                    await site.start()
                    self.logger.info(f"Server started on port {port}")
                    break  # Continue execution rather than returning
                except OSError as port_error:
                    self.logger.warning(f"Port {port} is in use: {port_error}")
            else:
                # If no ports are available
                raise RuntimeError("Could not find an available port to start the server")
            
            self.logger.info("Server initialization complete")
            
            # Keep the server running
            while True:
                await asyncio.sleep(3600)  # Sleep for an hour and keep checking
                self.logger.info("Server heartbeat - still active")
        
        except Exception as e:
            self.logger.error(f"Error starting server: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            raise
        
async def main():
    """Main entry point"""
    server = DemoServer()
    await server.start()

if __name__ == "__main__":
    asyncio.run(main())

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
import websockets

from memory.memory_a import MemoryA
from memory.memory_b import MemoryB
from memory.memory_c import MemoryC
from handlers.websocket_manager import WebSocketManager
from handlers.conversation_manager import ConversationManager
from handlers.twilio_webhook import handle_twilio_webhook
from services.Deepgram_service import DeepgramService
from services.Elevenlabs import ElevenLabsService
from services.LLM_agent import LanguageModelProcessor
from services.call_categorization_service import CallCategorizationService
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
        self.memory_c = MemoryC()
        
        # Initialize conversation manager
        self.conversation_manager = ConversationManager(
            memory_a=self.memory_a,
            memory_b=self.memory_b,
            llm_service=self.llm_agent,
            elevenlabs_service=self.elevenlabs_service
        )
        
        # Initialize call categorization service
        self.call_categorization_service = CallCategorizationService()
        
        # Initialize WebSocket manager
        self.websocket_manager = WebSocketManager(
            memory_a=self.memory_a,
            memory_b=self.memory_b,
            memory_c=self.memory_c,
            conversation_manager=self.conversation_manager,
            deepgram_service=self.deepgram_service,
            config_loader=self.config_loader,
            call_categorization_service=self.call_categorization_service,
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
            
    async def health_check(self, request):
        """Simple health check endpoint"""
        return web.Response(text="OK")
        
    async def start(self):
        """Start the demo server"""
        try:
            # Initialize Memory A with questions
            await self.memory_a.initialize_with_questions("questions.json")
            
            # Pre-warm the LLM to reduce cold start latency
            await self.conversation_manager.warm_up_llm()
            
            # Pre-generate audio for all questions
            await self.memory_a.pre_generate_audio(self.elevenlabs_service)

            # Initialize Memory C with default fillers
            await self.memory_c.initialize_with_fillers()

            # Pre-generate audio for all fillers
            await self.memory_c.pre_generate_audio(self.elevenlabs_service)
            
            # Create application
            self.app = web.Application()
            
            # Add routes
            self.app.router.add_get('/health', self.health_check)
            self.app.router.add_post('/webhook', self.handle_webhook)
            
            # Start the web server
            runner = web.AppRunner(self.app)
            await runner.setup()
            site = web.TCPSite(runner, '0.0.0.0', 8000)
            await site.start()
            self.logger.info("Web server started on port 8000")
            
            # Start WebSocket server on port 8001 using websockets library
            port = 8001
            
            # This is the websocket function that is activated when a client (Twilio) connects
            ws_server = await websockets.serve(
                lambda websocket: self.websocket_manager.handle_websocket(client_ws=websocket),
                '0.0.0.0',
                port
            )
            self.logger.info(f"WebSocket server started on port {port}")
            
            # Wait for server to close
            await ws_server.wait_closed()
            self.logger.info("WebSocket server closed")
            
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

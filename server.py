import logging
import asyncio
import json
import os
from aiohttp import web
import aiohttp
from websockets.exceptions import ConnectionClosed

from config.config_loader import ConfigLoader
from memory.memory_a import MemoryA
from memory.memory_b import MemoryB
from handlers.conversation_manager import ConversationManager
from handlers.twilio_webhook import handle_twilio_webhook
from handlers.websocket_manager import WebSocketManager
from services.Elevenlabs import ElevenLabsService
from services.Deepgram_service import DeepgramService
from services.LLM_agent import LanguageModelProcessor
from tasks.poll_queue import poll_queue
from tasks.check_status_second import call_status_check

# Configure logging
from logger.logger_config import logger

class AICallServer:
    """
    Main server implementation for the AI Call system.
    
    Handles:
    - HTTP endpoints for Twilio webhooks
    - WebSocket connections for real-time audio streaming
    - Initialization of all components
    - Outbound call management through AWS SQS queue
    """
    
    def __init__(self, config_file="config.ini"):
        # Load configuration
        self.config_loader = ConfigLoader(config_file)
        self.logger = logging.getLogger(__name__)
        
        # Initialize shared data for outbound calls
        self.shared_data = {"call_instance_list": []}
        self.queue_messages = {"message_list": []}
        self.duplicate_message_set = set()
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
        
        # Initialize services
        self.elevenlabs_service = ElevenLabsService(config_loader=self.config_loader)
        self.deepgram_service = DeepgramService(config_loader=self.config_loader)
        self.llm_processor = LanguageModelProcessor(config_loader=self.config_loader)
        
        # Initialize memory systems
        self.memory_a = MemoryA()
        self.memory_b = MemoryB()
        
        # Initialize conversation manager
        self.conversation_manager = ConversationManager(
            memory_a=self.memory_a,
            memory_b=self.memory_b,
            llm_service=self.llm_processor,
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
        
        self.logger.info("AI Call Server initialized")
        
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
            await self.websocket_manager.handle_websocket(ws)
            
        except ConnectionClosed:
            self.logger.info("WebSocket connection closed")
        except Exception as e:
            self.logger.error(f"WebSocket error: {e}")
        finally:
            if not ws.closed:
                await ws.close()
                
        return ws
        
    async def health_check(self, request):
        """Simple health check endpoint"""
        return web.json_response({"status": "ok"})
        
    async def initialize(self):
        """Initialize components that require async setup"""
        try:
            # Load questions from JSON file
            questions_file = os.path.join(os.path.dirname(__file__), 'questions.json')
            await self.memory_a.initialize_with_questions(questions_file)
            
            # Pre-generate audio for questions (don't await, let it run in background)
            asyncio.create_task(self.memory_a.pre_generate_audio(self.elevenlabs_service))
            
            # Start outbound call management tasks
            asyncio.create_task(poll_queue(
                configloader=self.config_loader,
                shared_data=self.shared_data,
                queue_messages=self.queue_messages,
                dup_set=self.duplicate_message_set
            ))
            
            asyncio.create_task(call_status_check(
                shared_data=self.shared_data,
                call_status_mapping=self.call_status_mapping,
                configloader=self.config_loader,
                queue_messages=self.queue_messages,
                dup_set=self.duplicate_message_set
            ))
            
            self.logger.info("Server initialization complete")
            
        except Exception as e:
            self.logger.error(f"Error during initialization: {e}")
            raise
            
    def run(self, host='0.0.0.0', port=8000):
        """Run the server"""
        self.logger.info(f"Starting server on {host}:{port}")
        
        # Initialize async components
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.initialize())
        
        # Start the server
        web.run_app(self.app, host=host, port=port)


if __name__ == "__main__":
    server = AICallServer()
    server.run()

from elevenlabs import VoiceSettings
from elevenlabs.client import ElevenLabs
import base64
import io
import logging

class ElevenLabsService:
    def __init__(self,config_loader):
        self.tts_voice_id = config_loader.get('tts', 'voice_id')
        self.elevenlabs_api_key = config_loader.get('tts', 'api_key')
        self.elevenlabs_model = config_loader.get('tts', 'tts_model')
        
        self.client = ElevenLabs(api_key=self.elevenlabs_api_key)
        self.voice_settings = VoiceSettings(stability=0.6, similarity_boost=1.0, style=0.1, use_speaker_boost=True)
        self.logger = logging.getLogger(__name__)
 
    async def text_to_speech(self, text: str):
        """
        Stream audio in chunks for real-time playback
        Returns base64-encoded audio chunks as a generator
        """
        audio_stream = self.client.text_to_speech.convert_as_stream(
            text=text,
            voice_id=self.tts_voice_id,
            model_id=self.elevenlabs_model,
            voice_settings=self.voice_settings,
            output_format="ulaw_8000",
            optimize_streaming_latency=4
        )
        for chunk in audio_stream:
            yield base64.b64encode(chunk).decode('utf-8')
            
    async def text_to_speech_full(self, text: str) -> bytes:
        """
        Generate complete audio data for a text input
        Returns the full audio as bytes for storage in Memory A
        """
        try:
            self.logger.info(f"Generating full audio for text: {text[:30]}...")
            
            # Generate audio as a complete file
            audio_data = self.client.text_to_speech.convert(
                text=text,
                voice_id=self.tts_voice_id,
                model_id=self.elevenlabs_model,
                voice_settings=self.voice_settings,
                output_format="ulaw_8000"
            )
            
            # If audio_data is a generator, collect all chunks
            if hasattr(audio_data, '__iter__') and not isinstance(audio_data, (bytes, bytearray)):
                collected_data = bytearray()
                for chunk in audio_data:
                    collected_data.extend(chunk)
                audio_data = bytes(collected_data)
            
            self.logger.info(f"Generated {len(audio_data)} bytes of audio")
            return audio_data
            
        except Exception as e:
            self.logger.error(f"Error generating audio: {str(e)}")
            # Return empty bytes in case of error
            return b""

async def generate_audio(api_key, voice_id, text, model="eleven_flash_v2"):
    """
    Generate audio using ElevenLabs API directly (non-class method)
    
    Args:
        api_key: ElevenLabs API key
        voice_id: ID of the voice to use
        text: Text to convert to speech
        model: Model ID to use
        
    Returns:
        Audio data as bytes
    """
    import logging
    from elevenlabs import VoiceSettings
    from elevenlabs.client import ElevenLabs
    
    logger = logging.getLogger(__name__)
    logger.info(f"Generating audio for: {text[:30]}...")
    
    try:
        # Initialize client
        client = ElevenLabs(api_key=api_key)
        voice_settings = VoiceSettings(stability=0.6, similarity_boost=1.0, style=0.1, use_speaker_boost=True)
        
        # Generate audio
        audio_data = client.text_to_speech.convert(
            text=text,
            voice_id=voice_id,
            model_id=model,
            voice_settings=voice_settings,
            output_format="mp3_44100_128",  # Use valid format instead of just "mp3"
            optimize_streaming_latency=4
        )
        
        # If audio_data is a generator, collect all chunks
        if hasattr(audio_data, '__iter__') and not isinstance(audio_data, (bytes, bytearray)):
            collected_data = bytearray()
            for chunk in audio_data:
                collected_data.extend(chunk)
            audio_data = bytes(collected_data)
        
        logger.info(f"Generated {len(audio_data)} bytes of audio")
        return audio_data
        
    except Exception as e:
        logger.error(f"Error generating audio: {str(e)}")
        # Return empty bytes in case of error
        return b""

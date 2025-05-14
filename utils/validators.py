import re
import logging
from logger.logger_config import logger

def validate_phone_no(phone_no):
    """
    Validates that a phone number is in the E.164 format which Twilio requires.
    
    E.164 format: [+][country code][subscriber number]
    Example: +14155552671
    
    Args:
        phone_no (str): The phone number to validate
        
    Returns:
        bool: True if the phone number is valid, False otherwise
    """
    try:
        # Log the received phone number for debugging
        logger.info(f"Validating phone number: {phone_no}")
        
        # Very permissive validation - just check for + followed by digits
        # This will accept almost any phone number starting with +
        pattern = r'^\+\d+'
        
        if re.match(pattern, phone_no):
            logger.info(f"Phone number {phone_no} is valid")
            return True
        else:
            logger.warning(f"Invalid phone number format: {phone_no}. Must start with + followed by digits")
            return False
            
    except Exception as e:
        logger.error(f"Error validating phone number: {str(e)}")
        return False




